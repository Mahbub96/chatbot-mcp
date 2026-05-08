from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from config import HUMANIZE_RESPONSES, HUMAN_TONE_INSTRUCTION

MODEL_NAME = "local-mcp-model"
SYSTEM_PROMPT = (
    "You are a helpful local AI assistant.\n"
    "You can use tools when needed.\n"
    "Be concise and practical.\n"
    "Do not claim you cannot remember user information; this gateway may provide stored memory context.\n"
    "Be explicit about certainty: label exact stored facts as facts, and label assumptions/inferences as uncertain."
)
STYLE_PROMPT_PREFIX = "[gateway-style-humanized]"


def safe_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [msg for msg in messages if isinstance(msg, dict)]


def inject_system_message(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(msg.get("role") == "system" for msg in messages):
        return messages
    return [{"role": "system", "content": SYSTEM_PROMPT}, *messages]


def inject_human_style_message(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not HUMANIZE_RESPONSES:
        return messages
    style_content = f"{STYLE_PROMPT_PREFIX} {HUMAN_TONE_INSTRUCTION}"
    for msg in messages:
        if msg.get("role") != "system":
            continue
        content = msg.get("content")
        if isinstance(content, str) and STYLE_PROMPT_PREFIX in content:
            return messages
    if messages and messages[0].get("role") == "system":
        return [messages[0], {"role": "system", "content": style_content}, *messages[1:]]
    return [{"role": "system", "content": style_content}, *messages]


def parse_completion_request(body: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    messages = inject_system_message(safe_messages(body.get("messages", [])))
    messages = inject_human_style_message(messages)
    stream = bool(body.get("stream", True))
    return messages, stream


def has_multimodal(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(msg.get("content"), list) for msg in messages)


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


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})

