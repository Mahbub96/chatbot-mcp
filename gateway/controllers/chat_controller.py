from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from agent.llm import complete_llm, stream_llm
from config import BANGLA_MODEL, CODE_MODEL, MEMORY_ENABLED, MODEL as DEFAULT_UPSTREAM_MODEL, VISION_MODEL
from gateway.controllers.tool_controller import execute_tool_with_policy
from gateway.helpers.http_utils import (
    build_chunk_payload,
    build_non_stream_response,
    has_multimodal,
    inject_memory_context,
    json_error,
    latest_user_text,
    parse_completion_request,
    resolve_memory_scope,
    sse_data,
)
from gateway.helpers.memory_logic import (
    build_cv_context_answer,
    build_document_ingest_ack,
    build_exact_cv_response,
    build_exact_shared_response,
    build_identity_dispute_answer,
    build_memory_fallback_answer,
    build_memory_missing_answer,
    build_offer_intent_answer,
    build_shared_summary_response,
    build_user_profile_summary,
    detect_fact_slots,
    is_cv_query,
    is_exact_cv_request,
    is_exact_shared_request,
    is_offer_intent_query,
    is_personal_memory_query,
    is_shared_summary_request,
    is_user_profile_summary_query,
    looks_like_structured_document_text,
    matched_memories_for_query,
    pick_best_shared_memory,
    select_context_memories,
    user_disputes_identity,
)
from gateway.helpers.rate_limiter import InMemoryRateLimiter
from memory import memory_service
from router.model_router import pick_upstream_model
from router.tool_router import maybe_run_legacy_keyword_tool

logger = logging.getLogger(__name__)

ERR_TOO_MANY_REQUESTS = "Too many requests"
ERR_INVALID_JSON_BODY = "Invalid JSON body"
ERR_BODY_OBJECT_REQUIRED = "Request body must be an object"
TOOL_TEST_FILE_PATH = "test.txt"

rate_limiter = InMemoryRateLimiter(window_seconds=100, max_requests=100)
BANGLA_MODEL_COOLDOWN_SECONDS = 300
FAST_BANGLA_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
_model_unavailable_until: dict[str, float] = {}


def is_generic_image_refusal(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "i'm not able to provide help with this conversation",
        "i am not able to provide help with this conversation",
        "can't help with this conversation",
    )
    return any(marker in lowered for marker in markers)


def build_image_refusal_diagnostic(model: str) -> str:
    return (
        "I couldn't analyze the image with the current vision path. "
        f"Selected model: {model}. "
        "Please retry with a publicly reachable image URL (not private/local/base64) "
        "and include a short text prompt about what you want explained."
    )


def is_upstream_error_token(token: str) -> bool:
    text = (token or "").strip()
    return text.startswith("[LLM_ERROR") or text.startswith("[NETWORK_ERROR]") or text.startswith("[LLM_EXCEPTION]")


def looks_like_missing_personal_info_reply(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "i don't have that information",
        "i don't have information about",
        "you haven't shared",
        "i don't know your",
        "i do not know your",
        "i'm not aware of your",
        "i am not aware of your",
        "i'm not sure about your",
    )
    return any(marker in lowered for marker in markers)


def resolve_local_personal_fallback(
    *,
    user_text: str,
    memory_scope: str,
    query_matched_memories: list[dict[str, Any]],
) -> str | None:
    fallback = build_memory_fallback_answer(user_text, query_matched_memories)
    if fallback:
        return fallback
    pools: list[list[dict[str, Any]]] = []
    pools.append(memory_service.list_profile_facts(memory_scope=memory_scope, limit=50))
    pools.append(memory_service.list_profile_memories(memory_scope=memory_scope, limit=50))
    if memory_scope != "global":
        pools.append(memory_service.list_profile_facts(memory_scope="global", limit=50))
        pools.append(memory_service.list_profile_memories(memory_scope="global", limit=50))
    pools.append(memory_service.list_profile_facts_any_scope(limit=80))
    pools.append(memory_service.list_profile_memories_any_scope(limit=120))
    for pool in pools:
        if not pool:
            continue
        rematched = matched_memories_for_query(user_text, pool)
        fallback = build_memory_fallback_answer(user_text, rematched)
        if fallback:
            return fallback
    return None


