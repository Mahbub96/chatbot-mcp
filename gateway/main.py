import json
import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent.llm import complete_llm, edit_image, generate_image, stream_llm
from config import (
    BANGLA_MODEL,
    CODE_MODEL,
    IMAGE_BASE_URL,
    IMAGE_EDIT_MODEL,
    IMAGE_EDIT_BASE_URL,
    IMAGE_GEN_MODEL,
    MEMORY_ENABLED,
    MODEL as DEFAULT_UPSTREAM_MODEL,
    VISION_MODEL,
)
from memory import memory_service
from permissions.approvals import approval_store
from permissions.policy import evaluate_tool_action
from router.model_router import pick_upstream_model
from router.tool_router import maybe_run_legacy_keyword_tool
from tools.registry import TOOLS, run_tool

logger = logging.getLogger(__name__)

app = FastAPI(title="Local MCP Gateway", version="1.0.0")

MODEL_NAME = "local-mcp-model"
TOOL_TEST_FILE_PATH = "test.txt"

RATE_LIMIT_WINDOW_SECONDS = 100
RATE_LIMIT_MAX_REQUESTS = 100
BANGLA_MODEL_COOLDOWN_SECONDS = 300
FAST_BANGLA_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
ERR_MEMORY_DISABLED = "Memory is disabled"
ERR_TOO_MANY_REQUESTS = "Too many requests"
ERR_INVALID_JSON_BODY = "Invalid JSON body"
ERR_BODY_OBJECT_REQUIRED = "Request body must be an object"

SYSTEM_PROMPT = (
    "You are a helpful local AI assistant.\n"
    "You can use tools when needed.\n"
    "Be concise and practical."
)


class InMemoryRateLimiter:
    def __init__(self, window_seconds: int, max_requests: int):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._request_tracker: dict[str, list[float]] = {}

    def is_limited(self, key: str) -> bool:
        now = time.time()
        timestamps = self._request_tracker.get(key, [])
        fresh = [ts for ts in timestamps if (now - ts) < self.window_seconds]

        if len(fresh) >= self.max_requests:
            self._request_tracker[key] = fresh
            return True

        fresh.append(now)
        self._request_tracker[key] = fresh
        return False


rate_limiter = InMemoryRateLimiter(
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    max_requests=RATE_LIMIT_MAX_REQUESTS,
)
_model_unavailable_until: dict[str, float] = {}


def safe_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [msg for msg in messages if isinstance(msg, dict)]


def inject_system_message(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(msg.get("role") == "system" for msg in messages):
        return messages
    return [{"role": "system", "content": SYSTEM_PROMPT}, *messages]


def has_multimodal(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(msg.get("content"), list) for msg in messages)


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


def normalize_image_error(exc: Exception, *, model: str, endpoint: str, action: str) -> str:
    msg = str(exc)
    if "[LLM_ERROR 404]" in msg:
        return (
            f"{action} endpoint/model not available for current NVIDIA account. "
            f"model={model}, endpoint={endpoint}. "
            "Set a valid model/endpoint pair for your account."
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
    if not model_id:
        return False
    until = _model_unavailable_until.get(model_id)
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
            logger.info("Bangla model in cooldown, routing to fast Bangla fallback model.")
            return FAST_BANGLA_FALLBACK_MODEL
        logger.info("Bangla model in cooldown, routing directly to default model.")
        return DEFAULT_UPSTREAM_MODEL
    return preferred_model


def bangla_fallback_model() -> str:
    if FAST_BANGLA_FALLBACK_MODEL and FAST_BANGLA_FALLBACK_MODEL != BANGLA_MODEL:
        return FAST_BANGLA_FALLBACK_MODEL
    return DEFAULT_UPSTREAM_MODEL


def sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def build_chunk_payload(
    *,
    chunk_id: str,
    delta_content: str | None = None,
    finish_reason: str | None = None,
    model: str = MODEL_NAME,
) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta_content} if delta_content is not None else {},
                "finish_reason": finish_reason,
            }
        ],
    }


