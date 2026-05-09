from __future__ import annotations

import json
import hashlib
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from config import HUMANIZE_RESPONSES, HUMAN_TONE_INSTRUCTION
from gateway.memory_metrics import memory_metrics

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


def _normalized_scope(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    value = raw.strip().lower()
    if not value:
        return ""
    # Keep scope tokens filesystem/sql friendly.
    safe = "".join(ch if (ch.isalnum() or ch in {"@", ".", "_", "-"}) else "_" for ch in value)
    normalized = safe[:128].strip("_")
    if normalized:
        return normalized
    # Avoid silently collapsing malformed non-empty scopes into global.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"invalid_scope_{digest}"


def resolve_memory_scope(request: Request, body: dict[str, Any]) -> str:
    identity_scope = ""
    identity_key = ""
    for key in (
        "x-user-email",
        "x-openwebui-user-email",
        "x-auth-request-email",
        "x-forwarded-email",
        "x-user-id",
        "x-openwebui-user-id",
        "x-auth-request-user",
        "x-forwarded-user",
    ):
        candidate = _normalized_scope(request.headers.get(key))
        if candidate:
            identity_scope = candidate
            identity_key = key
            break

    body_scope = body.get("memory_scope")
    normalized_body_scope = _normalized_scope(body_scope)
    if identity_scope and normalized_body_scope and normalized_body_scope != identity_scope:
        memory_metrics.record_scope_resolution(
            resolved_scope=identity_scope,
            source="identity_override_body_scope",
            source_key=identity_key,
        )
        return identity_scope
    if normalized_body_scope and not identity_scope:
        memory_metrics.record_scope_resolution(
            resolved_scope=normalized_body_scope,
            source="body",
            source_key="memory_scope",
        )
        return normalized_body_scope

    # Explicit scope header has top priority after request body.
    explicit_scope = _normalized_scope(request.headers.get("x-memory-scope"))
    if identity_scope and explicit_scope and explicit_scope != identity_scope:
        memory_metrics.record_scope_resolution(
            resolved_scope=identity_scope,
            source="identity_override_header_scope",
            source_key=identity_key,
        )
        return identity_scope
    if explicit_scope and not identity_scope:
        memory_metrics.record_scope_resolution(
            resolved_scope=explicit_scope,
            source="header",
            source_key="x-memory-scope",
        )
        return explicit_scope

    # Permanent stable fallback from user identity headers.
    # This keeps one user mapped to one scope automatically.
    if identity_scope:
        memory_metrics.record_scope_resolution(
            resolved_scope=identity_scope,
            source="identity_header",
            source_key=identity_key,
        )
        return identity_scope
    memory_metrics.record_scope_resolution(
        resolved_scope="global",
        source="default",
        source_key="none",
    )
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
                meta = part.get("meta")
                if isinstance(meta, dict) and bool(meta.get("gateway_auto_instruction")):
                    # Ignore gateway-injected helper prompts when extracting user text.
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

