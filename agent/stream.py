from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agent.copilot import stream_suggestions

router = APIRouter()


def sse_data(obj: Any) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@router.post("/stream")
async def stream(payload: dict[str, Any]):
    """
    Lightweight streaming endpoint for IDE-style inline suggestions.

    Note: This module is optional and only used if mounted by a FastAPI app.
    """
    code = payload.get("code", "")
    cursor = int(payload.get("cursor", 0))
    model = payload.get("model")  # optional override

    async def event_generator() -> AsyncIterator[str]:
        async for token in stream_suggestions(code, cursor, model=model):
            yield sse_data({"token": token})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")