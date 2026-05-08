from __future__ import annotations

from typing import Any
import logging

from memory.service import memory_service

logger = logging.getLogger(__name__)

try:
    from langchain_core.runnables import RunnableLambda
except Exception:  # pragma: no cover - optional dependency path
    RunnableLambda = None  # type: ignore[assignment]


class RetrievalService:
    """Read-focused memory retrieval service."""

    def __init__(self) -> None:
        self._chain = self._build_chain()

    def _build_chain(self):
        if RunnableLambda is None:
            return None

        source_weight = {
            "manual": 1.25,
            "profile_fact": 1.2,
            "chat_user": 1.0,
            "profile_full": 0.95,
            "chat_assistant": 0.75,
        }

        def _retrieve(payload: dict[str, Any]) -> dict[str, Any]:
            query = str(payload.get("query") or "").strip()
            memory_scope = str(payload.get("memory_scope") or "global").strip() or "global"
            limit = int(payload.get("limit") or 5)
            primary = memory_service.search(query=query, memory_scope=memory_scope, limit=limit)
            # Minimal lexical fallback pool from current scope items.
            lexical_pool = memory_service.list_items(memory_scope=memory_scope, limit=200, offset=0)
            return {"primary": primary, "lexical_pool": lexical_pool, "query": query, "limit": limit}

        def _rerank(payload: dict[str, Any]) -> list[dict[str, Any]]:
            primary = list(payload.get("primary") or [])
            query = str(payload.get("query") or "").strip().lower()
            limit = int(payload.get("limit") or 5)
            if not query:
                return primary[:limit]
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in primary:
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen:
                    continue
                if item_id:
                    seen.add(item_id)
                out.append(item)
            # Add lexical-matched rows only if primary is thin.
            for row in payload.get("lexical_pool") or []:
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                overlap = sum(1 for token in query.split() if token and token in text.lower())
                if overlap <= 0:
                    continue
                item_id = str(row.get("id") or "")
                if item_id and item_id in seen:
                    continue
                if item_id:
                    seen.add(item_id)
                out.append(
                    {
                        "id": row.get("id"),
                        "text": text,
                        "score": float(overlap) / max(1.0, float(len(query.split()) or 1.0)),
                        "source": row.get("source", ""),
                        "category": row.get("category", "general"),
                        "structured_data": row.get("structured_data", {}),
                        "importance": float(row.get("importance") or 0.0),
                        "confidence": float(row.get("confidence") or 0.0),
                        "created_at": row.get("created_at", ""),
                    }
                )
            def _final_score(item: dict[str, Any]) -> float:
                base = float(item.get("score") or 0.0)
                confidence = float(item.get("confidence") or 0.0)
                importance = float(item.get("importance") or 0.0)
                source = str(item.get("source") or "").strip().lower()
                token_overlap = sum(1 for token in query.split() if token and token in str(item.get("text") or "").lower())
                overlap_norm = token_overlap / max(1.0, float(len(query.split()) or 1.0))
                quality = (0.55 * base) + (0.2 * confidence) + (0.15 * importance) + (0.1 * overlap_norm)
                return quality * float(source_weight.get(source, 0.9))

            out.sort(
                key=lambda x: (
                    _final_score(x),
                    float(x.get("confidence") or 0.0),
                    float(x.get("importance") or 0.0),
                ),
                reverse=True,
            )
            return out[:limit]

        return RunnableLambda(_retrieve) | RunnableLambda(_rerank)

    def retrieve(self, *, query: str, memory_scope: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._chain is None:
            return memory_service.search(query=query, memory_scope=memory_scope, limit=limit)
        payload = {"query": query, "memory_scope": memory_scope, "limit": limit}
        try:
            result = self._chain.invoke(payload)
            logger.debug("langchain_retrieval_success")
            return result if isinstance(result, list) else memory_service.search(query=query, memory_scope=memory_scope, limit=limit)
        except Exception:
            logger.debug("langchain_retrieval_fallback", exc_info=True)
            return memory_service.search(query=query, memory_scope=memory_scope, limit=limit)

    def list_items(self, *, memory_scope: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return memory_service.list_items(memory_scope=memory_scope, limit=limit, offset=offset)

