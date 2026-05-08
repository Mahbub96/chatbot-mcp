from __future__ import annotations

from typing import Any


def route_task(task_type: str) -> str:
    """
    Placeholder router for future task-based model routing.

    This repo's primary routing lives in `router/` (gateway routing).
    Keep this function deterministic and side-effect free.
    """
    task_type = (task_type or "").lower().strip()
    if task_type in {"code", "coding"}:
        return "code"
    if task_type in {"image", "vision"}:
        return "image"
    return "chat"


def route_from_messages(messages: list[dict[str, Any]]) -> str:
    """
    Minimal heuristic for choosing a task type from the last user message.
    """
    if not messages:
        return "chat"
    last = messages[-1].get("content", "")
    if not isinstance(last, str):
        return "chat"

    lowered = last.lower()
    if "```" in lowered or "def " in lowered or "class " in lowered:
        return "code"
    if "image" in lowered:
        return "image"
    return "chat"