import json
import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent.llm import complete_llm, stream_llm
from config import BANGLA_MODEL, MODEL as DEFAULT_UPSTREAM_MODEL, VISION_MODEL
from router.model_router import pick_upstream_model
from router.tool_router import maybe_run_legacy_keyword_tool
from tools.registry import TOOLS, run_tool

logger = logging.getLogger(__name__)

app = FastAPI(title="Local MCP Gateway", version="1.0.0")

MODEL_NAME = "local-mcp-model"
TOOL_TEST_FILE_PATH = "test.txt"

RATE_LIMIT_WINDOW_SECONDS = 100
RATE_LIMIT_MAX_REQUESTS = 100

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


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


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


@app.post("/mcp/execute")
async def execute_tool(payload: dict[str, Any]):
    name = payload.get("name")
    args = payload.get("arguments", {})

    if not isinstance(name, str) or not name.strip():
        return {"success": False, "error": "Missing tool name"}
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    return {"success": True, "tool": name, "result": run_tool(name, args)}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, "Too many requests")

    try:
        body = await request.json()
    except Exception:
        return json_error(400, "Invalid JSON body")

    if not isinstance(body, dict):
        return json_error(400, "Request body must be an object")

    messages, stream = parse_completion_request(body)
    if not messages:
        return json_error(400, "messages must be a non-empty array")

    if has_multimodal(messages) and not VISION_MODEL:
        return json_error(
            400,
            "Image input detected but VISION_MODEL is not configured. "
            "Set VISION_MODEL to a vision-capable NVIDIA NIM model id.",
        )

    upstream_model = pick_upstream_model(
        messages,
        default_model=DEFAULT_UPSTREAM_MODEL,
        bangla_model=BANGLA_MODEL,
        vision_model=VISION_MODEL or None,
    )

    tool_output = maybe_run_legacy_keyword_tool(
        messages,
        tool_runner=lambda name, args: run_tool(name, args),
        test_file_path=TOOL_TEST_FILE_PATH,
    )
    tool_prefix = ""
    if tool_output is not None:
        tool_prefix = f"\n[TOOL RESULT]\n{json.dumps(tool_output)}\n"

    if not stream:
        try:
            text = await complete_llm(messages, model=upstream_model)
            return build_non_stream_response(tool_prefix + text)
        except Exception as exc:
            logger.exception("Non-stream completion failed: %s", exc)
            return json_error(502, str(exc))

    async def generate():
        # Send an initial SSE comment to flush headers quickly (prevents client/proxy timeouts
        # when the upstream takes time to emit the first token).
        yield ":\n\n"
        if tool_prefix:
            yield sse_data(build_chunk_payload(chunk_id="tool", delta_content=tool_prefix))

        try:
            async for token in stream_llm(messages, model=upstream_model):
                if not token:
                    continue
                yield sse_data(build_chunk_payload(chunk_id="chatcmpl-local", delta_content=token))
        except Exception as exc:
            logger.exception("Stream completion failed: %s", exc)
            yield sse_data(
                build_chunk_payload(
                    chunk_id="error",
                    delta_content=f"[ERROR] {str(exc)}",
                    finish_reason="stop",
                )
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")