from __future__ import annotations

from fastapi import APIRouter, Request

from gateway.controllers.chat_controller import handle_chat_completions

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await handle_chat_completions(request)