def build_non_stream_response(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def parse_completion_request(body: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    messages = inject_system_message(safe_messages(body.get("messages", [])))
    stream = bool(body.get("stream", True))
    return messages, stream


def resolve_memory_scope(request: Request, body: dict[str, Any]) -> str:
    body_scope = body.get("memory_scope")
    if isinstance(body_scope, str) and body_scope.strip():
        return body_scope.strip()
    header_scope = request.headers.get("x-memory-scope")
    if isinstance(header_scope, str) and header_scope.strip():
        return header_scope.strip()
    return "global"


def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            if parts:
                return "\n".join(parts)
    return ""


def inject_memory_context(
    messages: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not memories:
        return messages
    lines: list[str] = []
    for idx, item in enumerate(memories[:5], start=1):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{idx}. {text}")
    if not lines:
        return messages

    memory_block = {
        "role": "system",
        "content": (
            "Relevant long-term memory for the same current user:\n"
            "Treat these items as known user facts unless the user corrects them.\n"
            + "\n".join(lines)
        ),
    }
    if messages and messages[0].get("role") == "system":
        return [messages[0], memory_block, *messages[1:]]
    return [memory_block, *messages]


def should_persist_user_memory(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 8:
        return False
    if text.endswith("?") or text.endswith("؟"):
        return False
    return True


def select_context_memories(user_text: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_query = (user_text or "").strip().lower()
    selected: list[dict[str, Any]] = []
    for item in memories:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        if normalized_query and text.lower() == normalized_query:
            continue
        source = (item.get("source") or "").strip().lower()
        if source == "chat_assistant":
            continue
        if text.endswith("?") or text.endswith("؟"):
            continue
        selected.append(item)
        if len(selected) >= 5:
            break
    return selected


def build_memory_fallback_answer(user_text: str, memories: list[dict[str, Any]]) -> str | None:
    if not memories:
        return None
    top = memories[0]
    top_text = (top.get("text") or "").strip()
    if not top_text:
        return None

    query = (user_text or "").strip()
    if query.endswith("?") or query.endswith("؟"):
        return f"From local memory: {top_text}"
    return f"Relevant local memory: {top_text}"


def build_memory_first_answer(user_text: str, memories: list[dict[str, Any]]) -> str | None:
    if not memories:
        return None
    query = (user_text or "").strip()
    if not query or not (query.endswith("?") or query.endswith("؟")):
        return None

    top = memories[0]
    top_text = (top.get("text") or "").strip()
    if not top_text:
        return None
    if (top.get("source") or "").strip().lower() == "chat_assistant":
        return None
    if len(top_text) > 600:
        return None
    if (top.get("score") or 0.0) < 0.6:
        return None
    return f"From local memory: {top_text}"


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def execute_tool_with_policy(name: str, args: dict[str, Any], approval_id: str | None = None) -> dict[str, Any]:
    policy = evaluate_tool_action(name, args)
    if policy.requires_approval:
        if isinstance(approval_id, str) and approval_id.strip():
            ok, reason = approval_store.consume_if_valid(approval_id, name, args)
            if not ok:
                return {
                    "success": False,
                    "requires_approval": True,
                    "error": reason,
                }
        else:
            pending = approval_store.create(
                tool_name=name,
                arguments=args,
                reason=policy.reason,
                risk_level=policy.risk_level,
            )
            return {
                "success": False,
                "requires_approval": True,
                "approval_id": pending.approval_id,
                "risk_level": pending.risk_level,
                "reason": pending.reason,
                "tool": name,
                "arguments": args,
            }
    return {"success": True, "tool": name, "result": run_tool(name, args)}


@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@app.get("/mcp/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": name,
                "description": f"Auto-loaded tool: {name}",
                "parameters": {"type": "object"},
            }
            for name in sorted(TOOLS.keys())
        ]
    }


@app.get("/memory/items")
def memory_items(memory_scope: str = "global", limit: int = 50, offset: int = 0):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return {"success": True, "items": memory_service.list_items(memory_scope=memory_scope, limit=limit, offset=offset)}


@app.post("/memory/items")
async def memory_add_item(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    text = payload.get("text", "")
    memory_scope = payload.get("memory_scope", "global")
    source = payload.get("source", "manual")
    importance = payload.get("importance", 0.6)
    return memory_service.add_memory(
        text=str(text),
        memory_scope=str(memory_scope),
        source=str(source),
        importance=float(importance),
    )


@app.post("/memory/search")
async def memory_search(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    query = payload.get("query", "")
    memory_scope = payload.get("memory_scope", "global")
    limit = payload.get("limit", 5)
    return {
        "success": True,
        "items": memory_service.search(query=str(query), memory_scope=str(memory_scope), limit=int(limit)),
    }


@app.delete("/memory/items/{item_id}")
async def memory_delete_item(item_id: str, memory_scope: str = "global"):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return memory_service.delete_item(item_id=item_id, memory_scope=memory_scope)


@app.post("/memory/reindex")
async def memory_reindex(payload: dict[str, Any] | None = None):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    payload = payload or {}
    memory_scope = payload.get("memory_scope", "global")
    return memory_service.reindex(memory_scope=str(memory_scope))


@app.post("/mcp/execute")
async def execute_tool(payload: dict[str, Any]):
    name = payload.get("name")
    args = payload.get("arguments", {})
    approval_id = payload.get("approval_id")

    if not isinstance(name, str) or not name.strip():
        return {"success": False, "error": "Missing tool name"}
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    return execute_tool_with_policy(name, args, approval_id=approval_id)


@app.get("/mcp/approvals")
def list_pending_approvals():
    return {"pending": approval_store.list_pending()}


@app.post("/mcp/approve")
async def set_approval(payload: dict[str, Any]):
    approval_id = payload.get("approval_id")
    approved = payload.get("approved")
    if not isinstance(approval_id, str) or not approval_id.strip():
        return {"success": False, "error": "approval_id is required"}
    if not isinstance(approved, bool):
        return {"success": False, "error": "approved must be boolean"}

    item = approval_store.set_decision(approval_id, approved=approved)
    if not item:
        return {"success": False, "error": "Approval not found"}

    return {
        "success": True,
        "approval_id": item.approval_id,
        "approved": item.approved,
        "tool_name": item.tool_name,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
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
    context_memories: list[dict[str, Any]] = []
    memory_first_answer: str | None = None

    if MEMORY_ENABLED and user_text:
        try:
            memories = memory_service.search(query=user_text, memory_scope=memory_scope, limit=10)
            context_memories = select_context_memories(user_text, memories)
            llm_messages = inject_memory_context(messages, context_memories)
            memory_first_answer = build_memory_first_answer(user_text, context_memories)
        except Exception as exc:
            logger.warning("Memory retrieval failed: %s", exc)

    if has_multimodal(llm_messages) and not VISION_MODEL:
        return json_error(
            400,
            "Image input detected but VISION_MODEL is not configured. "
            "Set VISION_MODEL to a vision-capable NVIDIA NIM model id.",
        )
    selected_model = pick_upstream_model(
        llm_messages,
        default_model=DEFAULT_UPSTREAM_MODEL,
        bangla_model=BANGLA_MODEL,
        code_model=CODE_MODEL or None,
        vision_model=VISION_MODEL or None,
    )
    upstream_model = choose_runtime_model(selected_model)

    tool_output = maybe_run_legacy_keyword_tool(
        llm_messages,
        tool_runner=lambda name, args: execute_tool_with_policy(name, args, approval_id=None),
        test_file_path=TOOL_TEST_FILE_PATH,
    )
    tool_prefix = ""
    if tool_output is not None:
        tool_prefix = f"\n[TOOL RESULT]\n{json.dumps(tool_output)}\n"
        # If the action is pending approval, do not continue with LLM text.
        if tool_output.get("requires_approval") is True:
            if not stream:
                return build_non_stream_response(tool_prefix)

            async def approval_only_stream():
                yield ":\n\n"
                yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
                yield "data: [DONE]\n\n"

            return StreamingResponse(approval_only_stream(), media_type="text/event-stream")

    if memory_first_answer and not has_multimodal(llm_messages):
        if not stream:
            return build_non_stream_response(tool_prefix + memory_first_answer)

        async def memory_first_stream():
            yield ":\n\n"
            if tool_prefix:
                yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
            yield sse_data(
                build_chunk_payload(
                    chunk_id="memory-first",
                    delta_content=memory_first_answer,
                )
            )
            yield sse_data(
                build_chunk_payload(
                    chunk_id="memory-first",
                    finish_reason="stop",
                )
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(memory_first_stream(), media_type="text/event-stream")

    if not stream:
        try:
            text = await complete_llm(llm_messages, model=upstream_model)
            if MEMORY_ENABLED and should_persist_user_memory(user_text):
                try:
                    memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
                except Exception as exc:
                    logger.warning("Memory write failed (non-stream): %s", exc)
            return build_non_stream_response(tool_prefix + text)
        except Exception as exc:
            if should_fallback_bangla_model(upstream_model, str(exc)):
                mark_model_unavailable(BANGLA_MODEL, BANGLA_MODEL_COOLDOWN_SECONDS)
                fallback_model = bangla_fallback_model()
                logger.warning(
                    "Bangla model unavailable (404). Falling back to %s for non-stream request and enabling cooldown.",
                    fallback_model,
                )
                try:
                    text = await complete_llm(llm_messages, model=fallback_model)
                    if MEMORY_ENABLED and should_persist_user_memory(user_text):
                        try:
                            memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
                        except Exception as write_exc:
                            logger.warning("Memory write failed (fallback non-stream): %s", write_exc)
                    return build_non_stream_response(tool_prefix + text)
                except Exception as fallback_exc:
                    logger.exception("Bangla fallback non-stream completion failed: %s", fallback_exc)
                    return json_error(502, str(fallback_exc))
            logger.exception("Non-stream completion failed: %s", exc)
            fallback_answer = build_memory_fallback_answer(user_text, context_memories)
            if fallback_answer:
                logger.warning("Serving response from local memory fallback due to LLM error.")
                return build_non_stream_response(tool_prefix + fallback_answer)
            return json_error(
                502,
                normalize_chat_error(
                    exc,
                    had_image_input=has_multimodal(llm_messages),
                    model=upstream_model,
                ),
            )

    async def generate():
        # Send an initial SSE comment to flush headers quickly (prevents client/proxy timeouts
        # when the upstream takes time to emit the first token).
        yield ":\n\n"
        if tool_prefix:
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))
        collected_tokens: list[str] = []

        try:
            async for token in stream_llm(llm_messages, model=upstream_model):
                if not token:
                    continue
                if should_fallback_bangla_model(upstream_model, token):
                    mark_model_unavailable(BANGLA_MODEL, BANGLA_MODEL_COOLDOWN_SECONDS)
                    fallback_model = bangla_fallback_model()
                    logger.warning(
                        "Bangla model unavailable (404). Falling back to %s for stream request and enabling cooldown.",
                        fallback_model,
                    )
                    async for fallback_token in stream_llm(llm_messages, model=fallback_model):
                        if not fallback_token:
                            continue
                        collected_tokens.append(fallback_token)
                        yield sse_data(
                            build_chunk_payload(chunk_id="chatcmpl-local", delta_content=fallback_token)
                        )
                    break
                collected_tokens.append(token)
                yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=token))
        except Exception as exc:
            logger.exception("Stream completion failed: %s", exc)
            fallback_answer = build_memory_fallback_answer(user_text, context_memories)
            if fallback_answer and not collected_tokens:
                logger.warning("Serving stream response from local memory fallback due to LLM error.")
                yield sse_data(
                    build_chunk_payload(
                        chunk_id="memory-fallback",
                        delta_content=fallback_answer,
                    )
                )
                yield sse_data(
                    build_chunk_payload(
                        chunk_id="memory-fallback",
                        finish_reason="stop",
                    )
                )
                yield "data: [DONE]\n\n"
                return
            yield sse_data(
                build_chunk_payload(
                    chunk_id="error",
                    delta_content=f"[ERROR] {str(exc)}",
                    finish_reason="stop",
                )
            )
        if MEMORY_ENABLED and should_persist_user_memory(user_text) and collected_tokens:
            try:
                memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
            except Exception as exc:
                logger.warning("Memory write failed (stream): %s", exc)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/v1/images/generations")
async def images_generations(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, ERR_TOO_MANY_REQUESTS)

    try:
        body = await request.json()
    except Exception:
        return json_error(400, ERR_INVALID_JSON_BODY)

    if not isinstance(body, dict):
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    prompt = body.get("prompt", "")
    model = body.get("model") or IMAGE_GEN_MODEL
    size = body.get("size", "1024x1024")
    n = body.get("n", 1)

    try:
        result = await generate_image(prompt=prompt, model=model, size=size, n=n)
        return result
    except Exception as exc:
        logger.exception("Image generation failed: %s", exc)
        return json_error(
            502,
            normalize_image_error(
                exc,
                model=model,
                endpoint=IMAGE_BASE_URL,
                action="Image generation",
            ),
        )


@app.post("/v1/images/edits")
async def images_edits(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, ERR_TOO_MANY_REQUESTS)

    try:
        body = await request.json()
    except Exception:
        return json_error(400, ERR_INVALID_JSON_BODY)

    if not isinstance(body, dict):
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    prompt = body.get("prompt", "")
    image = body.get("image", "")
    mask = body.get("mask")
    model = body.get("model") or IMAGE_EDIT_MODEL
    size = body.get("size", "1024x1024")
    n = body.get("n", 1)

    try:
        result = await edit_image(
            prompt=prompt,
            image=image,
            model=model,
            size=size,
            n=n,
            mask=mask,
        )
        return result
    except Exception as exc:
        logger.exception("Image edit failed: %s", exc)
        return json_error(
            502,
            normalize_image_error(
                exc,
                model=model,
                endpoint=IMAGE_EDIT_BASE_URL,
                action="Image edit",
            ),
        )