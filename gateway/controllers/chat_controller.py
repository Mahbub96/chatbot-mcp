from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from urllib.parse import urlparse
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from agent.llm import complete_llm, stream_llm
from config import (
    BANGLA_MODEL,
    CODE_MODEL,
    MEMORY_ENABLED,
    MODEL as DEFAULT_UPSTREAM_MODEL,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SHADOW_MONITOR_ENABLED,
    VISION_STREAM_TIMEOUT_SECONDS,
    VISION_MODEL,
)
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
    should_reject_personal_answer,
    user_disputes_identity,
)
from gateway.helpers.rate_limiter import InMemoryRateLimiter
from gateway.memory_pipeline import memory_pipeline
from gateway.memory_metrics import memory_metrics
from memory.facade import memory_facade as memory_service
from router.model_router import pick_upstream_model
from router.tool_router import maybe_run_legacy_keyword_tool

logger = logging.getLogger(__name__)

ERR_TOO_MANY_REQUESTS = "Too many requests"
ERR_INVALID_JSON_BODY = "Invalid JSON body"
ERR_BODY_OBJECT_REQUIRED = "Request body must be an object"
TOOL_TEST_FILE_PATH = "test.txt"

rate_limiter = InMemoryRateLimiter(
    window_seconds=max(1, RATE_LIMIT_WINDOW_SECONDS),
    max_requests=max(1, RATE_LIMIT_MAX_REQUESTS),
)
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


def find_unsupported_image_input(messages: list[dict[str, Any]]) -> str | None:
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_obj = part.get("image_url") or {}
            if not isinstance(image_obj, dict):
                continue
            image_url = str(image_obj.get("url") or "").strip()
            if not image_url:
                continue
            lowered = image_url.lower()
            if lowered.startswith("data:image/"):
                return "inline-base64"
            parsed = urlparse(image_url)
            host = (parsed.hostname or "").lower()
            if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.startswith("192.168.") or host.startswith("10.") or host.endswith(".local"):
                return "private-url"
    return None


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
        "i don't have any information about",
        "i don't have any specific information about",
        "you haven't shared",
        "i don't know your",
        "i do not know your",
        "i'm not aware of your",
        "i am not aware of your",
        "i'm not sure about your",
        "i'm assuming",
        "i am assuming",
    )
    return any(marker in lowered for marker in markers)


def infer_retrieval_method(retrieved_items: list[dict[str, Any]]) -> str:
    if not retrieved_items:
        return "structured"
    sources = {str(item.get("source") or "").strip().lower() for item in retrieved_items}
    has_short = bool({"short_trace", "short_trace_context"}.intersection(sources))
    has_long = "long_term_attribute" in sources
    has_vectorish = bool(
        {
            "chat_user",
            "chat_assistant",
            "profile_fact",
            "profile_full",
            "manual",
        }.intersection(sources)
    )
    has_lexical = "lexical" in sources
    if has_short or has_long:
        if has_vectorish or has_lexical:
            return "hybrid"
        return "structured"
    if has_lexical and has_vectorish:
        return "hybrid"
    if has_lexical:
        return "fts"
    if has_vectorish:
        return "vector"
    return "fts"


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
    # 1) Current-scope short-term first (most recent conversational truth)
    pools.append(memory_service.list_short_term_slot_facts(query=user_text, memory_scope=memory_scope, limit=50))
    pools.append(memory_service.list_short_term_context_facts(query=user_text, memory_scope=memory_scope, limit=60))
    # 2) Current-scope long/profile views
    pools.append(memory_service.list_profile_facts(memory_scope=memory_scope, limit=50))
    pools.append(memory_service.list_profile_memories(memory_scope=memory_scope, limit=50))
    # Cross-tab safety net: opt-in via config for production control.
    pools.append(memory_service.list_short_term_slot_facts_any_scope(query=user_text, limit=80))
    pools.append(memory_service.list_short_term_context_facts_any_scope(query=user_text, limit=120))
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


def persist_user_memory_on_failure(*, user_text: str, memory_scope: str) -> None:
    if not MEMORY_ENABLED:
        return
    normalized = (user_text or "").strip()
    if not normalized:
        return
    try:
        memory_service.maybe_store_from_user_turn(text=normalized, memory_scope=memory_scope)
    except Exception:
        # Best-effort resilience path for upstream failures.
        return


