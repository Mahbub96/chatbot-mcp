from __future__ import annotations

from typing import Any, Callable


def get_last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
    return ""


def maybe_run_legacy_keyword_tool(
    messages: list[dict[str, Any]],
    *,
    tool_runner: Callable[[str, dict[str, Any]], dict[str, Any]],
    test_file_path: str,
) -> dict[str, Any] | None:
    """
    Legacy heuristic for demo/testing.

    If the user message contains simple keywords like "read file",
    execute the local `file_tools` tool on `test_file_path`.

    Note: This is not full LLM tool-calling. It's a lightweight router.
    """
    user_msg = get_last_user_message(messages)
    if not user_msg:
        return None

    lowered = user_msg.lower()

    if "read file" in lowered:
        return tool_runner("file_tools", {"action": "read", "path": test_file_path})

    if "write file" in lowered:
        return tool_runner(
            "file_tools",
            {"action": "write", "path": test_file_path, "content": user_msg},
        )

    if "delete file" in lowered:
        return tool_runner("file_tools", {"action": "delete", "path": test_file_path})

    return None