def normalize_chat_error(exc: Exception, *, had_image_input: bool, model: str) -> str:
    msg = str(exc)
    if had_image_input and "[LLM_ERROR 500]" in msg:
        return (
            "Vision request failed on upstream model. "
            f"Configured model: {model}. "
            "Use a publicly reachable image URL (not base64) and verify "
            "that this model supports image understanding in your NVIDIA account."
        )
    return msg


def should_fallback_bangla_model(upstream_model: str, error_text: str) -> bool:
    if not BANGLA_MODEL or upstream_model != BANGLA_MODEL:
        return False
    if not DEFAULT_UPSTREAM_MODEL or DEFAULT_UPSTREAM_MODEL == BANGLA_MODEL:
        return False
    return "[LLM_ERROR 404]" in error_text


def mark_model_unavailable(model_id: str, cooldown_seconds: int) -> None:
    if not model_id:
        return
    _model_unavailable_until[model_id] = time.time() + max(1, cooldown_seconds)


def is_model_temporarily_unavailable(model_id: str) -> bool:
    until = _model_unavailable_until.get(model_id or "")
    if not until:
        return False
    if time.time() >= until:
        _model_unavailable_until.pop(model_id, None)
        return False
    return True


def choose_runtime_model(preferred_model: str) -> str:
    if (
        preferred_model == BANGLA_MODEL
        and BANGLA_MODEL
        and DEFAULT_UPSTREAM_MODEL
        and DEFAULT_UPSTREAM_MODEL != BANGLA_MODEL
        and is_model_temporarily_unavailable(BANGLA_MODEL)
    ):
        if FAST_BANGLA_FALLBACK_MODEL and FAST_BANGLA_FALLBACK_MODEL != BANGLA_MODEL:
            return FAST_BANGLA_FALLBACK_MODEL
        return DEFAULT_UPSTREAM_MODEL
    return preferred_model


def bangla_fallback_model() -> str:
    if FAST_BANGLA_FALLBACK_MODEL and FAST_BANGLA_FALLBACK_MODEL != BANGLA_MODEL:
        return FAST_BANGLA_FALLBACK_MODEL
    return DEFAULT_UPSTREAM_MODEL