async def persist_turn_memory(
    *,
    user_text: str,
    assistant_text: str,
    memory_scope: str,
) -> None:
    if not MEMORY_ENABLED:
        return
    normalized_user = (user_text or "").strip()
    normalized_assistant = (assistant_text or "").strip()
    if not normalized_user and not normalized_assistant:
        return
    # Read-your-write consistency: for personal-memory turns, persist inline
    # so immediate cross-thread requests can retrieve the latest facts.
    if normalized_user and is_personal_memory_query(normalized_user):
        try:
            await asyncio.to_thread(
                memory_service.maybe_store_from_user_turn,
                text=normalized_user,
                memory_scope=memory_scope,
            )
            await asyncio.to_thread(
                memory_service.maybe_store_from_assistant_turn,
                text=normalized_assistant,
                memory_scope=memory_scope,
            )
            return
        except Exception:
            # Fallback to queue path without breaking response.
            pass
    memory_pipeline.enqueue(
        memory_scope=memory_scope,
        user_text=normalized_user,
        assistant_text=normalized_assistant,
    )


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
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
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
    retrieval_trace_items: list[dict[str, Any]] = []

    if user_disputes_identity(user_text):
        dispute_answer = build_identity_dispute_answer()
        if not stream:
            return build_non_stream_response(dispute_answer)
        async def dispute_stream():
            yield ":\n\n"; yield sse_data(build_chunk_payload(chunk_id="identity-dispute", delta_content=dispute_answer)); yield sse_data(build_chunk_payload(chunk_id="identity-dispute", finish_reason="stop")); yield "data: [DONE]\n\n"
        return StreamingResponse(dispute_stream(), media_type="text/event-stream")

    if MEMORY_ENABLED and user_text:
        try:
            memories = await asyncio.to_thread(
                memory_service.retrieve_memory,
                query=user_text,
                memory_scope=memory_scope,
                limit=10,
            )
            retrieval_trace_items = memories[:]
            if SHADOW_MONITOR_ENABLED:
                try:
                    legacy_shadow = await asyncio.to_thread(
                        memory_service.search_legacy_only,
                        query=user_text,
                        memory_scope=memory_scope,
                        limit=10,
                    )
                    memory_metrics.record_shadow_comparison(
                        memory_scope=memory_scope,
                        prod_items=memories,
                        shadow_items=legacy_shadow,
                    )
                except Exception:
                    logger.debug("shadow_monitor_compare_failed", exc_info=True)
            retrieval_method = infer_retrieval_method(retrieval_trace_items)
            await asyncio.to_thread(
                memory_service.log_retrieval_decision,
                trace_id=request_id,
                memory_scope=memory_scope,
                query_text=user_text,
                retrieved_items=retrieval_trace_items,
                method_used=retrieval_method,
            )
            query_matched_memories = matched_memories_for_query(user_text, select_context_memories(user_text, memories))
            if not query_matched_memories and detect_fact_slots(user_text):
                trusted = await asyncio.to_thread(
                    memory_service.list_long_term_slot_facts,
                    query=user_text,
                    memory_scope=memory_scope,
                    limit=20,
                )
                if not trusted:
                    trusted = await asyncio.to_thread(
                        memory_service.list_profile_facts,
                        memory_scope=memory_scope,
                        limit=20,
                    )
                query_matched_memories = matched_memories_for_query(user_text, trusted)
            if not query_matched_memories and is_personal_memory_query(user_text):
                cross_tab_short = (
                    await asyncio.to_thread(
                        memory_service.list_short_term_slot_facts_any_scope,
                        query=user_text,
                        limit=40,
                    )
                    + await asyncio.to_thread(
                        memory_service.list_short_term_context_facts_any_scope,
                        query=user_text,
                        limit=60,
                    )
                )
                if cross_tab_short:
                    query_matched_memories = matched_memories_for_query(
                        user_text,
                        select_context_memories(user_text, cross_tab_short),
                    )
            llm_messages = inject_memory_context(messages, query_matched_memories)
        except Exception as exc:
            await asyncio.to_thread(
                memory_service.log_retrieval_decision,
                trace_id=request_id,
                memory_scope=memory_scope,
                query_text=user_text,
                retrieved_items=[],
                method_used="structured",
            )
            logger.warning("Memory retrieval failed: %s", exc)

    if has_multimodal(llm_messages) and not VISION_MODEL:
        return json_error(400, "Image input detected but VISION_MODEL is not configured. Set VISION_MODEL to a vision-capable NVIDIA NIM model id.")
    unsupported_image_input = find_unsupported_image_input(llm_messages) if has_multimodal(llm_messages) else None
    if unsupported_image_input == "inline-base64":
        return json_error(
            400,
            "Image input uses inline base64 data URL. This vision path requires an http/https public image URL.",
        )
    if unsupported_image_input == "private-url":
        return json_error(
            400,
            "Image input URL is private/local. Please provide a publicly reachable image URL.",
        )

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
        stored_ok = False
        store_bool_result = False
        evidence_profile_full = False
        evidence_profile_memories = False
        evidence_profile_facts = False
        try:
            store_bool_result = bool(
                await asyncio.to_thread(
                    memory_service.maybe_store_from_user_turn,
                    text=user_text,
                    memory_scope=memory_scope,
                )
            )
            stored_ok = store_bool_result
            # Safety net for compatibility paths where write might succeed but bool path is unavailable.
            if not stored_ok:
                evidence_profile_full = bool(
                    await asyncio.to_thread(memory_service.latest_profile_full, memory_scope=memory_scope)
                )
                evidence_profile_memories = bool(
                    await asyncio.to_thread(
                        memory_service.list_profile_memories,
                        memory_scope=memory_scope,
                        limit=1,
                    )
                )
                evidence_profile_facts = bool(
                    await asyncio.to_thread(
                        memory_service.list_profile_facts,
                        memory_scope=memory_scope,
                        limit=1,
                    )
                )
                stored_ok = bool(
                    evidence_profile_full
                    or evidence_profile_memories
                    or evidence_profile_facts
                )
            logger.info(
                "structured_ingest_decision request_id=%s scope=%s text_len=%s store_bool=%s evidence_profile_full=%s evidence_profile_memories=%s evidence_profile_facts=%s final_stored_ok=%s",
                request_id,
                memory_scope,
                len(user_text or ""),
                store_bool_result,
                evidence_profile_full,
                evidence_profile_memories,
                evidence_profile_facts,
                stored_ok,
            )
        except Exception as exc:
            logger.warning("Structured document memory write failed: %s", exc)
            stored_ok = False
        ingest_ack = (
            build_document_ingest_ack()
            if stored_ok
            else "I received your structured text, but memory persistence failed. Please retry and I will save it."
        )
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
        local_memories = memory_service.list_profile_memories(memory_scope=memory_scope, limit=220)
        if len(local_memories) < 8:
            any_scope = memory_service.list_profile_memories_any_scope(limit=320)
            seen: set[str] = set()
            merged: list[dict[str, Any]] = []
            for item in (local_memories + any_scope):
                sig = f"{str(item.get('memory_scope') or '')}|{str(item.get('source') or '')}|{str(item.get('text') or '').strip().lower()}"
                if not sig or sig in seen:
                    continue
                seen.add(sig)
                merged.append(item)
                if len(merged) >= 300:
                    break
            local_memories = merged
        return build_non_stream_response(tool_prefix + build_user_profile_summary(local_memories))
    if MEMORY_ENABLED and user_text and is_exact_shared_request(user_text) and not has_multimodal(llm_messages):
        best = pick_best_shared_memory(memory_service.list_profile_memories_any_scope(limit=400))
        return build_non_stream_response(tool_prefix + (build_exact_shared_response(best) if best else "I couldn't find an exact shared item in local memory."))
    if MEMORY_ENABLED and user_text and is_shared_summary_request(user_text) and not has_multimodal(llm_messages):
        return build_non_stream_response(tool_prefix + build_shared_summary_response(memory_service.list_profile_memories_any_scope(limit=400)))
    if user_text and is_offer_intent_query(user_text) and not has_multimodal(llm_messages):
        return build_non_stream_response(tool_prefix + build_offer_intent_answer())

    if MEMORY_ENABLED and user_text and is_cv_query(user_text) and not has_multimodal(llm_messages):
        if is_exact_cv_request(user_text):
            cv_full = memory_service.latest_profile_full(memory_scope=memory_scope)
            if not cv_full:
                cv_full = memory_service.latest_profile_full_any_scope()
            if cv_full and (cv_full.get("text") or "").strip():
                return build_non_stream_response(tool_prefix + build_exact_cv_response(str(cv_full.get("text") or "")))
        richer = memory_service.list_profile_memories(memory_scope=memory_scope, limit=8)
        if len(richer) < 4:
            richer = memory_service.list_profile_memories_any_scope(limit=16)
        _ = build_cv_context_answer(richer or query_matched_memories)

    if (
        MEMORY_ENABLED
        and user_text
        and is_personal_memory_query(user_text)
        and not query_matched_memories
        and not has_multimodal(llm_messages)
    ):
        missing_answer = build_memory_missing_answer(user_text)
        if missing_answer:
            if not stream:
                return build_non_stream_response(tool_prefix + missing_answer)

            async def missing_memory_stream():
                yield ":\n\n"
                if tool_prefix:
                    yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
                yield sse_data(build_chunk_payload(chunk_id="memory-missing", delta_content=missing_answer))
                yield sse_data(build_chunk_payload(chunk_id="memory-missing", finish_reason="stop"))
                yield "data: [DONE]\n\n"

            return StreamingResponse(missing_memory_stream(), media_type="text/event-stream")

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
            if (
                MEMORY_ENABLED
                and user_text
                and is_personal_memory_query(user_text)
                and should_reject_personal_answer(
                    user_text=user_text,
                    response_text=text,
                    memories=query_matched_memories,
                )
            ):
                memory_metrics.record_wrong_answer_guard_trigger(memory_scope=memory_scope)
                safe_fallback = resolve_local_personal_fallback(
                    user_text=user_text,
                    memory_scope=memory_scope,
                    query_matched_memories=query_matched_memories,
                ) or build_memory_missing_answer(user_text)
                if safe_fallback:
                    text = safe_fallback
            if MEMORY_ENABLED and user_text:
                await persist_turn_memory(
                    user_text=user_text,
                    assistant_text=text,
                    memory_scope=memory_scope,
                )
                memory_service.log_chat_trace(
                    request_id=request_id,
                    memory_scope=memory_scope,
                    user_text=user_text,
                    assistant_text=text,
                    model=upstream_model,
                    retrieved_items=retrieval_trace_items,
                    had_error=False,
                )
            return build_non_stream_response(tool_prefix + text)
        except Exception as exc:
            if should_fallback_bangla_model(upstream_model, str(exc)):
                mark_model_unavailable(BANGLA_MODEL, BANGLA_MODEL_COOLDOWN_SECONDS)
                text = await complete_llm(llm_messages, model=bangla_fallback_model())
                return build_non_stream_response(tool_prefix + text)
            persist_user_memory_on_failure(user_text=user_text, memory_scope=memory_scope)
            fallback_answer = None
            if MEMORY_ENABLED and user_text and is_personal_memory_query(user_text):
                fallback_answer = resolve_local_personal_fallback(
                    user_text=user_text,
                    memory_scope=memory_scope,
                    query_matched_memories=query_matched_memories,
                )
            if not fallback_answer:
                fallback_answer = build_memory_fallback_answer(user_text, query_matched_memories)
            if fallback_answer:
                if MEMORY_ENABLED and user_text:
                    memory_service.log_chat_trace(
                        request_id=request_id,
                        memory_scope=memory_scope,
                        user_text=user_text,
                        assistant_text=fallback_answer,
                        model=upstream_model,
                        retrieved_items=retrieval_trace_items,
                        had_error=True,
                    )
                return build_non_stream_response(tool_prefix + fallback_answer)
            return json_error(502, normalize_chat_error(exc, had_image_input=has_multimodal(llm_messages), model=upstream_model))

    async def generate():
        yield ":\n\n"
        is_vision_request = has_multimodal(llm_messages)
        hold_personal_stream = bool(user_text and is_personal_memory_query(user_text) and not is_vision_request)
        if tool_prefix:
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
        if is_vision_request:
            # Send one visible status line for UX, then keep alive silently.
            yield sse_data(build_chunk_payload(chunk_id="vision-status", delta_content="Processing image..."))
            # Keep stream alive with SSE comments while upstream vision runs.
            # Comments are not rendered as assistant text by clients.
            yield ":\n\n"
            try:
                timeout_s = float(max(8, VISION_STREAM_TIMEOUT_SECONDS))
                heartbeat_s = 5.0
                elapsed_s = 0.0
                task = asyncio.create_task(complete_llm(llm_messages, model=upstream_model))
                while not task.done():
                    wait_s = min(heartbeat_s, max(0.1, timeout_s - elapsed_s))
                    await asyncio.wait({task}, timeout=wait_s)
                    if task.done():
                        break
                    elapsed_s += wait_s
                    if elapsed_s >= timeout_s:
                        task.cancel()
                        yield sse_data(
                            build_chunk_payload(
                                chunk_id="error",
                                delta_content="[ERROR] Image analysis is taking too long. Please retry with a smaller/public image URL.",
                                finish_reason="stop",
                            )
                        )
                        yield "data: [DONE]\n\n"
                        return
                    yield ":\n\n"
                vision_text = await task
                if is_generic_image_refusal(vision_text):
                    vision_text = build_image_refusal_diagnostic(upstream_model)
                if vision_text:
                    yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=vision_text))
                if MEMORY_ENABLED and user_text and vision_text:
                    await persist_turn_memory(
                        user_text=user_text,
                        assistant_text=vision_text,
                        memory_scope=memory_scope,
                    )
                    memory_service.log_chat_trace(
                        request_id=request_id,
                        memory_scope=memory_scope,
                        user_text=user_text,
                        assistant_text=vision_text,
                        model=upstream_model,
                        retrieved_items=retrieval_trace_items,
                        had_error=False,
                    )
                yield "data: [DONE]\n\n"
                return
            except Exception as exc:
                msg = normalize_chat_error(exc, had_image_input=True, model=upstream_model)
                yield sse_data(build_chunk_payload(chunk_id="error", delta_content=f"[ERROR] {msg}", finish_reason="stop"))
                yield "data: [DONE]\n\n"
                return
        collected_tokens: list[str] = []
        try:
            async for token in stream_llm(llm_messages, model=upstream_model):
                if token:
                    if is_upstream_error_token(token):
                        persist_user_memory_on_failure(user_text=user_text, memory_scope=memory_scope)
                        fallback_answer = None
                        if MEMORY_ENABLED and user_text and is_personal_memory_query(user_text):
                            fallback_answer = resolve_local_personal_fallback(
                                user_text=user_text,
                                memory_scope=memory_scope,
                                query_matched_memories=query_matched_memories,
                            )
                        if not fallback_answer:
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
            persist_user_memory_on_failure(user_text=user_text, memory_scope=memory_scope)
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
        if (
            MEMORY_ENABLED
            and user_text
            and is_personal_memory_query(user_text)
            and should_reject_personal_answer(
                user_text=user_text,
                response_text=final_text,
                memories=query_matched_memories,
            )
        ):
            memory_metrics.record_wrong_answer_guard_trigger(memory_scope=memory_scope)
            safe_fallback = resolve_local_personal_fallback(
                user_text=user_text,
                memory_scope=memory_scope,
                query_matched_memories=query_matched_memories,
            ) or build_memory_missing_answer(user_text)
            if safe_fallback:
                final_text = safe_fallback
                if not hold_personal_stream:
                    yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=safe_fallback))
        if hold_personal_stream and final_text:
            yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=final_text))
        if is_vision_request and final_text:
            if is_generic_image_refusal(final_text):
                final_text = build_image_refusal_diagnostic(upstream_model)
            yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=final_text))
        if MEMORY_ENABLED and user_text and collected_tokens:
            await persist_turn_memory(
                user_text=user_text,
                assistant_text=final_text,
                memory_scope=memory_scope,
            )
            memory_service.log_chat_trace(
                request_id=request_id,
                memory_scope=memory_scope,
                user_text=user_text,
                assistant_text=final_text,
                model=upstream_model,
                retrieved_items=retrieval_trace_items,
                had_error=False,
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

