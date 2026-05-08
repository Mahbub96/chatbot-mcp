from __future__ import annotations

from typing import Any


def contains_bangla_text(text: str) -> bool:
    if not text:
        return False
    # Bengali & Assamese Unicode block: U+0980..U+09FF
    return any("\u0980" <= ch <= "\u09FF" for ch in text)


def _iter_text_parts(content: Any):
    if isinstance(content, str):
        yield content
        return
    if not isinstance(content, list):
        return
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str):
            yield text


def has_image(messages: list[dict[str, Any]]) -> bool:
    """
    Detect whether any message contains an actual image part.
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                    return True
    return False


def contains_code_intent(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    code_markers = (
        "```",
        "def ",
        "class ",
        "function ",
        "import ",
        "fix bug",
        "debug",
        "refactor",
        "optimize code",
        "write code",
    )
    return any(marker in lowered for marker in code_markers)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        for text in _iter_text_parts(msg.get("content")):
            if text.strip():
                chunks.append(text)
        if chunks:
            return "\n".join(chunks)
    return ""


def pick_upstream_model(
    messages: list[dict[str, Any]],
    *,
    default_model: str,
    bangla_model: str,
    code_model: str | None = None,
    vision_model: str | None = None,
) -> str:
    """
    Choose an upstream model based on the latest user message content.

    Best-practice notes:
    - Routing must be deterministic.
    - Keep this function side-effect free (returns a string only).
    """
    if vision_model and has_image(messages):
        return vision_model

    latest_user_text = _latest_user_text(messages)

    if code_model:
        if contains_code_intent(latest_user_text):
            return code_model

    if not bangla_model:
        return default_model

    if contains_bangla_text(latest_user_text):
        return bangla_model

    return default_model

