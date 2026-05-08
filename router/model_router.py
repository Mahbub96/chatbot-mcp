from __future__ import annotations

from typing import Any


def contains_bangla_text(text: str) -> bool:
    if not text:
        return False
    # Bengali & Assamese Unicode block: U+0980..U+09FF
    return any("\u0980" <= ch <= "\u09FF" for ch in text)

def has_image(messages: list[dict[str, Any]]) -> bool:
    """
    Detect whether any message contains multimodal/image content.

    OpenAI-style multimodal messages typically encode content as a list of parts,
    where one part is an image (e.g., type: 'image_url').
    """
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
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

    if code_model:
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and contains_code_intent(content):
                return code_model

    if not bangla_model:
        return default_model

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and contains_bangla_text(content):
            return bangla_model

    return default_model

