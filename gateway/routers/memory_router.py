from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from config import MEMORY_ENABLED
from memory import memory_service

ERR_MEMORY_DISABLED = "Memory is disabled"

router = APIRouter()


@router.get("/memory/items")
def memory_items(memory_scope: str = "global", limit: int = 50, offset: int = 0):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return {"success": True, "items": memory_service.list_items(memory_scope=memory_scope, limit=limit, offset=offset)}


@router.post("/memory/items")
async def memory_add_item(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    text = payload.get("text", "")
    memory_scope = payload.get("memory_scope", "global")
    source = payload.get("source", "manual")
    importance = payload.get("importance", 0.6)
    return memory_service.add_memory(
        text=str(text),
        memory_scope=str(memory_scope),
        source=str(source),
        importance=float(importance),
    )


@router.post("/memory/search")
async def memory_search(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    query = payload.get("query", "")
    memory_scope = payload.get("memory_scope", "global")
    limit = payload.get("limit", 5)
    return {
        "success": True,
        "items": memory_service.search(query=str(query), memory_scope=str(memory_scope), limit=int(limit)),
    }


@router.delete("/memory/items/{item_id}")
async def memory_delete_item(item_id: str, memory_scope: str = "global"):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return memory_service.delete_item(item_id=item_id, memory_scope=memory_scope)


@router.post("/memory/reindex")
async def memory_reindex(payload: dict[str, Any] | None = None):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    payload = payload or {}
    memory_scope = payload.get("memory_scope", "global")
    return memory_service.reindex(memory_scope=str(memory_scope))

