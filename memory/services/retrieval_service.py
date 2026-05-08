from __future__ import annotations

from typing import Any
import logging

from gateway.memory_metrics import memory_metrics
from memory.service import memory_service

logger = logging.getLogger(__name__)

class RetrievalService:
    """Read-focused memory retrieval service with strict stage order."""

    @staticmethod
    def _dedupe_key(item: dict[str, Any]) -> str:
        item_id = str(item.get("id") or "").strip()
        if item_id:
            return item_id
        return str(item.get("text") or "").strip().lower()

    @staticmethod
    def _token_overlap_ratio(query: str, text: str) -> float:
        query_tokens = [t for t in query.split() if t]
        if not query_tokens:
            return 0.0
        lower_text = (text or "").lower()
        overlap = sum(1 for token in query_tokens if token in lower_text)
        return float(overlap) / float(max(1, len(query_tokens)))

    @staticmethod
    def _lexical_item(row: dict[str, Any], query: str) -> dict[str, Any]:
        text = str(row.get("text") or "").strip()
        score = RetrievalService._token_overlap_ratio(query, text)
        return {
            "id": row.get("id"),
            "text": text,
            "score": score,
            "source": "lexical",
            "category": row.get("category", "general"),
            "structured_data": {
                **(row.get("structured_data", {}) if isinstance(row.get("structured_data"), dict) else {}),
                "lexical_from_source": str(row.get("source") or ""),
            },
            "importance": float(row.get("importance") or 0.0),
            "confidence": float(row.get("confidence") or 0.0),
            "created_at": row.get("created_at", ""),
        }

    @staticmethod
    def _source_group(source: str) -> str:
        normalized = (source or "").strip().lower()
        if normalized in {"short_trace", "short_trace_context"}:
            return "short_term"
        if normalized == "long_term_attribute":
            return "long_term"
        if normalized in {"chat_user", "chat_assistant", "profile_fact", "profile_full", "manual"}:
            return "primary"
        return "lexical"

    def _record_blend(self, *, memory_scope: str, items: list[dict[str, Any]]) -> None:
        blend_counts = {"short_term": 0, "long_term": 0, "primary": 0, "lexical": 0}
        for item in items:
            blend_counts[self._source_group(str(item.get("source") or ""))] += 1
        top_source = str(items[0].get("source") or "none").strip().lower() if items else "none"
        memory_metrics.record_retrieval_source_blend(
            memory_scope=memory_scope,
            source_counts=blend_counts,
            top_source=top_source,
        )

    def retrieve(self, *, query: str, memory_scope: str, limit: int = 5) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        normalized_scope = str(memory_scope or "global").strip() or "global"
        safe_limit = max(1, int(limit or 5))
        if not normalized_query:
            return []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _append_stage(items: list[dict[str, Any]]) -> None:
            for item in items:
                key = self._dedupe_key(item)
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(item)
                if len(out) >= safe_limit:
                    return

        try:
            # Stage 1: short-term slot facts
            _append_stage(
                memory_service.list_short_term_slot_facts(
                    query=normalized_query,
                    memory_scope=normalized_scope,
                    limit=safe_limit,
                )
            )
            if len(out) < safe_limit:
                # Stage 2: short-term contextual facts
                _append_stage(
                    memory_service.list_short_term_context_facts(
                        query=normalized_query,
                        memory_scope=normalized_scope,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                # Stage 2b: cross-tab short-term slot/context fallback
                _append_stage(
                    memory_service.list_short_term_slot_facts_any_scope(
                        query=normalized_query,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                _append_stage(
                    memory_service.list_short_term_context_facts_any_scope(
                        query=normalized_query,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                # Stage 3: long-term structured facts
                _append_stage(
                    memory_service.list_long_term_slot_facts(
                        query=normalized_query,
                        memory_scope=normalized_scope,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                # Stage 3b: cross-tab long-term structured facts
                _append_stage(
                    memory_service.list_long_term_slot_facts_any_scope(
                        query=normalized_query,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                # Stage 4: vector/fts-backed primary retrieval
                _append_stage(
                    memory_service.search(
                        query=normalized_query,
                        memory_scope=normalized_scope,
                        limit=safe_limit,
                    )
                )
            if len(out) < safe_limit:
                # Stage 5: lexical fallback from scope items
                lexical_pool = memory_service.list_items(memory_scope=normalized_scope, limit=200, offset=0)
                lexical: list[dict[str, Any]] = []
                for row in lexical_pool:
                    text = str(row.get("text") or "").strip()
                    if not text:
                        continue
                    if self._token_overlap_ratio(normalized_query.lower(), text) <= 0.0:
                        continue
                    lexical.append(self._lexical_item(row, normalized_query.lower()))
                lexical.sort(
                    key=lambda item: (
                        float(item.get("score") or 0.0),
                        float(item.get("confidence") or 0.0),
                        float(item.get("importance") or 0.0),
                    ),
                    reverse=True,
                )
                _append_stage(lexical)
            if len(out) < safe_limit:
                # Stage 5b: lexical fallback across all scopes (global DB access)
                any_scope_pool = []
                # Pull from full legacy record set across all scopes (includes manual/source records).
                for row in memory_service.repo.list_all(limit=1200, offset=0):
                    any_scope_pool.append(
                        {
                            "id": row.id,
                            "memory_scope": row.memory_scope,
                            "text": row.text,
                            "source": row.source,
                            "category": row.category,
                            "structured_data": {},
                            "importance": row.importance,
                            "confidence": row.confidence,
                            "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
                        }
                    )
                any_scope_pool.extend(memory_service.list_profile_memories_any_scope(limit=400))
                any_scope_pool.extend(memory_service.list_profile_facts_any_scope(limit=200))
                any_scope_pool.extend(
                    memory_service.list_short_term_context_facts_any_scope(
                        query=normalized_query,
                        limit=200,
                    )
                )
                lexical_any: list[dict[str, Any]] = []
                for row in any_scope_pool:
                    text = str(row.get("text") or "").strip()
                    if not text:
                        continue
                    if self._token_overlap_ratio(normalized_query.lower(), text) <= 0.0:
                        continue
                    lexical_any.append(self._lexical_item(row, normalized_query.lower()))
                lexical_any.sort(
                    key=lambda item: (
                        float(item.get("score") or 0.0),
                        float(item.get("confidence") or 0.0),
                        float(item.get("importance") or 0.0),
                    ),
                    reverse=True,
                )
                _append_stage(lexical_any)
            self._record_blend(memory_scope=normalized_scope, items=out[:safe_limit])
            return out[:safe_limit]
        except Exception:
            logger.debug("retrieval_fallback_primary_search", exc_info=True)
            fallback = memory_service.search(query=normalized_query, memory_scope=normalized_scope, limit=safe_limit)
            self._record_blend(memory_scope=normalized_scope, items=fallback[:safe_limit])
            return fallback[:safe_limit]

    def list_items(self, *, memory_scope: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return memory_service.list_items(memory_scope=memory_scope, limit=limit, offset=offset)

