from __future__ import annotations

from typing import Any, AsyncIterator

from agent.llm import stream_llm


def build_prompt(code: str, cursor_line: int) -> list[dict[str, Any]]:
    # Keep prompt minimal and deterministic.
    return [
        {
            "role": "system",
            "content": "You are a Copilot-style inline code completion engine.",
        },
        {
            "role": "user",
            "content": (
                "Complete ONLY the code from cursor position.\n\n"
                f"CURSOR_LINE: {cursor_line}\n\n"
                f"CODE:\n{code}\n\n"
                "Return only the continuation."
            ),
        },
    ]


async def stream_suggestions(code: str, cursor_line: int, *, model: str | None = None) -> AsyncIterator[str]:
    messages = build_prompt(code, cursor_line)
    async for chunk in stream_llm(messages, model=model):
        if chunk:
            yield chunk