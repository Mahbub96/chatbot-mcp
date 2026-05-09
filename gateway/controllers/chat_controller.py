from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from agent.llm import complete_llm, stream_llm
from config import (
    BANGLA_MODEL,
    CODE_MODEL,
    MEMORY_ENABLED,
    MEMORY_SEMANTIC_CONTEXT_FALLBACK_ENABLED,
    MEMORY_SEMANTIC_CONTEXT_FALLBACK_MAX_CHARS,
    MEMORY_SEMANTIC_CONTEXT_FALLBACK_MIN_SCORE,
    MEMORY_SEMANTIC_CONTEXT_FALLBACK_MIN_TOKEN_OVERLAP,
    MAX_VISION_IMAGE_BYTES,
    MAX_VISION_VIDEO_BYTES,
    MODEL as DEFAULT_UPSTREAM_MODEL,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SHADOW_MONITOR_ENABLED,
    SHADOW_MONITOR_SAMPLE_RATE,
    TEXT_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS,
    TEXT_STREAM_STATUS_INTERVAL_SECONDS,
    TEXT_STREAM_TIMEOUT_FALLBACK_MODEL,
    VISION_PER_MODEL_TIMEOUT_SECONDS,
    VISION_STREAM_TIMEOUT_SECONDS,
    VISION_FALLBACK_MODELS,
    VISION_SPEED_FIRST,
    VISION_MODEL,
    VISION_VIDEO_FRAME_INTERVAL_SECONDS,
    VISION_VIDEO_MAX_FRAMES,
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
    blocks_semantic_memory_context_fallback,
    is_offer_intent_query,
    is_personal_memory_query,
    is_shared_summary_request,
    is_user_profile_summary_query,
    looks_like_structured_document_text,
    matched_memories_for_query,
    memories_for_semantic_context_fallback,
    pick_best_shared_memory,
    select_context_memories,
    should_reject_personal_answer,
    user_disputes_identity,
)
from gateway.helpers.rate_limiter import InMemoryRateLimiter
from gateway.memory_pipeline import memory_pipeline
from gateway.memory_metrics import memory_metrics
from gateway.services.multimodal_materializer import (
    contains_image_url_part,
    contains_video_url_part,
    materialize_multimodal_parts,
    promote_text_video_links,
)
from memory.facade import memory_facade as memory_service
from router.model_router import pick_upstream_model
from router.tool_router import maybe_run_legacy_keyword_tool

logger = logging.getLogger(__name__)
step_logger = logging.getLogger("gateway.steps")


def _runtime_revision() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, timeout=2)
        return (out or "").strip() or "unknown"
    except Exception:
        return "unknown"


RUNTIME_SIGNATURE = (
    f"revision={_runtime_revision()}|semantic_fallback={MEMORY_SEMANTIC_CONTEXT_FALLBACK_ENABLED}|"
    f"controller={Path(__file__).resolve()}"
)


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
        "i'm not going to engage in this subject matter",
        "i am not going to engage in this subject matter",
        "i can't engage in this subject",
        "i cannot engage in this subject",
        "i can’t engage in this subject",
        "i can't assist with that",
        "i cannot assist with that",
        "i can’t assist with that",
        "i'm unable to help with that",
        "i am unable to help with that",
        "i can’t help with that",
        "i can't help with that",
    )
    return any(marker in lowered for marker in markers)


def build_image_refusal_diagnostic(model: str) -> str:
    return (
        "I couldn't analyze the image with the current vision path. "
        f"Selected model: {model}. "
        "Please retry and include a short text prompt about what you want explained."
    )


