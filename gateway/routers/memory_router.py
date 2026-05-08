from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request

from config import MEMORY_ENABLED
from gateway.helpers.http_utils import resolve_memory_scope
from gateway.memory_metrics import memory_metrics
from memory.facade import memory_facade

ERR_MEMORY_DISABLED = "Memory is disabled"

router = APIRouter()


@router.get("/memory/items")
def memory_items(
    request: Request,
    memory_scope: str = "global",
    limit: int = 50,
    offset: int = 0,
    include_legacy: bool = True,
    include_short_traces: bool = True,
):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    resolved_scope = resolve_memory_scope(request, {"memory_scope": memory_scope})
    safe_limit = max(1, min(200, int(limit or 50)))
    safe_offset = max(0, int(offset or 0))
    # Pull enough rows from each source to support merged pagination.
    fetch_window = min(500, safe_limit + safe_offset + 50)
    merged: list[dict[str, Any]] = []
    if include_legacy:
        legacy_rows = memory_facade.list_items(memory_scope=resolved_scope, limit=fetch_window, offset=0)
        for row in legacy_rows:
            item = dict(row)
            item["table_source"] = "memory_records"
            merged.append(item)
    if include_short_traces:
        short_rows = memory_facade.repo.list_recent_short_traces(memory_scope=resolved_scope, limit=fetch_window)
        for trace in short_rows:
            created = trace.get("created_at")
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
            merged.append(
                {
                    "id": str(trace.get("id") or ""),
                    "memory_scope": resolved_scope,
                    "text": str(trace.get("user_message") or "").strip(),
                    "source": "short_trace",
                    "category": "short_term",
                    "structured_data": {
                        "trace_id": str(trace.get("trace_id") or ""),
                        "assistant_response": str(trace.get("assistant_response") or "").strip(),
                        "retrieval_method": str(trace.get("retrieval_method") or "none"),
                    },
                    "importance": float(trace.get("confidence_score") or 0.0),
                    "confidence": float(trace.get("confidence_score") or 0.0),
                    "created_at": created_at,
                    "table_source": "short_traces",
                }
            )
    merged.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    items = merged[safe_offset : safe_offset + safe_limit]
    return {
        "success": True,
        "memory_scope": resolved_scope,
        "items": items,
        "total_candidates": len(merged),
        "sources": {
            "include_legacy": bool(include_legacy),
            "include_short_traces": bool(include_short_traces),
        },
    }


@router.post("/memory/items")
async def memory_add_item(request: Request, payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    text = payload.get("text", "")
    memory_scope = resolve_memory_scope(request, payload)
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
async def memory_store(request: Request, payload: dict[str, Any]):
    return await memory_add_item(request, payload)


@router.post("/memory/search")
async def memory_search(request: Request, payload: dict[str, Any]):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    query = payload.get("query", "")
    memory_scope = resolve_memory_scope(request, payload)
    limit = payload.get("limit", 5)
    source_filter = str(payload.get("source") or "").strip().lower()
    category_filter = str(payload.get("category") or "").strip().lower()
    safe_limit = max(1, int(limit or 5))
    # Pull a wider candidate set so post-filtering can still return up to requested limit.
    candidate_limit = min(100, safe_limit * 5)
    items = memory_facade.retrieve_memory(
        query=str(query),
        memory_scope=str(memory_scope),
        limit=candidate_limit,
    )
    if source_filter:
        items = [item for item in items if str(item.get("source") or "").strip().lower() == source_filter]
    if category_filter:
        items = [item for item in items if str(item.get("category") or "").strip().lower() == category_filter]
    if not items:
        query_tokens = {tok for tok in re.findall(r"\w+", str(query or "").lower()) if len(tok) >= 2}
        lexical_any_scope: list[dict[str, Any]] = []
        if query_tokens:
            for row in memory_facade.repo.list_all(limit=2000, offset=0):
                text = str(row.text or "").strip()
                if not text:
                    continue
                text_tokens = {tok for tok in re.findall(r"\w+", text.lower()) if len(tok) >= 2}
                overlap = len(query_tokens.intersection(text_tokens))
                if overlap <= 0:
                    continue
                score = overlap / max(1.0, float(len(query_tokens)))
                lexical_any_scope.append(
                    {
                        "id": row.id,
                        "memory_scope": row.memory_scope,
                        "text": text,
                        "score": float(score),
                        "source": str(row.source or "lexical_any_scope"),
                        "category": str(row.category or "general"),
                        "structured_data": {},
                        "importance": float(row.importance or 0.0),
                        "confidence": float(row.confidence or 0.0),
                        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
                    }
                )
        lexical_any_scope.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                float(item.get("importance") or 0.0),
            ),
            reverse=True,
        )
        items = lexical_any_scope
        if source_filter:
            items = [item for item in items if str(item.get("source") or "").strip().lower() == source_filter]
        if category_filter:
            items = [item for item in items if str(item.get("category") or "").strip().lower() == category_filter]
    return {
        "success": True,
        "items": items[:safe_limit],
    }


@router.get("/memory/stats")
def memory_stats(request: Request, memory_scope: str = "global"):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    scope = str(resolve_memory_scope(request, {"memory_scope": memory_scope}) or "global")
    short_total = memory_facade.repo.count_short_traces(memory_scope=scope)
    recent_short = memory_facade.repo.list_recent_short_traces(memory_scope=scope, limit=5)
    return {
        "success": True,
        "stats": {
            **memory_facade.get_memory_observability(memory_scope=scope),
            "short_term_trace_total": int(short_total),
            "recent_short_traces": recent_short,
            "wrong_answer_guard_triggers": memory_metrics.get_wrong_answer_guard_triggers(memory_scope=scope),
            "scope_resolution_trace": memory_metrics.get_scope_snapshot(memory_scope=scope),
            "retrieval_source_blend": memory_metrics.get_retrieval_source_blend_snapshot(memory_scope=scope),
            "shadow_monitor": memory_metrics.get_shadow_snapshot(memory_scope=scope),
        },
    }


@router.get("/memory/short-traces")
def memory_short_traces(request: Request, memory_scope: str = "global", limit: int = 50):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    scope = str(resolve_memory_scope(request, {"memory_scope": memory_scope}) or "global")
    safe_limit = max(1, min(200, int(limit or 50)))
    items = memory_facade.repo.list_recent_short_traces(memory_scope=scope, limit=safe_limit)
    return {"success": True, "memory_scope": scope, "count": len(items), "items": items}


@router.delete("/memory/items/{item_id}")
async def memory_delete_item(request: Request, item_id: str, memory_scope: str = "global"):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    resolved_scope = resolve_memory_scope(request, {"memory_scope": memory_scope})
    return memory_facade.delete_item(item_id=item_id, memory_scope=resolved_scope)


@router.post("/memory/reindex")
async def memory_reindex(request: Request, payload: dict[str, Any] | None = None):
    if not MEMORY_ENABLED:
        return {"success": False, "error": ERR_MEMORY_DISABLED}
    payload = payload or {}
    memory_scope = resolve_memory_scope(request, payload)
    return memory_facade.reindex(memory_scope=str(memory_scope))