async def handle_chat_completions(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, ERR_TOO_MANY_REQUESTS)
    try:
        body = await request.json()
    except Exception:
        return json_error(400, ERR_INVALID_JSON_BODY)
    if not isinstance(body, dict):
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    messages, stream = parse_completion_request(body)
    if not messages:
        return json_error(400, "messages must be a non-empty array")
    memory_scope = resolve_memory_scope(request, body)
    llm_messages = messages
    user_text = latest_user_text(messages)
    query_matched_memories: list[dict[str, Any]] = []

    if user_disputes_identity(user_text):
        dispute_answer = build_identity_dispute_answer()
        if not stream:
            return build_non_stream_response(dispute_answer)
        async def dispute_stream():
            yield ":\n\n"; yield sse_data(build_chunk_payload(chunk_id="identity-dispute", delta_content=dispute_answer)); yield sse_data(build_chunk_payload(chunk_id="identity-dispute", finish_reason="stop")); yield "data: [DONE]\n\n"
        return StreamingResponse(dispute_stream(), media_type="text/event-stream")

    if MEMORY_ENABLED and user_text:
        try:
            memories = memory_service.search(query=user_text, memory_scope=memory_scope, limit=10)
            query_matched_memories = matched_memories_for_query(user_text, select_context_memories(user_text, memories))
            if not query_matched_memories and detect_fact_slots(user_text).intersection({"name", "university", "email"}):
                trusted = memory_service.list_profile_facts(memory_scope=memory_scope, limit=20) or memory_service.list_profile_facts(memory_scope="global", limit=20)
                query_matched_memories = matched_memories_for_query(user_text, trusted)
            llm_messages = inject_memory_context(messages, query_matched_memories)
        except Exception as exc:
            logger.warning("Memory retrieval failed: %s", exc)

    if has_multimodal(llm_messages) and not VISION_MODEL:
        return json_error(400, "Image input detected but VISION_MODEL is not configured. Set VISION_MODEL to a vision-capable NVIDIA NIM model id.")

    selected_model = pick_upstream_model(llm_messages, default_model=DEFAULT_UPSTREAM_MODEL, bangla_model=BANGLA_MODEL, code_model=CODE_MODEL or None, vision_model=VISION_MODEL or None)
    upstream_model = choose_runtime_model(selected_model)
    tool_output = maybe_run_legacy_keyword_tool(
        llm_messages,
        tool_runner=lambda n, a: execute_tool_with_policy(n, a, approval_id=None),
        test_file_path=TOOL_TEST_FILE_PATH,
    )
    tool_prefix = f"\n[TOOL RESULT]\n{json.dumps(tool_output)}\n" if tool_output is not None else ""
    if tool_output is not None and tool_output.get("requires_approval") is True:
        if not stream:
            return build_non_stream_response(tool_prefix)

        async def approval_only_stream():
            yield ":\n\n"
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
            yield "data: [DONE]\n\n"

        return StreamingResponse(approval_only_stream(), media_type="text/event-stream")

    if MEMORY_ENABLED and user_text and looks_like_structured_document_text(user_text) and not has_multimodal(llm_messages):
        try: memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
        except Exception as exc: logger.warning("Structured document memory write failed: %s", exc)
        ingest_ack = build_document_ingest_ack()
        if not stream:
            return build_non_stream_response(tool_prefix + ingest_ack)

        async def ingest_ack_stream():
            yield ":\n\n"
            if tool_prefix:
                yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
            yield sse_data(build_chunk_payload(chunk_id="doc-ingest", delta_content=ingest_ack))
            yield sse_data(build_chunk_payload(chunk_id="doc-ingest", finish_reason="stop"))
            yield "data: [DONE]\n\n"

        return StreamingResponse(ingest_ack_stream(), media_type="text/event-stream")
    if MEMORY_ENABLED and user_text and is_user_profile_summary_query(user_text) and not has_multimodal(llm_messages):
        return build_non_stream_response(tool_prefix + build_user_profile_summary(memory_service.list_profile_memories_any_scope(limit=300)))
    if MEMORY_ENABLED and user_text and is_exact_shared_request(user_text) and not has_multimodal(llm_messages):
        best = pick_best_shared_memory(memory_service.list_profile_memories_any_scope(limit=400))
        return build_non_stream_response(tool_prefix + (build_exact_shared_response(best) if best else "I couldn't find an exact shared item in local memory."))
    if MEMORY_ENABLED and user_text and is_shared_summary_request(user_text) and not has_multimodal(llm_messages):
        return build_non_stream_response(tool_prefix + build_shared_summary_response(memory_service.list_profile_memories_any_scope(limit=400)))
    if user_text and is_offer_intent_query(user_text) and not has_multimodal(llm_messages):
        return build_non_stream_response(tool_prefix + build_offer_intent_answer())

    memory_missing_answer = None
    if MEMORY_ENABLED and user_text and not query_matched_memories and not has_multimodal(llm_messages) and not looks_like_structured_document_text(user_text):
        memory_missing_answer = build_memory_missing_answer(user_text)
    if MEMORY_ENABLED and user_text and is_cv_query(user_text) and not has_multimodal(llm_messages):
        if is_exact_cv_request(user_text):
            cv_full = memory_service.latest_profile_full(memory_scope=memory_scope) or memory_service.latest_profile_full(memory_scope="global") or memory_service.latest_profile_full_any_scope()
            if cv_full and (cv_full.get("text") or "").strip():
                return build_non_stream_response(tool_prefix + build_exact_cv_response(str(cv_full.get("text") or "")))
        richer = memory_service.list_profile_memories(memory_scope=memory_scope, limit=8) or memory_service.list_profile_memories(memory_scope="global", limit=8) or memory_service.list_profile_facts_any_scope(limit=8)
        cv_context = build_cv_context_answer(richer or query_matched_memories)
        if cv_context: memory_missing_answer = cv_context

    if not stream:
        try:
            text = await complete_llm(llm_messages, model=upstream_model)
            if has_multimodal(llm_messages) and is_generic_image_refusal(text):
                text = build_image_refusal_diagnostic(upstream_model)
            if (
                MEMORY_ENABLED
                and user_text
                and is_personal_memory_query(user_text)
                and looks_like_missing_personal_info_reply(text)
            ):
                local_fallback = resolve_local_personal_fallback(
                    user_text=user_text,
                    memory_scope=memory_scope,
                    query_matched_memories=query_matched_memories,
                )
                if local_fallback:
                    text = local_fallback
            if MEMORY_ENABLED and user_text:
                memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
                memory_service.maybe_store_from_assistant_turn(text=text, memory_scope=memory_scope)
            return build_non_stream_response(tool_prefix + text)
        except Exception as exc:
            if should_fallback_bangla_model(upstream_model, str(exc)):
                mark_model_unavailable(BANGLA_MODEL, BANGLA_MODEL_COOLDOWN_SECONDS)
                text = await complete_llm(llm_messages, model=bangla_fallback_model())
                return build_non_stream_response(tool_prefix + text)
            fallback_answer = build_memory_fallback_answer(user_text, query_matched_memories)
            if fallback_answer:
                return build_non_stream_response(tool_prefix + fallback_answer)
            return json_error(502, normalize_chat_error(exc, had_image_input=has_multimodal(llm_messages), model=upstream_model))

    async def generate():
        yield ":\n\n"
        is_vision_request = has_multimodal(llm_messages)
        hold_personal_stream = bool(user_text and is_personal_memory_query(user_text) and not is_vision_request)
        if tool_prefix:
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
        collected_tokens: list[str] = []
        try:
            async for token in stream_llm(llm_messages, model=upstream_model):
                if token:
                    if is_upstream_error_token(token):
                        fallback_answer = build_memory_fallback_answer(user_text, query_matched_memories)
                        if fallback_answer and not collected_tokens:
                            yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=fallback_answer))
                        else:
                            msg = normalize_chat_error(
                                RuntimeError(token),
                                had_image_input=is_vision_request,
                                model=upstream_model,
                            )
                            yield sse_data(build_chunk_payload(chunk_id="error", delta_content=f"[ERROR] {msg}", finish_reason="stop"))
                        yield "data: [DONE]\n\n"
                        return
                    collected_tokens.append(token)
                    if not is_vision_request and not hold_personal_stream:
                        yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=token))
        except Exception as exc:
            fallback_answer = build_memory_fallback_answer(user_text, query_matched_memories)
            if fallback_answer and not collected_tokens:
                yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=fallback_answer))
                yield sse_data(build_chunk_payload(chunk_id="memory-fallback", finish_reason="stop"))
                yield "data: [DONE]\n\n"
                return
            yield sse_data(build_chunk_payload(chunk_id="error", delta_content=f"[ERROR] {str(exc)}", finish_reason="stop"))
        final_text = "".join(collected_tokens)
        if (
            MEMORY_ENABLED
            and user_text
            and is_personal_memory_query(user_text)
            and looks_like_missing_personal_info_reply(final_text)
        ):
            local_fallback = resolve_local_personal_fallback(
                user_text=user_text,
                memory_scope=memory_scope,
                query_matched_memories=query_matched_memories,
            )
            if local_fallback:
                final_text = local_fallback
                if not hold_personal_stream:
                    yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=local_fallback))
        if hold_personal_stream and final_text:
            yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=final_text))
        if is_vision_request and final_text:
            if is_generic_image_refusal(final_text):
                final_text = build_image_refusal_diagnostic(upstream_model)
            yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=final_text))
        if MEMORY_ENABLED and user_text and collected_tokens:
            memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
            memory_service.maybe_store_from_assistant_turn(text=final_text, memory_scope=memory_scope)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