def _ensure_vision_instruction(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Ensure multimodal requests always include an explicit visual-description task.
    This prevents weak/no-text prompts from triggering generic refusals.
    """
    normalized: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            normalized.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            normalized.append(msg)
            continue
        has_image = False
        has_video = False
        has_text = False
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "image_url":
                has_image = True
            elif part_type == "video_url":
                has_video = True
            elif part_type == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    has_text = True
        if (has_image or has_video) and not has_text:
            auto_instruction = (
                "Describe this visual content professionally and precisely. "
                "List key objects, setting, actions, visible text, colors/style, and notable details. "
                "If uncertain, clearly label uncertainty."
            )
            normalized.append(
                {
                    **msg,
                    "content": [
                        {
                            "type": "text",
                            "text": auto_instruction,
                            "meta": {"gateway_auto_instruction": True},
                        },
                        *content,
                    ],
                }
            )
            continue
        normalized.append(msg)
    return normalized


def _with_refusal_retry_instruction(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Add a strict follow-up instruction used only when the first vision attempt refused.
    """
    retry_instruction = (
        "You are performing neutral visual analysis only. "
        "Do not discuss policy or refusal language. "
        "Describe only what is visible in the provided image/video frames."
    )
    return [
        *messages,
        {"role": "system", "content": retry_instruction},
    ]


def find_unsupported_image_input(_messages: list[dict[str, Any]]) -> str | None:
    # Accept all image URL styles:
    # - data:image/... base64
    # - file://...
    # - localhost/private LAN URLs
    # Upstream/model may still reject unsupported forms, but gateway won't pre-block them.
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


def is_openwebui_followup_task_prompt(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return (
        "### task:" in lowered
        and "<chat_history>" in lowered
        and "follow_ups" in lowered
        and "json format" in lowered
    )


def build_openwebui_followup_task_response() -> str:
    # Keep strict JSON shape expected by OpenWebUI task parser.
    return json.dumps(
        {
            "follow_ups": [
                "Can you describe the key objects in this image?",
                "What details should I pay attention to in this image?",
                "Can you summarize this image in one sentence?",
            ]
        },
        ensure_ascii=True,
    )


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


def should_run_shadow_compare(request_id: str) -> bool:
    if not SHADOW_MONITOR_ENABLED:
        return False
    if SHADOW_MONITOR_SAMPLE_RATE >= 1.0:
        return True
    if SHADOW_MONITOR_SAMPLE_RATE <= 0.0:
        return False
    try:
        bucket = uuid.UUID(str(request_id)).int % 10000
    except Exception:
        bucket = int(time.time() * 1000) % 10000
    return bucket < int(SHADOW_MONITOR_SAMPLE_RATE * 10000)


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


def fallback_context_memories_when_unmatched(
    *,
    user_text: str,
    retrieved_items: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if not user_text or not retrieved_items:
        return []
    if not is_personal_memory_query(user_text):
        return []
    prioritized: list[dict[str, Any]] = []
    for item in retrieved_items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip().lower()
        if source in {"short_trace", "short_trace_context", "long_term_attribute", "profile_fact", "profile_full"}:
            prioritized.append(item)
    if not prioritized:
        prioritized = [item for item in retrieved_items if isinstance(item, dict)]
    return prioritized[: max(1, limit)]


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
    on_step: Any | None = None,
) -> None:
    def _emit(step_name: str) -> None:
        if callable(on_step):
            try:
                on_step(step_name)
            except Exception:
                return

    if not MEMORY_ENABLED:
        return
    normalized_user = (user_text or "").strip()
    normalized_assistant = (assistant_text or "").strip()
    if not normalized_user and not normalized_assistant:
        return
    _emit("short_memory.persist_turn.start")
    # Read-your-write consistency: for personal-memory turns, persist inline
    # so immediate cross-thread requests can retrieve the latest facts.
    if normalized_user and is_personal_memory_query(normalized_user):
        try:
            _emit("short_memory.persist_turn.inline.user")
            await asyncio.to_thread(
                memory_service.maybe_store_from_user_turn,
                text=normalized_user,
                memory_scope=memory_scope,
            )
            _emit("short_memory.persist_turn.inline.assistant")
            await asyncio.to_thread(
                memory_service.maybe_store_from_assistant_turn,
                text=normalized_assistant,
                memory_scope=memory_scope,
            )
            _emit("short_memory.persist_turn.inline.done")
            return
        except Exception:
            # Fallback to queue path without breaking response.
            _emit("short_memory.persist_turn.inline.failed_queue_fallback")
    _emit("short_memory.persist_turn.queue_enqueue")
    memory_pipeline.enqueue(
        memory_scope=memory_scope,
        user_text=normalized_user,
        assistant_text=normalized_assistant,
    )


def normalize_chat_error(exc: Exception, *, had_image_input: bool, model: str) -> str:
    msg = str(exc)
    if had_image_input and "vision_all_models_failed" in msg:
        return (
            "Vision request failed across all configured models. "
            f"Primary model: {model}. "
            f"Details: {msg}"
        )
    if had_image_input and "[LLM_ERROR 500]" in msg:
        return (
            "Vision request failed on upstream model. "
            f"Configured model: {model}. "
            "Verify that this model supports your provided image input format "
            "(base64, file URL, localhost/private URL, or public URL) in your NVIDIA account."
        )
    return msg


def _vision_model_candidates(primary_model: str) -> list[str]:
    candidates: list[str] = []
    ordered = (
        [*list(VISION_FALLBACK_MODELS), primary_model]
        if VISION_SPEED_FIRST and VISION_FALLBACK_MODELS
        else [primary_model, *list(VISION_FALLBACK_MODELS)]
    )
    for model in ordered:
        normalized = str(model or "").strip()
        if not normalized or normalized in candidates:
            continue
        candidates.append(normalized)
    return candidates or [primary_model]


async def _complete_vision_with_fallback(
    *,
    messages: list[dict[str, Any]],
    primary_model: str,
    on_step: Any | None = None,
) -> tuple[str, str]:
    def _emit(step_name: str) -> None:
        if callable(on_step):
            try:
                on_step(step_name)
            except Exception:
                return

    errors: list[str] = []
    for model in _vision_model_candidates(primary_model):
        try:
            _emit(f"vision_model_attempt.start[{model}]")
            output = await asyncio.wait_for(
                complete_llm(messages, model=model),
                timeout=float(max(5, VISION_PER_MODEL_TIMEOUT_SECONDS)),
            )
            if not output:
                _emit(f"vision_model_attempt.empty_output[{model}]")
                errors.append(f"{model}: empty_output")
                continue
            if is_generic_image_refusal(output):
                _emit(f"vision_model_attempt.generic_refusal[{model}]")
                retry_messages = _with_refusal_retry_instruction(messages)
                _emit(f"vision_model_attempt.retry.start[{model}]")
                retry_output = await asyncio.wait_for(
                    complete_llm(retry_messages, model=model),
                    timeout=float(max(5, VISION_PER_MODEL_TIMEOUT_SECONDS)),
                )
                if retry_output and not is_generic_image_refusal(retry_output):
                    _emit(f"vision_model_attempt.retry.success[{model}]")
                    return retry_output, model
                _emit(f"vision_model_attempt.retry.failed[{model}]")
                errors.append(f"{model}: generic_refusal")
                continue
            _emit(f"vision_model_attempt.success[{model}]")
            return output, model
        except asyncio.TimeoutError:
            _emit(f"vision_model_attempt.timeout[{model}]")
            errors.append(f"{model}: per_model_timeout")
            continue
        except Exception as exc:
            _emit(f"vision_model_attempt.error[{model}]")
            errors.append(f"{model}: {str(exc)}")
            continue
    raise RuntimeError("vision_all_models_failed | " + " || ".join(errors))


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
    request_started_at = time.perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    step_counter = 0
    previous_elapsed_ms = 0

    def log_step(function_name: str) -> None:
        nonlocal step_counter, previous_elapsed_ms
        step_counter += 1
        elapsed_ms = int((time.perf_counter() - request_started_at) * 1000)
        delta_ms = elapsed_ms - previous_elapsed_ms
        previous_elapsed_ms = elapsed_ms
        message = f"req={request_id} step {step_counter} : {function_name} | +{elapsed_ms}ms | delta={delta_ms}ms"
        logger.info(message)
        if step_logger.handlers:
            step_logger.info(message)

    log_step("handle_chat_completions.start")
    log_step(f"runtime.signature[{RUNTIME_SIGNATURE}]")
    client_ip = request.client.host if request.client else "unknown"
    log_step("rate_limiter.is_limited")
    if rate_limiter.is_limited(client_ip):
        log_step("json_error.too_many_requests")
        return json_error(429, ERR_TOO_MANY_REQUESTS)
    try:
        log_step("request.json")
        body = await request.json()
    except Exception:
        log_step("json_error.invalid_json_body")
        return json_error(400, ERR_INVALID_JSON_BODY)
    if not isinstance(body, dict):
        log_step("json_error.body_object_required")
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    log_step("parse_completion_request")
    messages, stream = parse_completion_request(body)
    log_step("promote_text_video_links")
    messages = promote_text_video_links(messages)
    if not messages:
        log_step("json_error.messages_empty")
        return json_error(400, "messages must be a non-empty array")
    if has_multimodal(messages):
        log_step("materialize_multimodal_parts")
        messages = await materialize_multimodal_parts(
            messages,
            max_image_bytes=MAX_VISION_IMAGE_BYTES,
            max_video_bytes=MAX_VISION_VIDEO_BYTES,
            max_video_frames=VISION_VIDEO_MAX_FRAMES,
            video_frame_interval_seconds=VISION_VIDEO_FRAME_INTERVAL_SECONDS,
        )
        log_step("_ensure_vision_instruction")
        messages = _ensure_vision_instruction(messages)
        if contains_video_url_part(messages) and not contains_image_url_part(messages):
            log_step("json_error.video_decode_failed")
            return json_error(
                400,
                "Video detected but could not decode frames. Share a direct downloadable video URL or upload a smaller video.",
            )
    log_step("resolve_memory_scope")
    memory_scope = resolve_memory_scope(request, body)
    llm_messages = messages
    log_step("latest_user_text")
    user_text = latest_user_text(messages)
    query_matched_memories: list[dict[str, Any]] = []
    retrieval_trace_items: list[dict[str, Any]] = []

    if is_openwebui_followup_task_prompt(user_text):
        log_step("build_openwebui_followup_task_response")
        followup_json = build_openwebui_followup_task_response()
        if not stream:
            log_step("build_non_stream_response.followups")
            return build_non_stream_response(followup_json)

        async def followup_stream():
            yield ":\n\n"
            yield sse_data(build_chunk_payload(chunk_id="followups", delta_content=followup_json))
            yield sse_data(build_chunk_payload(chunk_id="followups", finish_reason="stop"))
            yield "data: [DONE]\n\n"

        return StreamingResponse(followup_stream(), media_type="text/event-stream")

    if user_disputes_identity(user_text):
        log_step("build_identity_dispute_answer")
        dispute_answer = build_identity_dispute_answer()
        if not stream:
            log_step("build_non_stream_response.identity_dispute")
            return build_non_stream_response(dispute_answer)
        async def dispute_stream():
            yield ":\n\n"; yield sse_data(build_chunk_payload(chunk_id="identity-dispute", delta_content=dispute_answer)); yield sse_data(build_chunk_payload(chunk_id="identity-dispute", finish_reason="stop")); yield "data: [DONE]\n\n"
        return StreamingResponse(dispute_stream(), media_type="text/event-stream")

    if MEMORY_ENABLED and user_text and not has_multimodal(llm_messages):
        try:
            log_step("memory_service.retrieve_memory")
            memories = await asyncio.to_thread(
                memory_service.retrieve_memory,
                query=user_text,
                memory_scope=memory_scope,
                limit=10,
            )
            log_step(f"short_memory.retrieve.done[{len(memories)}]")
            retrieval_trace_items = memories[:]
            if should_run_shadow_compare(request_id):
                try:
                    log_step("short_memory.retrieve.shadow_compare.start")
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
                    log_step("short_memory.retrieve.shadow_compare.done")
                except Exception:
                    logger.debug("shadow_monitor_compare_failed", exc_info=True)
            retrieval_method = infer_retrieval_method(retrieval_trace_items)
            log_step(f"short_memory.retrieval_method[{retrieval_method}]")
            await asyncio.to_thread(
                memory_service.log_retrieval_decision,
                trace_id=request_id,
                memory_scope=memory_scope,
                query_text=user_text,
                retrieved_items=retrieval_trace_items,
                method_used=retrieval_method,
            )
            log_step("short_memory.log_retrieval_decision.done")
            query_matched_memories = matched_memories_for_query(user_text, select_context_memories(user_text, memories))
            log_step(f"short_memory.query_match.done[{len(query_matched_memories)}]")
            if not query_matched_memories:
                log_step(
                    f"short_memory.zero_match_snapshot[n_memories={len(memories)}|n_trace={len(retrieval_trace_items)}]"
                )
            retrieval_pool = memories if memories else retrieval_trace_items
            if memories and len(retrieval_trace_items) != len(memories):
                log_step(
                    f"short_memory.trace_pool_mismatch[memories={len(memories)}|trace={len(retrieval_trace_items)}]"
                )
            if not query_matched_memories and retrieval_pool:
                log_step(f"short_memory.unmatched_use_retrieval_pool[{len(retrieval_pool)}]")
                fallback_matches = fallback_context_memories_when_unmatched(
                    user_text=user_text,
                    retrieved_items=retrieval_pool,
                    limit=3,
                )
                if fallback_matches:
                    query_matched_memories = fallback_matches
                    log_step(f"short_memory.query_match.fallback_topk[{len(query_matched_memories)}]")
                if not query_matched_memories:
                    if not MEMORY_SEMANTIC_CONTEXT_FALLBACK_ENABLED:
                        log_step("short_memory.query_match.semantic_fallback.skipped[disabled]")
                    elif blocks_semantic_memory_context_fallback(user_text):
                        log_step("short_memory.query_match.semantic_fallback.skipped[blocked_profile_intent]")
                    else:
                        semantic_matches = memories_for_semantic_context_fallback(
                            user_text,
                            retrieval_pool,
                            limit=3,
                            min_score=MEMORY_SEMANTIC_CONTEXT_FALLBACK_MIN_SCORE,
                            min_overlap=MEMORY_SEMANTIC_CONTEXT_FALLBACK_MIN_TOKEN_OVERLAP,
                            max_chars=MEMORY_SEMANTIC_CONTEXT_FALLBACK_MAX_CHARS,
                        )
                        if semantic_matches:
                            query_matched_memories = semantic_matches
                            log_step(f"short_memory.query_match.semantic_fallback[{len(query_matched_memories)}]")
                        else:
                            log_step(
                                f"short_memory.query_match.semantic_fallback.skipped[no_eligible_items|pool={len(retrieval_pool)}]"
                            )
            if not query_matched_memories and detect_fact_slots(user_text):
                log_step("short_memory.long_term_slot_lookup.start")
                trusted = await asyncio.to_thread(
                    memory_service.list_long_term_slot_facts,
                    query=user_text,
                    memory_scope=memory_scope,
                    limit=20,
                )
                if not trusted:
                    log_step("short_memory.profile_facts_lookup.start")
                    trusted = await asyncio.to_thread(
                        memory_service.list_profile_facts,
                        memory_scope=memory_scope,
                        limit=20,
                    )
                query_matched_memories = matched_memories_for_query(user_text, trusted)
                log_step(f"short_memory.long_term_slot_lookup.done[{len(query_matched_memories)}]")
            if not query_matched_memories and is_personal_memory_query(user_text):
                log_step("short_memory.cross_scope_short_lookup.start")
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
                log_step(f"short_memory.cross_scope_short_lookup.done[{len(query_matched_memories)}]")
            llm_messages = inject_memory_context(messages, query_matched_memories)
            log_step(f"short_memory.inject_context.done[{len(query_matched_memories)}]")
        except Exception as exc:
            await asyncio.to_thread(
                memory_service.log_retrieval_decision,
                trace_id=request_id,
                memory_scope=memory_scope,
                query_text=user_text,
                retrieved_items=[],
                method_used="structured",
            )
            log_step("short_memory.retrieve.failed")
            logger.warning("Memory retrieval failed: %s", exc)

    if has_multimodal(llm_messages) and not VISION_MODEL:
        log_step("json_error.vision_model_not_configured")
        return json_error(400, "Image input detected but VISION_MODEL is not configured. Set VISION_MODEL to a vision-capable NVIDIA NIM model id.")
    _ = find_unsupported_image_input(llm_messages) if has_multimodal(llm_messages) else None

    log_step("pick_upstream_model")
    selected_model = pick_upstream_model(llm_messages, default_model=DEFAULT_UPSTREAM_MODEL, bangla_model=BANGLA_MODEL, code_model=CODE_MODEL or None, vision_model=VISION_MODEL or None)
    log_step("choose_runtime_model")
    upstream_model = choose_runtime_model(selected_model)
    log_step("maybe_run_legacy_keyword_tool")
    tool_output = maybe_run_legacy_keyword_tool(
        llm_messages,
        tool_runner=lambda n, a: execute_tool_with_policy(n, a, approval_id=None),
        test_file_path=TOOL_TEST_FILE_PATH,
    )
    tool_prefix = f"\n[TOOL RESULT]\n{json.dumps(tool_output)}\n" if tool_output is not None else ""
    if tool_output is not None and tool_output.get("requires_approval") is True:
        if not stream:
            log_step("build_non_stream_response.tool_approval")
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
            log_step("build_non_stream_response.doc_ingest")
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
        log_step("build_non_stream_response.user_profile_summary")
        return build_non_stream_response(tool_prefix + build_user_profile_summary(local_memories))
    if MEMORY_ENABLED and user_text and is_exact_shared_request(user_text) and not has_multimodal(llm_messages):
        best = pick_best_shared_memory(memory_service.list_profile_memories_any_scope(limit=400))
        log_step("build_non_stream_response.exact_shared")
        return build_non_stream_response(tool_prefix + (build_exact_shared_response(best) if best else "I couldn't find an exact shared item in local memory."))
    if MEMORY_ENABLED and user_text and is_shared_summary_request(user_text) and not has_multimodal(llm_messages):
        log_step("build_non_stream_response.shared_summary")
        return build_non_stream_response(tool_prefix + build_shared_summary_response(memory_service.list_profile_memories_any_scope(limit=400)))
    if user_text and is_offer_intent_query(user_text) and not has_multimodal(llm_messages):
        log_step("build_non_stream_response.offer_intent")
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
                log_step("build_non_stream_response.memory_missing")
                return build_non_stream_response(tool_prefix + missing_answer)

            async def missing_memory_stream():
                yield ":\n\n"
                if tool_prefix:
                    yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
                yield sse_data(build_chunk_payload(chunk_id="memory-missing", delta_content=missing_answer))
                yield sse_data(build_chunk_payload(chunk_id="memory-missing", finish_reason="stop"))
                yield "data: [DONE]\n\n"

            return StreamingResponse(missing_memory_stream(), media_type="text/event-stream")

    if (
        MEMORY_ENABLED
        and user_text
        and is_personal_memory_query(user_text)
        and query_matched_memories
        and not has_multimodal(llm_messages)
    ):
        memory_fast_answer = build_memory_fallback_answer(user_text, query_matched_memories)
        if not memory_fast_answer:
            memory_fast_answer = resolve_local_personal_fallback(
                user_text=user_text,
                memory_scope=memory_scope,
                query_matched_memories=query_matched_memories,
            )
        if memory_fast_answer:
            if MEMORY_ENABLED and user_text:
                memory_service.log_chat_trace(
                    request_id=request_id,
                    memory_scope=memory_scope,
                    user_text=user_text,
                    assistant_text=memory_fast_answer,
                    model="memory-fastpath",
                    retrieved_items=retrieval_trace_items,
                    had_error=False,
                )
            if not stream:
                log_step("build_non_stream_response.memory_fastpath")
                return build_non_stream_response(tool_prefix + memory_fast_answer)

            async def memory_fast_stream():
                yield ":\n\n"
                if tool_prefix:
                    yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
                yield sse_data(build_chunk_payload(chunk_id="memory-fastpath", delta_content=memory_fast_answer))
                yield sse_data(build_chunk_payload(chunk_id="memory-fastpath", finish_reason="stop"))
                log_step("stream_response.done.memory_fastpath")
                yield "data: [DONE]\n\n"

            return StreamingResponse(memory_fast_stream(), media_type="text/event-stream")

    if not stream:
        try:
            if has_multimodal(llm_messages):
                log_step("_complete_vision_with_fallback.non_stream")
                vision_started_at = time.perf_counter()
                text, upstream_model = await _complete_vision_with_fallback(
                    messages=llm_messages,
                    primary_model=upstream_model,
                )
                logger.info(
                    "vision_call.non_stream.duration_ms=%s model=%s",
                    int((time.perf_counter() - vision_started_at) * 1000),
                    upstream_model,
                )
            else:
                log_step("complete_llm.non_stream")
                text = await complete_llm(llm_messages, model=upstream_model)
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
                log_step("persist_turn_memory.non_stream")
                await persist_turn_memory(
                    user_text=user_text,
                    assistant_text=text,
                    memory_scope=memory_scope,
                    on_step=log_step,
                )
                log_step("memory_service.log_chat_trace.non_stream")
                memory_service.log_chat_trace(
                    request_id=request_id,
                    memory_scope=memory_scope,
                    user_text=user_text,
                    assistant_text=text,
                    model=upstream_model,
                    retrieved_items=retrieval_trace_items,
                    had_error=False,
                )
            log_step("build_non_stream_response.final")
            return build_non_stream_response(tool_prefix + text)
        except Exception as exc:
            if has_multimodal(llm_messages) and "vision_all_models_failed" in str(exc):
                diagnostic = build_image_refusal_diagnostic(upstream_model)
                log_step("build_non_stream_response.vision_diagnostic")
                return build_non_stream_response(tool_prefix + diagnostic)
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
                log_step("build_non_stream_response.fallback_answer")
                return build_non_stream_response(tool_prefix + fallback_answer)
            log_step("json_error.upstream_failure")
            return json_error(502, normalize_chat_error(exc, had_image_input=has_multimodal(llm_messages), model=upstream_model))

    async def generate():
        yield ":\n\n"
        is_vision_request = has_multimodal(llm_messages)
        hold_personal_stream = bool(user_text and is_personal_memory_query(user_text) and not is_vision_request)
        if tool_prefix:
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
        if is_vision_request:
            active_vision_model = upstream_model
            try:
                yield f"event: status\ndata: {json.dumps({'message': 'Processing image...'})}\n\n"
                timeout_s = float(max(8, VISION_STREAM_TIMEOUT_SECONDS))
                log_step("_complete_vision_with_fallback.stream")
                vision_started_at = time.perf_counter()
                vision_task = asyncio.create_task(
                    _complete_vision_with_fallback(
                        messages=llm_messages,
                        primary_model=active_vision_model,
                        on_step=log_step,
                    )
                )
                heartbeat_interval_s = 3.0
                next_heartbeat_at_s = heartbeat_interval_s
                while True:
                    elapsed_s = time.perf_counter() - vision_started_at
                    remaining_s = timeout_s - elapsed_s
                    if remaining_s <= 0:
                        vision_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await vision_task
                        raise asyncio.TimeoutError()
                    wait_slice_s = min(heartbeat_interval_s, remaining_s)
                    try:
                        vision_text, used_vision_model = await asyncio.wait_for(
                            asyncio.shield(vision_task),
                            timeout=wait_slice_s,
                        )
                        break
                    except asyncio.TimeoutError:
                        elapsed_whole_s = int(time.perf_counter() - vision_started_at)
                        if elapsed_whole_s >= int(next_heartbeat_at_s):
                            yield f"event: status\ndata: {json.dumps({'message': f'Still processing image... ({elapsed_whole_s}s)'})}\n\n"
                            log_step("vision_status_heartbeat_sent")
                            next_heartbeat_at_s += heartbeat_interval_s
                        continue
                logger.info(
                    "vision_call.stream.duration_ms=%s model=%s",
                    int((time.perf_counter() - vision_started_at) * 1000),
                    used_vision_model,
                )
                active_vision_model = used_vision_model
                if vision_text:
                    yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=vision_text))
                if MEMORY_ENABLED and user_text and vision_text:
                    log_step("persist_turn_memory.stream_vision")
                    await persist_turn_memory(
                        user_text=user_text,
                        assistant_text=vision_text,
                        memory_scope=memory_scope,
                        on_step=log_step,
                    )
                    log_step("memory_service.log_chat_trace.stream_vision")
                    memory_service.log_chat_trace(
                        request_id=request_id,
                        memory_scope=memory_scope,
                        user_text=user_text,
                        assistant_text=vision_text,
                        model=active_vision_model,
                        retrieved_items=retrieval_trace_items,
                        had_error=False,
                    )
                log_step("stream_response.done.vision_success")
                yield "data: [DONE]\n\n"
                return
            except asyncio.TimeoutError:
                yield sse_data(
                    build_chunk_payload(
                        chunk_id="error",
                        delta_content="[ERROR] Image analysis timed out. Please retry.",
                        finish_reason="stop",
                    )
                )
                log_step("stream_response.done.vision_timeout")
                yield "data: [DONE]\n\n"
                return
            except Exception as exc:
                if "vision_all_models_failed" in str(exc):
                    diagnostic = build_image_refusal_diagnostic(active_vision_model)
                    yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=diagnostic))
                    log_step("stream_response.done.vision_all_models_failed")
                    yield "data: [DONE]\n\n"
                    return
                msg = normalize_chat_error(exc, had_image_input=True, model=active_vision_model)
                yield sse_data(build_chunk_payload(chunk_id="error", delta_content=f"[ERROR] {msg}", finish_reason="stop"))
                log_step("stream_response.done.vision_error")
                yield "data: [DONE]\n\n"
                return
        collected_tokens: list[str] = []
        token_count = 0
        first_token_seen = False
        try:
            log_step("stream_llm.stream")
            stream_iter = stream_llm(llm_messages, model=upstream_model).__aiter__()
            pending_next: asyncio.Task[str] | None = None
            next_text_status_at_s = float(TEXT_STREAM_STATUS_INTERVAL_SECONDS)
            text_stream_started_at = time.perf_counter()
            first_token_timeout_s = float(TEXT_STREAM_FIRST_TOKEN_TIMEOUT_SECONDS)
            while True:
                if pending_next is None:
                    pending_next = asyncio.create_task(stream_iter.__anext__())
                try:
                    token = await asyncio.wait_for(
                        asyncio.shield(pending_next),
                        timeout=float(TEXT_STREAM_STATUS_INTERVAL_SECONDS),
                    )
                    pending_next = None
                except asyncio.TimeoutError:
                    if not first_token_seen:
                        elapsed_s = int(time.perf_counter() - text_stream_started_at)
                        if elapsed_s >= int(first_token_timeout_s):
                            if pending_next:
                                pending_next.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await pending_next
                                pending_next = None
                            fallback_answer = None
                            if MEMORY_ENABLED and user_text and is_personal_memory_query(user_text):
                                fallback_answer = resolve_local_personal_fallback(
                                    user_text=user_text,
                                    memory_scope=memory_scope,
                                    query_matched_memories=query_matched_memories,
                                )
                            if (
                                not fallback_answer
                                and TEXT_STREAM_TIMEOUT_FALLBACK_MODEL
                                and TEXT_STREAM_TIMEOUT_FALLBACK_MODEL != upstream_model
                            ):
                                try:
                                    log_step("stream_llm.first_token_timeout.fallback_model.start")
                                    fallback_answer = await asyncio.wait_for(
                                        complete_llm(
                                            llm_messages,
                                            model=TEXT_STREAM_TIMEOUT_FALLBACK_MODEL,
                                        ),
                                        timeout=20.0,
                                    )
                                    if fallback_answer:
                                        log_step("stream_llm.first_token_timeout.fallback_model.success")
                                except Exception:
                                    log_step("stream_llm.first_token_timeout.fallback_model.failed")
                            if fallback_answer:
                                yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=fallback_answer))
                            else:
                                yield sse_data(
                                    build_chunk_payload(
                                        chunk_id="error",
                                        delta_content=(
                                            f"[ERROR] Upstream first token timed out after {int(first_token_timeout_s)}s. "
                                            "Please retry or use a faster model."
                                        ),
                                        finish_reason="stop",
                                    )
                                )
                            log_step("stream_response.done.first_token_timeout")
                            yield "data: [DONE]\n\n"
                            return
                        if elapsed_s >= int(next_text_status_at_s):
                            yield f"event: status\ndata: {json.dumps({'message': f'Still generating response... ({elapsed_s}s)'})}\n\n"
                            log_step("text_stream.waiting_first_token_status_sent")
                            next_text_status_at_s += float(TEXT_STREAM_STATUS_INTERVAL_SECONDS)
                    continue
                except StopAsyncIteration:
                    break
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
                        log_step("stream_response.done.upstream_error_token")
                        yield "data: [DONE]\n\n"
                        return
                    token_count += 1
                    if not first_token_seen:
                        log_step("stream_llm.first_token")
                        first_token_seen = True
                    elif token_count % 100 == 0:
                        log_step(f"stream_llm.token_progress[{token_count}]")
                    collected_tokens.append(token)
                    if not is_vision_request and not hold_personal_stream:
                        yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=token))
            log_step(f"stream_llm.done[{token_count}]")
        except Exception as exc:
            persist_user_memory_on_failure(user_text=user_text, memory_scope=memory_scope)
            fallback_answer = build_memory_fallback_answer(user_text, query_matched_memories)
            if fallback_answer and not collected_tokens:
                yield sse_data(build_chunk_payload(chunk_id="memory-fallback", delta_content=fallback_answer))
                yield sse_data(build_chunk_payload(chunk_id="memory-fallback", finish_reason="stop"))
                log_step("stream_response.done.memory_fallback")
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
            log_step("persist_turn_memory.stream")
            await persist_turn_memory(
                user_text=user_text,
                assistant_text=final_text,
                memory_scope=memory_scope,
                on_step=log_step,
            )
            log_step("memory_service.log_chat_trace.stream")
            memory_service.log_chat_trace(
                request_id=request_id,
                memory_scope=memory_scope,
                user_text=user_text,
                assistant_text=final_text,
                model=upstream_model,
                retrieved_items=retrieval_trace_items,
                had_error=False,
            )
        log_step("stream_response.done")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

