from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from config import MEMORY_ENABLED
from memory.facade import memory_facade

ERR_MEMORY_DISABLED = "Memory is disabled"

router = APIRouter()


@router.get("/memory/items")
def memory_items(memory_scope: str = "global", limit: int = 50, offset: int = 0):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return {"success": True, "items": memory_facade.list_items(memory_scope=memory_scope, limit=limit, offset=offset)}


@router.post("/memory/items")
async def memory_add_item(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    text = payload.get("text", "")
    memory_scope = payload.get("memory_scope", "global")
    source = payload.get("source", "manual")
    importance = payload.get("importance", 0.6)
    return memory_facade.add_memory(
        text=str(text),
        memory_scope=str(memory_scope),
        source=str(source),
        importance=float(importance),
        category=str(payload.get("category", "general")),
        structured_data=payload.get("structured_data"),
    )


@router.post("/memory/store")
async def memory_store(payload: dict[str, Any]):
    return await memory_add_item(payload)


@router.post("/memory/search")
async def memory_search(payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    query = payload.get("query", "")
    memory_scope = payload.get("memory_scope", "global")
    limit = payload.get("limit", 5)
    source_filter = payload.get("source")
    category_filter = payload.get("category")
    return {
        "success": True,
        "items": memory_facade.search(
            query=str(query),
            memory_scope=str(memory_scope),
            limit=int(limit),
            source_filter=str(source_filter) if source_filter else None,
            category_filter=str(category_filter) if category_filter else None,
        ),
    }


@router.delete("/memory/items/{item_id}")
async def memory_delete_item(item_id: str, memory_scope: str = "global"):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    return memory_facade.delete_item(item_id=item_id, memory_scope=memory_scope)


@router.post("/memory/reindex")
async def memory_reindex(payload: dict[str, Any] | None = None):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    payload = payload or {}
    memory_scope = payload.get("memory_scope", "global")
    return memory_facade.reindex(memory_scope=str(memory_scope))

