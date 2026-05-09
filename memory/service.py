from __future__ import annotations

import re
import json
import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
import logging
from sqlalchemy.exc import OperationalError

from config import (
    LEGACY_WRITE_ENABLED,
    LEGACY_READ_FALLBACK_ENABLED,
    LONG_TERM_PROMOTE_MIN_SCORE,
    MEMORY_AUTO_STORE,
    MEMORY_FAILURE_STORE_MIN_CHARS,
    MEMORY_MAX_ITEMS,
    MEMORY_MIN_SCORE,
    MEMORY_STORE_ASSISTANT_TURNS,
    MEMORY_TOP_K,
    MEMORY_VECTOR_BACKEND,
    SHORT_TERM_CLEAR_ON_RESTART,
    SHORT_TERM_MAX_QUEUE_ITEMS,
    SHORT_TERM_MAX_RETRIEVAL_LOG_ITEMS,
    SHORT_TERM_RETENTION_HOURS,
    SHORT_TERM_TRACE_MAX_ITEMS,
)
from memory.db import create_engine_and_session
from memory.embedder import NvidiaEmbeddingService
from memory.pgvector_store import PgVectorStore
from memory.repository import MemoryRepository
from memory.vector_store import FaissVectorStore

logger = logging.getLogger(__name__)
LOW_QUALITY_QUEUE_SIGNALS = ("### task:", "<chat_history>", "json format:", "guidelines:", "follow_ups", "output:")
# Key tail: letters/digits/underscore/slash/space or hyphen (alternation avoids brittle char-class ranges).
_STRUCTURED_KV_KEY_TAIL = r"(?:[A-Za-z0-9_/ ]|-)"
_STRUCTURED_KV_LINE_RE = re.compile(
    rf"(?im)^\s*[A-Za-z](?:{_STRUCTURED_KV_KEY_TAIL}){{1,40}}\s*[:-]\s*[^\n]{{2,180}}\s*$"
)
_STRUCTURED_KV_CAPTURE_RE = re.compile(
    rf"(?im)^\s*([A-Za-z](?:{_STRUCTURED_KV_KEY_TAIL}){{1,40}})\s*[:-]\s*([^\n]{{2,180}})\s*$"
)

try:
    from pydantic import BaseModel, Field
    from langchain_core.runnables import RunnableLambda
except Exception:  # pragma: no cover - optional dependency path
    BaseModel = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    RunnableLambda = None  # type: ignore[assignment]


if BaseModel is not None:
    class TypedClassificationResult(BaseModel):
        should_store: bool = False
        importance_score: float = 0.0
        category: str = "general"
        structured_data: dict[str, str] = Field(default_factory=dict)


class MemoryService:
    def __init__(self):
        engine, session_factory = create_engine_and_session()
        self._engine = engine
        self.repo = MemoryRepository(session_factory)
        self.embedder = NvidiaEmbeddingService()
        self.vector = self._init_vector_store()
        self._typed_classification_chain = self._build_typed_classification_chain()
        self._boot_short_term_state()

    def _boot_short_term_state(self) -> None:
        try:
            if SHORT_TERM_CLEAR_ON_RESTART:
                self.repo.clear_short_term_memory()
                return
            self.repo.enforce_short_term_ttl_across_scopes(retention_hours=SHORT_TERM_RETENTION_HOURS)
            self._enforce_short_term_retention("global")
        except Exception:
            # Startup hygiene must never break process boot.
            return

    def _enforce_short_term_retention(self, memory_scope: str) -> None:
        try:
            self.repo.enforce_short_term_retention(
                memory_scope=memory_scope,
                retention_hours=SHORT_TERM_RETENTION_HOURS,
                max_traces=SHORT_TERM_TRACE_MAX_ITEMS,
                max_queue_items=SHORT_TERM_MAX_QUEUE_ITEMS,
                max_retrieval_logs=SHORT_TERM_MAX_RETRIEVAL_LOG_ITEMS,
            )
        except Exception:
            # Retention is best-effort and should not break chat flow.
            return

    @staticmethod
    def _is_missing_table_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "no such table" in text

    @staticmethod
    def _safe_metric_token(value: str) -> str:
        token = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower())
        token = re.sub(r"_+", "_", token).strip("_")
        return token or "unknown"

    def _record_embedding_observability(
        self,
        *,
        memory_scope: str,
        stage: str,
        meta: dict[str, object] | None,
    ) -> None:
        scope = (memory_scope or "global").strip() or "global"
        details = meta or {}
        provider = self._safe_metric_token(str(details.get("provider") or "unknown"))
        reason = self._safe_metric_token(str(details.get("reason") or "unknown"))
        stage_token = self._safe_metric_token(stage)
        try:
            self.repo.increment_short_runtime_metric(
                memory_scope=scope,
                metric_key=f"embedding.stage.{stage_token}.provider.{provider}",
                delta=1,
            )
            if provider == "fallback":
                self.repo.increment_short_runtime_metric(
                    memory_scope=scope,
                    metric_key="embedding.fallback.total",
                    delta=1,
                )
                self.repo.increment_short_runtime_metric(
                    memory_scope=scope,
                    metric_key=f"embedding.fallback.reason.{reason}",
                    delta=1,
                )
            if reason.startswith("http_"):
                self.repo.increment_short_runtime_metric(
                    memory_scope=scope,
                    metric_key=f"embedding.api_error.{reason}",
                    delta=1,
                )
        except Exception:
            return

    def _recover_schema_bindings(self) -> None:
        try:
            self.close()
        except Exception:
            pass
        engine, session_factory = create_engine_and_session()
        self._engine = engine
        self.repo = MemoryRepository(session_factory)
        self.vector = self._init_vector_store()

    def _init_vector_store(self):
        backend = (MEMORY_VECTOR_BACKEND or "faiss").strip().lower()
        if backend == "pgvector":
            try:
                return PgVectorStore(engine=self._engine, dim=self.embedder.dim)
            except Exception:
                return FaissVectorStore(dim=self.embedder.dim)
        return FaissVectorStore(dim=self.embedder.dim)

    def _build_typed_classification_chain(self):
        if RunnableLambda is None or BaseModel is None:
            return None

        def _normalize(text: str) -> str:
            return (text or "").strip()

        def _heuristic(text: str) -> dict[str, Any]:
            return self._heuristic_classify_memory_candidate(text)

        def _typed(payload: dict[str, Any]) -> dict[str, Any]:
            parsed = TypedClassificationResult(**(payload or {}))
            return self._normalize_classification_result(parsed.model_dump())

        return RunnableLambda(_normalize) | RunnableLambda(_heuristic) | RunnableLambda(_typed)

    def _normalize_classification_result(self, result: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(result or {})
        score = max(0.0, min(1.0, float(normalized.get("importance_score") or 0.0)))
        normalized["importance_score"] = score
        normalized["category"] = str(normalized.get("category") or "general").strip().lower() or "general"
        if not isinstance(normalized.get("structured_data"), dict):
            normalized["structured_data"] = {}
        typed_should_store = bool(normalized.get("should_store", False))
        # Align ingestion gate with long-term promotion threshold to avoid inconsistent behavior
        # from external classifiers returning should_store=True with very low scores.
        normalized["should_store"] = typed_should_store and score >= LONG_TERM_PROMOTE_MIN_SCORE
        return normalized

    def close(self) -> None:
        try:
            self.vector.flush()
        except Exception:
            pass
        try:
            self._engine.dispose()
        except Exception:
            # Best-effort cleanup for process shutdown/test teardown.
            pass
        try:
            self.embedder.close()
        except Exception:
            pass

    def add_memory(
        self,
        *,
        text: str,
        memory_scope: str = "global",
        source: str = "chat",
        importance: float = 0.5,
        confidence: float | None = None,
        category: str = "general",
        structured_data: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not text:
            return {"success": False, "error": "text cannot be empty"}
        if not LEGACY_WRITE_ENABLED:
            return self._add_memory_normalized_only(
                text=text,
                memory_scope=memory_scope,
                source=source,
                importance=importance,
                confidence=confidence,
                category=category,
                structured_data=structured_data,
            )

        # Exact dedupe on recent scope items.
        try:
            recent = self.repo.list(memory_scope=memory_scope, limit=50, offset=0)
        except OperationalError as exc:
            if _retry and self._is_missing_table_error(exc):
                self._recover_schema_bindings()
                return self.add_memory(
                    text=text,
                    memory_scope=memory_scope,
                    source=source,
                    importance=importance,
                    confidence=confidence,
                    category=category,
                    structured_data=structured_data,
                    _retry=False,
                )
            raise
        if any((r.text or "").strip().lower() == text.lower() for r in recent):
            return {"success": True, "deduped": True}

        try:
            row = self.repo.create(
                memory_scope=memory_scope,
                text=text,
                source=source,
                importance=importance,
                confidence=float(confidence if confidence is not None else importance),
                category=category,
                structured_data=json.dumps(structured_data or {}, ensure_ascii=True),
            )
        except OperationalError as exc:
            if _retry and self._is_missing_table_error(exc):
                self._recover_schema_bindings()
                return self.add_memory(
                    text=text,
                    memory_scope=memory_scope,
                    source=source,
                    importance=importance,
                    confidence=confidence,
                    category=category,
                    structured_data=structured_data,
                    _retry=False,
                )
            raise
        try:
            add_vec, add_meta = self.embedder.embed_with_meta(row.text)
            self._record_embedding_observability(
                memory_scope=row.memory_scope,
                stage="index_add",
                meta=add_meta,
            )
            self.vector.add(
                memory_id=row.id,
                memory_scope=row.memory_scope,
                embedding=add_vec,
            )
        except Exception:
            # Vector indexing should be best-effort; row is already persisted in SQL.
            pass

        self._prune_scope_if_needed(memory_scope)

        return {
            "success": True,
            "id": row.id,
            "memory_scope": row.memory_scope,
            "text": row.text,
            "source": row.source,
            "category": row.category,
            "structured_data": json.loads(row.structured_data or "{}"),
            "importance": row.importance,
            "confidence": row.confidence,
            "created_at": row.created_at.isoformat(),
        }

    def _add_memory_normalized_only(
        self,
        *,
        text: str,
        memory_scope: str,
        source: str,
        importance: float,
        confidence: float | None,
        category: str,
        structured_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        score = float(confidence if confidence is not None else importance)
        score = max(0.6, min(1.0, score))
        classification = {
            "should_store": True,
            "importance_score": score,
            "category": (category or "general").strip().lower() or "general",
            "structured_data": structured_data or {},
        }
        promoted = self._promote_user_fact_to_long_term(
            memory_scope=memory_scope,
            text=text,
            classification=classification,
        )
        if not promoted:
            return {"success": False, "error": "normalized write failed"}
        synthetic_id = hashlib.sha256(
            f"{memory_scope}|{classification['category']}|{text}".encode("utf-8")
        ).hexdigest()
        return {
            "success": True,
            "id": synthetic_id,
            "memory_scope": memory_scope,
            "text": text,
            "source": str(source or "normalized"),
            "category": classification["category"],
            "structured_data": classification["structured_data"],
            "importance": score,
            "confidence": score,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def search(
        self,
        *,
        query: str,
        memory_scope: str = "global",
        limit: int | None = None,
        source_filter: str | None = None,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not query:
            return []
        top_k = max(1, int(limit or MEMORY_TOP_K))
        normalized_source = (source_filter or "").strip().lower()
        normalized_category = (category_filter or "").strip().lower()
        normalized_first: list[dict[str, Any]] = []
        if not normalized_source or normalized_source in {"long_term", "long_term_attribute", "normalized"}:
            slot_items = self.list_long_term_slot_facts(
                query=query,
                memory_scope=memory_scope,
                limit=top_k,
            )
            for item in slot_items:
                if normalized_category and str(item.get("category") or "").strip().lower() != normalized_category:
                    continue
                normalized_first.append(item)
            for item in self.repo.search_long_text_fts(memory_scope=memory_scope, query=query, limit=top_k):
                text = str(item.get("attributes_text") or "").strip()
                if not text:
                    text = str(item.get("description") or "").strip() or str(item.get("canonical_name") or "").strip()
                if not text:
                    continue
                normalized_first.append(
                    {
                        "id": str(item.get("entity_id") or ""),
                        "text": text,
                        "score": 1.0 / (1.0 + max(0.0, float(item.get("rank") or 0.0))),
                        "source": "long_term_attribute",
                        "category": "profile",
                        "structured_data": {
                            "entity_id": item.get("entity_id"),
                            "canonical_name": item.get("canonical_name"),
                        },
                        "importance": 0.9,
                        "confidence": 0.9,
                        "created_at": (
                            item.get("updated_at").isoformat()
                            if hasattr(item.get("updated_at"), "isoformat")
                            else str(item.get("updated_at") or "")
                        ),
                    }
                )
        if normalized_first:
            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in normalized_first:
                key = f"{item.get('id')}|{str(item.get('text') or '').strip().lower()}"
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
                if len(deduped) >= top_k:
                    break
            if deduped:
                return deduped
        if not LEGACY_READ_FALLBACK_ENABLED:
            return []
        query_vec, query_meta = self.embedder.embed_with_meta(query)
        self._record_embedding_observability(
            memory_scope=memory_scope,
            stage="search",
            meta=query_meta,
        )
        candidates = self.vector.search(
            memory_scope=memory_scope,
            embedding=query_vec,
            top_k=top_k,
        )
        results: list[dict[str, Any]] = []
        for item in candidates:
            if item["score"] < MEMORY_MIN_SCORE:
                continue
            row = self.repo.get(item["id"])
            if not row:
                continue
            if normalized_source and (row.source or "").strip().lower() != normalized_source:
                continue
            if normalized_category and (row.category or "").strip().lower() != normalized_category:
                continue
            results.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": item["score"],
                    "source": row.source,
                    "category": row.category,
                    "structured_data": json.loads(row.structured_data or "{}"),
                    "importance": row.importance,
                    "confidence": row.confidence,
                    "created_at": row.created_at.isoformat(),
                }
            )
        if results:
            return results

        # Fallback lexical retrieval via SQLite FTS5 (fast indexed text search).
        fts_items = self.repo.search_text_fts(memory_scope=memory_scope, query=query, limit=top_k)
        if fts_items:
            return [
                {
                    "id": item["id"],
                    "text": item["text"],
                    # Convert lower bm25 rank to a higher-is-better score.
                    "score": 1.0 / (1.0 + max(0.0, item["rank"])),
                    "source": item["source"],
                    "category": "general",
                    "structured_data": {},
                    "importance": item["importance"],
                    "confidence": item["importance"],
                    "created_at": item["created_at"].isoformat() if hasattr(item["created_at"], "isoformat") else str(item["created_at"]),
                }
                for item in fts_items
            ]

        # Final fallback if FTS is unavailable.
        query_terms = {t for t in query.lower().split() if t}
        lexical: list[dict[str, Any]] = []
        for row in self.repo.list(memory_scope=memory_scope, limit=500, offset=0):
            if normalized_source and (row.source or "").strip().lower() != normalized_source:
                continue
            if normalized_category and (row.category or "").strip().lower() != normalized_category:
                continue
            terms = {t for t in (row.text or "").lower().split() if t}
            overlap = len(query_terms.intersection(terms))
            if overlap <= 0:
                continue
            lexical.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": float(overlap),
                    "source": row.source,
                    "category": row.category,
                    "structured_data": json.loads(row.structured_data or "{}"),
                    "importance": row.importance,
                    "confidence": row.confidence,
                    "created_at": row.created_at.isoformat(),
                }
            )
        lexical.sort(key=lambda x: x["score"], reverse=True)
        return lexical[:top_k]

    def search_legacy_only(
        self,
        *,
        query: str,
        memory_scope: str = "global",
        limit: int | None = None,
        source_filter: str | None = None,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not query:
            return []
        top_k = max(1, int(limit or MEMORY_TOP_K))
        normalized_source = (source_filter or "").strip().lower()
        normalized_category = (category_filter or "").strip().lower()
        query_vec, query_meta = self.embedder.embed_with_meta(query)
        self._record_embedding_observability(
            memory_scope=memory_scope,
            stage="legacy_search",
            meta=query_meta,
        )
        candidates = self.vector.search(
            memory_scope=memory_scope,
            embedding=query_vec,
            top_k=top_k,
        )
        results: list[dict[str, Any]] = []
        for item in candidates:
            if item["score"] < MEMORY_MIN_SCORE:
                continue
            row = self.repo.get(item["id"])
            if not row:
                continue
            if normalized_source and (row.source or "").strip().lower() != normalized_source:
                continue
            if normalized_category and (row.category or "").strip().lower() != normalized_category:
                continue
            results.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": item["score"],
                    "source": row.source,
                    "category": row.category,
                    "structured_data": json.loads(row.structured_data or "{}"),
                    "importance": row.importance,
                    "confidence": row.confidence,
                    "created_at": row.created_at.isoformat(),
                }
            )
        if results:
            return results

        fts_items = self.repo.search_text_fts(memory_scope=memory_scope, query=query, limit=top_k)
        if fts_items:
            return [
                {
                    "id": item["id"],
                    "text": item["text"],
                    "score": 1.0 / (1.0 + max(0.0, item["rank"])),
                    "source": item["source"],
                    "category": "general",
                    "structured_data": {},
                    "importance": item["importance"],
                    "confidence": item["importance"],
                    "created_at": item["created_at"].isoformat() if hasattr(item["created_at"], "isoformat") else str(item["created_at"]),
                }
                for item in fts_items
            ]

        query_terms = {t for t in query.lower().split() if t}
        lexical: list[dict[str, Any]] = []
        for row in self.repo.list(memory_scope=memory_scope, limit=500, offset=0):
            if normalized_source and (row.source or "").strip().lower() != normalized_source:
                continue
            if normalized_category and (row.category or "").strip().lower() != normalized_category:
                continue
            terms = {t for t in (row.text or "").lower().split() if t}
            overlap = len(query_terms.intersection(terms))
            if overlap <= 0:
                continue
            lexical.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": float(overlap),
                    "source": row.source,
                    "category": row.category,
                    "structured_data": json.loads(row.structured_data or "{}"),
                    "importance": row.importance,
                    "confidence": row.confidence,
                    "created_at": row.created_at.isoformat(),
                }
            )
        lexical.sort(key=lambda x: x["score"], reverse=True)
        return lexical[:top_k]

    def list_items(self, *, memory_scope: str = "global", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        normalized_items = self._list_profile_items_from_long(
            memory_scope=memory_scope,
            limit=max(1, limit),
        )
        if normalized_items:
            if offset > 0:
                return normalized_items[offset : offset + max(1, limit)]
            return normalized_items[: max(1, limit)]
        if not LEGACY_READ_FALLBACK_ENABLED:
            return []
        rows = self.repo.list(memory_scope=memory_scope, limit=limit, offset=offset)
        return [
            {
                "id": r.id,
                "memory_scope": r.memory_scope,
                "text": r.text,
                "source": r.source,
                "category": r.category,
                "structured_data": json.loads(r.structured_data or "{}"),
                "importance": r.importance,
                "confidence": r.confidence,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    @staticmethod
    def _legacy_row_to_memory_item(r) -> dict[str, Any]:
        return {
            "id": r.id,
            "memory_scope": r.memory_scope,
            "text": r.text,
            "source": r.source,
            "category": r.category,
            "structured_data": json.loads(r.structured_data or "{}"),
            "importance": r.importance,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }

    def _list_profile_items_from_long(self, *, memory_scope: str, limit: int) -> list[dict[str, Any]]:
        keys = [
            "name",
            "full_name",
            "email",
            "phone",
            "mobile",
            "location",
            "education",
            "university",
            "experience",
            "skills",
            "website",
            "company",
            "role",
            "hobby",
            "favorite",
            "profession",
            "occupation",
        ]
        rows = self.repo.list_long_attributes_by_keys(
            memory_scope=memory_scope,
            attribute_keys=keys,
            limit=max(1, limit * 4),
        )
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("attribute_key") or "").strip().lower()
            value = str(row.get("attribute_value") or "").strip()
            if not key or not value:
                continue
            dedupe = f"{key}:{value.lower()}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            updated = row.get("updated_at") or row.get("created_at")
            items.append(
                {
                    "id": str(row.get("id") or ""),
                    "memory_scope": memory_scope,
                    "text": f"{key}: {value}",
                    "source": "long_term_attribute",
                    "category": str(row.get("entity_type") or "profile"),
                    "structured_data": {
                        "entity_id": row.get("entity_id"),
                        "entity_name": row.get("canonical_name"),
                        "attribute_key": key,
                    },
                    "importance": float(row.get("importance_score") or 0.0),
                    "confidence": float(row.get("confidence_score") or 0.0),
                    "created_at": (
                        updated.isoformat()
                        if hasattr(updated, "isoformat")
                        else str(updated or "")
                    ),
                }
            )
            if len(items) >= max(1, limit):
                break
        return items

    def _list_profile_items_from_long_any_scope(self, *, limit: int) -> list[dict[str, Any]]:
        keys = [
            "name",
            "full_name",
            "email",
            "phone",
            "mobile",
            "location",
            "education",
            "university",
            "experience",
            "skills",
            "website",
            "company",
            "role",
            "hobby",
            "favorite",
            "profession",
            "occupation",
        ]
        rows = self.repo.list_long_attributes_by_keys_any_scope(
            attribute_keys=keys,
            limit=max(1, limit * 4),
        )
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("attribute_key") or "").strip().lower()
            value = str(row.get("attribute_value") or "").strip()
            scope = str(row.get("memory_scope") or "global").strip() or "global"
            if not key or not value:
                continue
            dedupe = f"{scope}|{key}:{value.lower()}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            updated = row.get("updated_at") or row.get("created_at")
            items.append(
                {
                    "id": str(row.get("id") or ""),
                    "memory_scope": scope,
                    "text": f"{key}: {value}",
                    "source": "long_term_attribute",
                    "category": str(row.get("entity_type") or "profile"),
                    "structured_data": {
                        "entity_id": row.get("entity_id"),
                        "entity_name": row.get("canonical_name"),
                        "attribute_key": key,
                    },
                    "importance": float(row.get("importance_score") or 0.0),
                    "confidence": float(row.get("confidence_score") or 0.0),
                    "created_at": (
                        updated.isoformat()
                        if hasattr(updated, "isoformat")
                        else str(updated or "")
                    ),
                }
            )
            if len(items) >= max(1, limit):
                break
        return items

    @staticmethod
    def _build_retrieval_observability(items: list[dict[str, Any]]) -> dict[str, Any]:
        source_counts: dict[str, int] = {}
        bucket_counts = {
            "short_term": 0,
            "long_term": 0,
            "vector_primary": 0,
            "lexical": 0,
            "unknown": 0,
        }
        for item in items:
            source = str(item.get("source") or "").strip().lower() or "unknown"
            source_counts[source] = int(source_counts.get(source, 0)) + 1
            if source in {"short_trace", "short_trace_context"}:
                bucket_counts["short_term"] += 1
            elif source == "long_term_attribute":
                bucket_counts["long_term"] += 1
            elif source in {"chat_user", "chat_assistant", "profile_fact", "profile_full", "manual"}:
                bucket_counts["vector_primary"] += 1
            elif source in {"lexical", "fts"}:
                bucket_counts["lexical"] += 1
            else:
                bucket_counts["unknown"] += 1
        has_short = bucket_counts["short_term"] > 0
        has_long = bucket_counts["long_term"] > 0
        has_vector_primary = bucket_counts["vector_primary"] > 0
        has_lexical = bucket_counts["lexical"] > 0
        method = "none"
        if has_short or has_long:
            method = "structured"
            if has_vector_primary or has_lexical:
                method = "hybrid"
        elif has_vector_primary and has_lexical:
            method = "hybrid"
        elif has_vector_primary:
            method = "vector"
        elif has_lexical:
            method = "fts"
        top_source = str(items[0].get("source") or "none").strip().lower() if items else "none"
        top_bucket = "none"
        if items:
            if top_source in {"short_trace", "short_trace_context"}:
                top_bucket = "short_term"
            elif top_source == "long_term_attribute":
                top_bucket = "long_term"
            elif top_source in {"chat_user", "chat_assistant", "profile_fact", "profile_full", "manual"}:
                top_bucket = "vector_primary"
            elif top_source in {"lexical", "fts"}:
                top_bucket = "lexical"
            else:
                top_bucket = "unknown"
        return {
            "method": method,
            "source_counts": source_counts,
            "bucket_counts": bucket_counts,
            "top_source": top_source,
            "top_bucket": top_bucket,
        }

    @staticmethod
    def _extract_key_values_from_text(text: str) -> list[tuple[str, str]]:
        raw = (text or "").strip()
        if not raw:
            return []
        pairs: list[tuple[str, str]] = []
        for line in raw.splitlines():
            ln = line.strip()
            if not ln or ":" not in ln:
                continue
            key, value = ln.split(":", 1)
            k = key.strip().lower()
            v = value.strip()
            if not k or not v:
                continue
            pairs.append((k, v))
        return pairs

    @staticmethod
    def _canonical_metric_key(key: str) -> str:
        raw = (key or "").strip().lower()
        if not raw:
            return ""
        alias_map = {
            "full_name": "name",
            "current_role": "role",
            "job_title": "role",
            "designation": "role",
            "city": "location",
            "address": "location",
            "mobile_number": "mobile",
            "phone_number": "phone",
            "email_address": "email",
            "profession": "occupation",
        }
        return alias_map.get(raw, raw)

    def _legacy_vs_long_mismatch(self, *, memory_scope: str) -> dict[str, Any]:
        scope = (memory_scope or "global").strip() or "global"
        target_keys = [
            "name",
            "full_name",
            "email",
            "email_address",
            "phone",
            "phone_number",
            "mobile",
            "mobile_number",
            "location",
            "city",
            "address",
            "education",
            "university",
            "experience",
            "skills",
            "website",
            "company",
            "role",
            "current_role",
            "job_title",
            "designation",
            "hobby",
            "favorite",
            "profession",
            "occupation",
        ]
        long_rows = self.repo.list_long_attributes_by_keys(
            memory_scope=scope,
            attribute_keys=target_keys,
            limit=300,
        )
        legacy_rows = self.repo.list_by_sources(
            memory_scope=scope,
            sources=["profile_fact", "profile_full", "chat_user", "manual"],
            limit=300,
            offset=0,
        )

        long_values: dict[str, set[str]] = {}
        for row in long_rows:
            key = self._canonical_metric_key(str(row.get("attribute_key") or ""))
            value = str(row.get("attribute_value") or "").strip().lower()
            if not key or not value:
                continue
            long_values.setdefault(key, set()).add(value)

        legacy_values: dict[str, set[str]] = {}
        for row in legacy_rows:
            for key, value in self._extract_key_values_from_text(str(row.text or "")):
                k = self._canonical_metric_key(key)
                v = value.strip().lower()
                if not k or not v:
                    continue
                legacy_values.setdefault(k, set()).add(v)

        per_key: dict[str, dict[str, Any]] = {}
        mismatch_count = 0
        duplicate_keys_count = 0
        duplicate_value_pairs_count = 0
        all_keys = sorted(set(long_values.keys()).intersection(set(legacy_values.keys())))
        for key in all_keys:
            long_set = long_values.get(key, set())
            legacy_set = legacy_values.get(key, set())
            mismatch = long_set != legacy_set
            overlap_values = sorted(long_set.intersection(legacy_set))
            if mismatch:
                mismatch_count += 1
            if overlap_values:
                duplicate_keys_count += 1
                duplicate_value_pairs_count += len(overlap_values)
            per_key[key] = {
                "mismatch": mismatch,
                "long_values": sorted(long_set),
                "legacy_values": sorted(legacy_set),
                "overlap_values": overlap_values,
            }
        long_keys = set(long_values.keys())
        legacy_keys = set(legacy_values.keys())
        return {
            "scope": scope,
            "mismatch_keys_count": mismatch_count,
            "duplicate_keys_count": duplicate_keys_count,
            "duplicate_value_pairs_count": duplicate_value_pairs_count,
            "coverage": {
                "long_keys_count": len(long_keys),
                "legacy_keys_count": len(legacy_keys),
                "shared_keys_count": len(all_keys),
                "long_only_keys_count": len(long_keys.difference(legacy_keys)),
                "legacy_only_keys_count": len(legacy_keys.difference(long_keys)),
            },
            "source_of_truth_risk": bool(duplicate_keys_count > 0),
            "per_key": per_key,
        }

    def list_profile_facts(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        long_items = self._list_profile_items_from_long(
            memory_scope=memory_scope,
            limit=max(1, limit),
        )
        if long_items:
            return long_items
        if not LEGACY_READ_FALLBACK_ENABLED:
            return []
        rows = self.repo.list_by_sources(
            memory_scope=memory_scope,
            sources=["profile_fact"],
            limit=max(1, limit),
            offset=0,
        )
        return [self._legacy_row_to_memory_item(r) for r in rows]

    def list_profile_memories(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        long_items = self._list_profile_items_from_long(
            memory_scope=memory_scope,
            limit=max(1, limit),
        )
        if not LEGACY_READ_FALLBACK_ENABLED:
            return long_items[: max(1, limit)]
        rows = self.repo.list_by_sources(
            memory_scope=memory_scope,
            sources=["profile_fact", "profile_full"],
            limit=max(1, limit),
            offset=0,
        )
        legacy_items = [self._legacy_row_to_memory_item(r) for r in rows]
        if not long_items:
            return legacy_items
        # Keep long_* as source of truth while preserving useful legacy profile
        # rows (profile_fact/profile_full) for backward compatibility.
        legacy_profile_items = [
            item
            for item in legacy_items
            if str(item.get("source") or "").strip().lower() in {"profile_fact", "profile_full"}
        ]
        merged = long_items + legacy_profile_items
        return merged[: max(1, limit)]

    def list_profile_facts_any_scope(self, *, limit: int = 20) -> list[dict[str, Any]]:
        long_items = self._list_profile_items_from_long_any_scope(
            limit=max(1, limit),
        )
        if long_items:
            return long_items
        if not LEGACY_READ_FALLBACK_ENABLED:
            return []
        rows = self.repo.list_all_by_sources(sources=["profile_fact"], limit=max(1, limit), offset=0)
        facts = []
        for r in rows:
            facts.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "category": r.category,
                    "structured_data": json.loads(r.structured_data or "{}"),
                    "importance": r.importance,
                    "confidence": r.confidence,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return facts

    def list_profile_memories_any_scope(self, *, limit: int = 200) -> list[dict[str, Any]]:
        long_items = self._list_profile_items_from_long_any_scope(
            limit=max(1, limit),
        )
        if long_items:
            return long_items
        if not LEGACY_READ_FALLBACK_ENABLED:
            return []
        rows = self.repo.list_all_by_sources(
            sources=["profile_fact", "profile_full", "chat_user", "chat_assistant", "manual"],
            limit=max(1, limit),
            offset=0,
        )
        items = []
        for r in rows:
            items.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "category": r.category,
                    "structured_data": json.loads(r.structured_data or "{}"),
                    "importance": r.importance,
                    "confidence": r.confidence,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return items

    def latest_profile_full(self, *, memory_scope: str = "global") -> dict[str, Any] | None:
        r = self.repo.latest_by_source(memory_scope=memory_scope, source="profile_full")
        if not r:
            return None
        return {
            "id": r.id,
            "memory_scope": r.memory_scope,
            "text": r.text,
            "source": r.source,
            "category": r.category,
            "structured_data": json.loads(r.structured_data or "{}"),
            "importance": r.importance,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }

    def latest_profile_full_any_scope(self) -> dict[str, Any] | None:
        r = self.repo.latest_by_source_any_scope(source="profile_full")
        if not r:
            return None
        return {
            "id": r.id,
            "memory_scope": r.memory_scope,
            "text": r.text,
            "source": r.source,
            "category": r.category,
            "structured_data": json.loads(r.structured_data or "{}"),
            "importance": r.importance,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }

    def estimate_response_confidence(self, *, response_text: str, retrieved_count: int, had_error: bool = False) -> float:
        text = (response_text or "").strip().lower()
        score = 0.55
        if retrieved_count > 0:
            score += 0.20
        if had_error:
            score -= 0.25
        uncertainty_markers = (
            "i don't have enough data",
            "i do not have enough data",
            "i'm not sure",
            "i am not sure",
            "i don't know",
            "i do not know",
            "not fully verified",
        )
        if any(marker in text for marker in uncertainty_markers):
            score -= 0.20
        if len(text) >= 40:
            score += 0.05
        return max(0.0, min(1.0, score))

    def log_chat_trace(
        self,
        *,
        request_id: str,
        memory_scope: str,
        user_text: str,
        assistant_text: str,
        model: str,
        retrieved_items: list[dict[str, Any]] | None = None,
        had_error: bool = False,
    ) -> None:
        normalized_user = (user_text or "").strip()
        normalized_assistant = (assistant_text or "").strip()
        if not normalized_user and not normalized_assistant:
            return
        retrieved_items = retrieved_items or []
        retrieval_summary = {
            "retrieved_count": len(retrieved_items),
            "retrieved_ids": [str(item.get("id") or "") for item in retrieved_items if item.get("id")],
            "top_score": float(retrieved_items[0].get("score") or 0.0) if retrieved_items else 0.0,
        }
        confidence = self.estimate_response_confidence(
            response_text=normalized_assistant,
            retrieved_count=len(retrieved_items),
            had_error=had_error,
        )
        try:
            retrieval_obs = self._build_retrieval_observability(retrieved_items)
            retrieval_method = str(retrieval_obs.get("method") or "none")
            self.repo.create_chat_trace(
                request_id=request_id,
                memory_scope=memory_scope,
                user_text=normalized_user,
                assistant_text=normalized_assistant,
                model=model,
                confidence=confidence,
                retrieval_summary=json.dumps(retrieval_summary, ensure_ascii=True),
            )
            try:
                self.repo.create_short_trace(
                    trace_id=request_id,
                    memory_scope=memory_scope,
                    user_message=normalized_user,
                    assistant_response=normalized_assistant,
                    model_used=model,
                    retrieved_memory_ids=retrieval_summary["retrieved_ids"],
                    retrieval_method=retrieval_method,
                    confidence_score=confidence,
                    latency_ms=0,
                )
                self.repo.prune_short_traces(memory_scope=memory_scope, keep_latest=SHORT_TERM_TRACE_MAX_ITEMS)
                self._enforce_short_term_retention(memory_scope)
            except Exception:
                # New short_* path should not break legacy path.
                pass
            self.repo.prune_chat_traces(memory_scope=memory_scope, keep_latest=SHORT_TERM_TRACE_MAX_ITEMS)
        except OperationalError as exc:
            if self._is_missing_table_error(exc):
                self._recover_schema_bindings()
                return
            return
        except Exception:
            # Trace logging must not break user responses.
            return

    def log_retrieval_decision(
        self,
        *,
        trace_id: str,
        memory_scope: str,
        query_text: str,
        retrieved_items: list[dict[str, Any]] | None = None,
        method_used: str = "vector",
    ) -> None:
        query = (query_text or "").strip()
        if not query:
            return
        items = retrieved_items or []
        scores = [float(item.get("score") or 0.0) for item in items]
        score_distribution = {
            "count": len(scores),
            "max": max(scores) if scores else 0.0,
            "min": min(scores) if scores else 0.0,
            "avg": (sum(scores) / len(scores)) if scores else 0.0,
        }
        retrieval_obs = self._build_retrieval_observability(items)
        score_distribution["source_counts"] = retrieval_obs["source_counts"]
        score_distribution["bucket_counts"] = retrieval_obs["bucket_counts"]
        score_distribution["top_source"] = retrieval_obs["top_source"]
        score_distribution["top_bucket"] = retrieval_obs["top_bucket"]
        confidence = max(0.0, min(1.0, score_distribution["max"]))
        normalized_method = (method_used or "").strip().lower()
        if normalized_method not in {"vector", "fts", "structured", "hybrid"}:
            normalized_method = str(retrieval_obs.get("method") or "structured")
            if normalized_method == "none":
                normalized_method = "structured"
        try:
            self.repo.create_short_retrieval_log(
                trace_id=trace_id,
                memory_scope=memory_scope,
                query_text=query,
                retrieved_ids=[str(item.get("id") or "") for item in items if item.get("id")],
                method_used=normalized_method,
                score_distribution=score_distribution,
                confidence_score=confidence,
            )
            self._enforce_short_term_retention(memory_scope)
        except OperationalError as exc:
            if self._is_missing_table_error(exc):
                self._recover_schema_bindings()
                return
            return
        except Exception:
            # Retrieval logging must not affect user path.
            return

    def delete_item(self, *, item_id: str, memory_scope: str = "global") -> dict[str, Any]:
        ok = self.repo.delete(memory_id=item_id, memory_scope=memory_scope)
        if not ok:
            return {"success": False, "error": "memory not found"}
        self.reindex(memory_scope=memory_scope)
        return {"success": True, "id": item_id}

    def reindex(self, *, memory_scope: str = "global") -> dict[str, Any]:
        rows = self.repo.list(memory_scope=memory_scope, limit=100000, offset=0)
        payload = [{"id": r.id, "memory_scope": r.memory_scope, "text": r.text} for r in rows]
        self.vector.rebuild(rows=payload, embed_fn=self.embedder.embed)
        return {"success": True, "count": len(rows), "memory_scope": memory_scope}

    @staticmethod
    def _record_memory_filter_decision(*, memory_scope: str, decision: str) -> None:
        try:
            from gateway.memory_metrics import memory_metrics

            memory_metrics.record_memory_filter_decision(memory_scope=memory_scope, decision=decision)
        except Exception:
            return

    def should_store_memory_text(self, text: str, *, strict: bool = False) -> bool:
        t = (text or "").strip()
        if len(t) < (MEMORY_FAILURE_STORE_MIN_CHARS if strict else 8):
            return False
        if t.endswith("?") or t.endswith("؟"):
            return False
        lowered = t.lower()
        if re.match(r"^\s*(what|who|where|when|why|how|can|should|do|does|did|is|are|am|tell me)\b", lowered):
            return False
        if any(sig in lowered for sig in LOW_QUALITY_QUEUE_SIGNALS):
            return False
        if len(t) > 800 and not self._looks_like_structured_text(t):
            return False
        return True

    def maybe_store_from_user_turn(self, *, text: str, memory_scope: str = "global") -> bool:
        if not MEMORY_AUTO_STORE:
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_auto_store_disabled")
            logger.debug("structured_store_decision scope=%s reason=auto_store_disabled", memory_scope)
            return False
        t = (text or "").strip()
        if not self.should_store_memory_text(t):
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_text_filter_reject")
            logger.debug("structured_store_decision scope=%s reason=text_too_short text_len=%s", memory_scope, len(t))
            return False
        queue_id, classification = self._enqueue_short_memory_candidate(text=t, memory_scope=memory_scope)
        structured_like = self._looks_like_structured_text(t)
        # Structured documents should bypass low-quality conversational guards
        # (e.g. "Output:" headings in CV/project sections).
        if structured_like:
            try:
                self._store_structured_facts(t, memory_scope=memory_scope)
                self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="processed")
                self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_store_structured")
                logger.debug(
                    "structured_store_success scope=%s text_len=%s mode=full_and_facts",
                    memory_scope,
                    len(t),
                )
                return True
            except Exception as exc:
                logger.warning(
                    "structured_store_primary_failed scope=%s text_len=%s error=%s",
                    memory_scope,
                    len(t),
                    exc,
                )
                # Last-resort durability path: keep full profile text even if
                # structured extraction/promotion fails partway through.
                try:
                    self._store_full_profile_text(t, memory_scope=memory_scope)
                    self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="processed")
                    self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_store_structured_fallback")
                    logger.info(
                        "structured_store_fallback_success scope=%s text_len=%s mode=profile_full_only",
                        memory_scope,
                        len(t),
                    )
                    return True
                except Exception as fallback_exc:
                    logger.error(
                        "structured_store_fallback_failed scope=%s text_len=%s error=%s",
                        memory_scope,
                        len(t),
                        fallback_exc,
                    )
                    self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="rejected")
                    self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_store_structured_failed")
                    return False
        if not self.should_store_memory_text(t):
            self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="rejected")
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_text_filter_reject")
            logger.debug("structured_store_decision scope=%s reason=memory_text_filter text_len=%s", memory_scope, len(t))
            return False
        if not classification["should_store"]:
            self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="rejected")
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_classifier_reject")
            logger.debug(
                "structured_store_decision scope=%s reason=classifier_reject text_len=%s importance=%s category=%s",
                memory_scope,
                len(t),
                float(classification.get("importance_score") or 0.0),
                str(classification.get("category") or ""),
            )
            return False
        promoted = self._promote_user_fact_to_long_term(
            memory_scope=memory_scope,
            text=t,
            classification=classification,
        )
        if promoted:
            self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="processed")
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_store_promoted")
            logger.debug("structured_store_decision scope=%s reason=promoted_non_structured text_len=%s", memory_scope, len(t))
            return True
        self._finalize_short_memory_queue_item(queue_id=queue_id, extraction_status="rejected")
        self._record_memory_filter_decision(memory_scope=memory_scope, decision="user_promote_failed")
        logger.debug("structured_store_decision scope=%s reason=promote_failed_non_structured text_len=%s", memory_scope, len(t))
        return False

    def _enqueue_short_memory_candidate(self, *, text: str, memory_scope: str) -> tuple[str | None, dict[str, Any]]:
        raw = (text or "").strip()
        if not raw:
            return None, {"should_store": False, "importance_score": 0.0, "category": "general", "structured_data": {}}
        classification = self.classify_memory_candidate(raw)
        fingerprint = hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()
        try:
            queue_id = self.repo.create_short_memory_queue_item(
                trace_id=str(uuid4()),
                memory_scope=memory_scope,
                raw_content=raw,
                extraction_status="pending",
                importance_score=float(classification.get("importance_score") or 0.0),
                confidence_score=float(classification.get("importance_score") or 0.0),
                dedupe_fingerprint=fingerprint,
            )
            self._enforce_short_term_retention(memory_scope)
            return queue_id, classification
        except Exception:
            # Queue staging should never block chat path.
            return None, classification

    def _finalize_short_memory_queue_item(self, *, queue_id: str | None, extraction_status: str) -> None:
        target_id = (queue_id or "").strip()
        if not target_id:
            return
        try:
            self.repo.mark_short_memory_queue_item(
                queue_id=target_id,
                extraction_status=extraction_status,
            )
        except Exception:
            # Queue finalization is observability; it must never break chat path.
            return

    def _promote_user_fact_to_long_term(
        self,
        *,
        memory_scope: str,
        text: str,
        classification: dict[str, Any],
    ) -> bool:
        score = max(0.0, min(1.0, float(classification.get("importance_score") or 0.0)))
        if score < LONG_TERM_PROMOTE_MIN_SCORE:
            return False
        raw = (text or "").strip()
        if not raw:
            return False
        structured = classification.get("structured_data") or {}
        if not isinstance(structured, dict):
            structured = {}
        inferred_name = self._extract_name_from_self_statement(raw)
        if inferred_name and not str(structured.get("name") or "").strip():
            structured["name"] = inferred_name
        category = (classification.get("category") or "fact").strip().lower() or "fact"
        canonical_name = str(structured.get("name") or structured.get("full_name") or "").strip() or raw[:80]
        self_identity = self._is_self_identity_fact(raw, structured)
        if self_identity:
            category = "person"
            dedupe_base = f"{memory_scope}|person|self"
            if not canonical_name or canonical_name == raw[:80]:
                canonical_name = "self"
        else:
            dedupe_base = f"{memory_scope}|{category}|{canonical_name.lower()}"
        dedupe_key = hashlib.sha256(dedupe_base.encode("utf-8")).hexdigest()
        attributes_pairs: list[tuple[str, str]] = []
        for key, value in structured.items():
            k = str(key or "").strip().lower()
            v = str(value or "").strip()
            if k and v:
                attributes_pairs.append((k, v))
        if not attributes_pairs:
            attributes_pairs.append(("raw_text", raw))
        try:
            entity_id = self.repo.upsert_long_entity(
                memory_scope=memory_scope,
                entity_type=category,
                canonical_name=canonical_name,
                description=raw[:500],
                importance_score=score,
                confidence_score=score,
                dedupe_key=dedupe_key,
                source_trace_id=None,
            )
            for key, value in attributes_pairs:
                self.repo.upsert_long_attribute(
                    entity_id=entity_id,
                    attribute_key=key,
                    attribute_value=value,
                    value_type="string",
                    confidence_score=score,
                )
            attributes_text = " ".join(f"{k}: {v}" for k, v in attributes_pairs)
            self.repo.upsert_long_memory_fts_source(
                entity_id=entity_id,
                memory_scope=memory_scope,
                canonical_name=canonical_name,
                description=raw[:500],
                attributes_text=attributes_text,
            )
            try:
                embedding, emb_meta = self.embedder.embed_with_meta(raw[:1200])
                self._record_embedding_observability(
                    memory_scope=memory_scope,
                    stage="long_term_promotion",
                    meta=emb_meta,
                )
                self.repo.upsert_long_embedding(
                    entity_id=entity_id,
                    model_name="nvidia/nv-embedqa-e5-v5",
                    embedding_ref=json.dumps(
                        {
                            "kind": "inline-json",
                            "dim": len(embedding),
                            "vector": embedding,
                        },
                        ensure_ascii=True,
                    ),
                    confidence_score=score,
                )
            except Exception:
                # Embeddings are best-effort during promotion.
                pass
            # Basic relationship extraction:
            # person -> location / person -> preference / person -> work
            if category == "person" or bool(str(structured.get("name") or "").strip()):
                rel_values: dict[str, str] = {}
                for key in ("location", "favorite", "hobby", "company", "role"):
                    value = str(structured.get(key) or "").strip()
                    if value:
                        rel_values[key] = value
                # Support inline "key: value; key: value" payloads.
                for match in re.finditer(
                    r"(?i)\b(location|favorite|hobby|company|role)\s*[:=-]\s*([^;,\n]{2,120})",
                    raw,
                ):
                    rel_key = str(match.group(1) or "").strip().lower()
                    rel_value = str(match.group(2) or "").strip(" .;,\t")
                    if rel_key and rel_value:
                        rel_values[rel_key] = rel_value
                for rel_key, rel_type, rel_entity_type in (
                    ("location", "lives_in", "location"),
                    ("favorite", "prefers", "preference"),
                    ("hobby", "has_hobby", "skill"),
                    ("company", "works_at", "organization"),
                    ("role", "has_role", "role"),
                ):
                    rel_value = str(rel_values.get(rel_key) or "").strip()
                    if not rel_value:
                        continue
                    rel_dedupe = hashlib.sha256(
                        f"{memory_scope}|{rel_entity_type}|{rel_value.lower()}".encode("utf-8")
                    ).hexdigest()
                    to_entity_id = self.repo.upsert_long_entity(
                        memory_scope=memory_scope,
                        entity_type=rel_entity_type,
                        canonical_name=rel_value,
                        description=rel_value,
                        importance_score=score,
                        confidence_score=score,
                        dedupe_key=rel_dedupe,
                        source_trace_id=None,
                    )
                    self.repo.upsert_long_attribute(
                        entity_id=to_entity_id,
                        attribute_key="label",
                        attribute_value=rel_value,
                        value_type="string",
                        confidence_score=score,
                    )
                    self.repo.upsert_long_relationship(
                        from_entity_id=entity_id,
                        to_entity_id=to_entity_id,
                        relation_type=rel_type,
                        confidence_score=score,
                    )
            return True
        except Exception:
            # Long-term promotion is best-effort.
            return False

    def _is_self_identity_fact(self, raw_text: str, structured: dict[str, Any]) -> bool:
        lower = (raw_text or "").strip().lower()
        if not lower:
            return False
        has_self_signal = any(
            sig in lower
            for sig in (
                "my name is",
                "i am ",
                "i'm ",
                "name:",
                "email:",
                "my email",
                "আমার নাম",
            )
        )
        if has_self_signal:
            return True
        for key in ("name", "full_name", "email", "location", "company", "role"):
            value = str((structured or {}).get(key) or "").strip()
            if value:
                return True
        return False

    def _extract_name_from_self_statement(self, raw_text: str) -> str:
        text = (raw_text or "").strip()
        if not text:
            return ""
        patterns = (
            r"(?i)\bmy\s+name\s+is\s+([a-z][a-z .'-]{1,80})\b",
            r"(?i)\bi\s+am\s+([a-z][a-z .'-]{1,80})\b",
            r"(?i)\bi'm\s+([a-z][a-z .'-]{1,80})\b",
            r"(?i)\bname\s*[:=-]\s*([a-z][a-z .'-]{1,80})\b",
            r"আমার\s+নাম\s+([ঀ-৿][ঀ-৿ .'-]{1,80})",
            r"নাম\s*[:=-]\s*([ঀ-৿][ঀ-৿ .'-]{1,80})",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            candidate = str(match.group(1) or "").strip(" \t,.;:-")
            if len(candidate.split()) > 6:
                continue
            lower = candidate.lower()
            if lower in {"a developer", "an engineer", "student", "boy", "girl"}:
                continue
            # Trim common continuation tokens in both English and Bangla.
            candidate = re.split(r"(?i)\s+(and|but|who|from|at|working|আমি|আর|এবং)\b", candidate)[0].strip(" \t,.;:-")
            if not candidate:
                continue
            return candidate
        return ""

    def list_long_term_slot_facts(self, *, query: str, memory_scope: str = "global", limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        slot_to_keys = (
            ("name", ("name", "full_name")),
            ("email", ("email",)),
            ("university", ("university", "education")),
            ("work", ("role", "company", "profession", "occupation")),
            ("hobby", ("hobby",)),
            ("favorite", ("favorite",)),
            ("location", ("location",)),
        )
        keys: list[str] = []
        for slot, mapped_keys in slot_to_keys:
            if slot in q or (slot == "work" and any(t in q for t in ("job", "company", "role", "profession", "occupation", "career"))):
                keys.extend(mapped_keys)
        if not keys:
            return []
        rows = self.repo.list_long_attributes_by_keys(
            memory_scope=memory_scope,
            attribute_keys=keys,
            limit=max(1, limit * 3),
        )
        if not rows:
            return []
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("attribute_key") or "").strip().lower()
            value = str(row.get("attribute_value") or "").strip()
            if not key or not value:
                continue
            dedupe = f"{key}:{value.lower()}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            text = f"{key}: {value}"
            confidence = max(
                0.0,
                min(
                    1.0,
                    float(row.get("confidence_score") or 0.0),
                ),
            )
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "text": text,
                    "score": confidence,
                    "source": "long_term_attribute",
                    "category": str(row.get("entity_type") or "general"),
                    "structured_data": {
                        "entity_id": row.get("entity_id"),
                        "entity_name": row.get("canonical_name"),
                        "attribute_key": key,
                    },
                    "importance": float(row.get("importance_score") or 0.0),
                    "confidence": confidence,
                    "created_at": (
                        row.get("updated_at").isoformat()
                        if hasattr(row.get("updated_at"), "isoformat")
                        else str(row.get("updated_at") or "")
                    ),
                }
            )
            if len(out) >= max(1, limit):
                break
        return out

    def list_long_term_slot_facts_any_scope(self, *, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        slot_to_keys = (
            ("name", ("name", "full_name")),
            ("email", ("email",)),
            ("university", ("university", "education")),
            ("work", ("role", "company", "profession", "occupation")),
            ("hobby", ("hobby",)),
            ("favorite", ("favorite",)),
            ("location", ("location",)),
            ("code", ("code", "marker", "token", "pin", "otp")),
        )
        keys: list[str] = []
        for slot, mapped_keys in slot_to_keys:
            if slot in q or (slot == "work" and any(t in q for t in ("job", "company", "role", "profession", "occupation", "career"))):
                keys.extend(mapped_keys)
        if not keys:
            return []
        rows = self.repo.list_long_attributes_by_keys_any_scope(
            attribute_keys=keys,
            limit=max(1, limit * 3),
        )
        if not rows:
            return []
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("attribute_key") or "").strip().lower()
            value = str(row.get("attribute_value") or "").strip()
            scope = str(row.get("memory_scope") or "global").strip() or "global"
            if not key or not value:
                continue
            dedupe = f"{scope}|{key}:{value.lower()}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            text = f"{key}: {value}"
            confidence = max(
                0.0,
                min(
                    1.0,
                    float(row.get("confidence_score") or 0.0),
                ),
            )
            out.append(
                {
                    "id": str(row.get("id") or ""),
                    "memory_scope": scope,
                    "text": text,
                    "score": confidence,
                    "source": "long_term_attribute",
                    "category": str(row.get("entity_type") or "general"),
                    "structured_data": {
                        "entity_id": row.get("entity_id"),
                        "entity_name": row.get("canonical_name"),
                        "attribute_key": key,
                    },
                    "importance": float(row.get("importance_score") or 0.0),
                    "confidence": confidence,
                    "created_at": (
                        row.get("updated_at").isoformat()
                        if hasattr(row.get("updated_at"), "isoformat")
                        else str(row.get("updated_at") or "")
                    ),
                }
            )
            if len(out) >= max(1, limit):
                break
        return out

    def list_short_term_slot_facts(self, *, query: str, memory_scope: str = "global", limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        slot_to_keys = (
            ("name", ("name", "full name")),
            ("email", ("email",)),
            ("university", ("university", "education")),
            ("work", ("role", "company", "profession", "occupation", "work")),
            ("hobby", ("hobby",)),
            ("favorite", ("favorite",)),
            ("location", ("location",)),
        )
        target_keys: set[str] = set()
        for slot, keys in slot_to_keys:
            if slot in q or (slot == "work" and any(t in q for t in ("job", "company", "role", "profession", "occupation", "career"))):
                target_keys.update(k.lower() for k in keys)
        if not target_keys:
            return []

        traces = self.repo.list_recent_short_traces(
            memory_scope=memory_scope,
            limit=SHORT_TERM_TRACE_MAX_ITEMS,
        )
        if not traces:
            return []

        line_pattern = re.compile(r"(?im)^\s*([a-z][a-z0-9 _/\-]{1,40})\s*[:=-]\s*([^\n]{2,160})\s*$")

        def _normalize_slot_key(raw_key: str) -> str:
            key = str(raw_key or "").strip().lower()
            if not key:
                return ""
            # Common profile labels frequently include qualifiers.
            key = re.sub(r"^(current|present|my|your)\s+", "", key).strip()
            alias_map = {
                "full name": "name",
                "current role": "role",
                "job title": "role",
                "current company": "company",
                "workplace": "company",
                "residence": "location",
                "city": "location",
            }
            return alias_map.get(key, key)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for trace in traces:
            created = trace.get("created_at")
            base_conf = max(0.0, min(1.0, float(trace.get("confidence_score") or 0.0)))
            candidates = [
                str(trace.get("user_message") or "").strip(),
                str(trace.get("assistant_response") or "").strip(),
            ]
            for text in candidates:
                if not text:
                    continue
                for match in line_pattern.finditer(text):
                    raw_key = _normalize_slot_key(str(match.group(1) or ""))
                    raw_value = str(match.group(2) or "").strip(" \t.;,")
                    if not raw_key or not raw_value:
                        continue
                    if raw_key not in target_keys:
                        continue
                    dedupe = f"{raw_key}:{raw_value.lower()}"
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    score = max(0.2, min(1.0, base_conf + 0.15))
                    trace_row_id = str(trace.get("id") or "")
                    synthetic_id = hashlib.sha256(
                        f"short-slot|{trace_row_id}|{raw_key}|{raw_value.lower()}".encode("utf-8")
                    ).hexdigest()
                    out.append(
                        {
                            "id": synthetic_id,
                            "text": f"{raw_key}: {raw_value}",
                            "score": score,
                            "source": "short_trace",
                            "category": "short_term",
                            "structured_data": {
                                "trace_id": trace.get("trace_id"),
                                "source_field": "user_or_assistant",
                                "attribute_key": raw_key,
                            },
                            "importance": score,
                            "confidence": score,
                            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                        }
                    )
        safe_limit = max(1, int(limit))
        out.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                str(item.get("created_at") or ""),
            ),
            reverse=True,
        )
        return out[:safe_limit]

    def list_short_term_slot_facts_any_scope(self, *, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        slot_to_keys = (
            ("name", ("name", "full name")),
            ("email", ("email",)),
            ("university", ("university", "education")),
            ("work", ("role", "company", "profession", "occupation", "work")),
            ("hobby", ("hobby",)),
            ("favorite", ("favorite",)),
            ("location", ("location",)),
        )
        target_keys: set[str] = set()
        for slot, keys in slot_to_keys:
            if slot in q or (slot == "work" and any(t in q for t in ("job", "company", "role", "profession", "occupation", "career"))):
                target_keys.update(k.lower() for k in keys)
        if not target_keys:
            return []

        traces = self.repo.list_recent_short_traces_any_scope(limit=SHORT_TERM_TRACE_MAX_ITEMS)
        if not traces:
            return []

        line_pattern = re.compile(r"(?im)^\s*([a-z][a-z0-9 _/\-]{1,40})\s*[:=-]\s*([^\n]{2,160})\s*$")

        def _normalize_slot_key(raw_key: str) -> str:
            key = str(raw_key or "").strip().lower()
            if not key:
                return ""
            key = re.sub(r"^(current|present|my|your)\s+", "", key).strip()
            alias_map = {
                "full name": "name",
                "current role": "role",
                "job title": "role",
                "current company": "company",
                "workplace": "company",
                "residence": "location",
                "city": "location",
            }
            return alias_map.get(key, key)

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for trace in traces:
            created = trace.get("created_at")
            trace_scope = str(trace.get("memory_scope") or "global").strip() or "global"
            base_conf = max(0.0, min(1.0, float(trace.get("confidence_score") or 0.0)))
            candidates = [
                str(trace.get("user_message") or "").strip(),
                str(trace.get("assistant_response") or "").strip(),
            ]
            for text in candidates:
                if not text:
                    continue
                for match in line_pattern.finditer(text):
                    raw_key = _normalize_slot_key(str(match.group(1) or ""))
                    raw_value = str(match.group(2) or "").strip(" \t.;,")
                    if not raw_key or not raw_value:
                        continue
                    if raw_key not in target_keys:
                        continue
                    dedupe = f"{trace_scope}|{raw_key}:{raw_value.lower()}"
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    score = max(0.2, min(1.0, base_conf + 0.15))
                    trace_row_id = str(trace.get("id") or "")
                    synthetic_id = hashlib.sha256(
                        f"short-slot-any|{trace_row_id}|{raw_key}|{raw_value.lower()}".encode("utf-8")
                    ).hexdigest()
                    out.append(
                        {
                            "id": synthetic_id,
                            "memory_scope": trace_scope,
                            "text": f"{raw_key}: {raw_value}",
                            "score": score,
                            "source": "short_trace",
                            "category": "short_term",
                            "structured_data": {
                                "trace_id": trace.get("trace_id"),
                                "source_field": "user_or_assistant",
                                "attribute_key": raw_key,
                            },
                            "importance": score,
                            "confidence": score,
                            "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                        }
                    )
        safe_limit = max(1, int(limit))
        out.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                str(item.get("created_at") or ""),
            ),
            reverse=True,
        )
        return out[:safe_limit]

    def list_short_term_context_facts(self, *, query: str, memory_scope: str = "global", limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        query_tokens = {tok for tok in re.findall(r"\w+", q) if len(tok) >= 2}
        if not query_tokens:
            return []

        traces = self.repo.list_recent_short_traces(
            memory_scope=memory_scope,
            limit=SHORT_TERM_TRACE_MAX_ITEMS,
        )
        if not traces:
            return []

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for trace in traces:
            created = trace.get("created_at")
            base_conf = max(0.0, min(1.0, float(trace.get("confidence_score") or 0.0)))
            for field_name in ("user_message", "assistant_response"):
                text = str(trace.get(field_name) or "").strip()
                if not text:
                    continue
                lowered = text.lower()
                text_tokens = {tok for tok in re.findall(r"\w+", lowered) if len(tok) >= 2}
                if not text_tokens:
                    continue
                overlap = len(query_tokens.intersection(text_tokens))
                if overlap <= 0:
                    continue
                overlap_norm = overlap / max(1.0, float(len(query_tokens)))
                score = max(0.2, min(1.0, (0.55 * overlap_norm) + (0.45 * base_conf)))
                dedupe = hashlib.sha256(f"{field_name}|{lowered}".encode("utf-8")).hexdigest()
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                out.append(
                    {
                        "id": hashlib.sha256(
                            f"short-ctx|{str(trace.get('id') or '')}|{field_name}|{lowered}".encode("utf-8")
                        ).hexdigest(),
                        "text": text,
                        "score": score,
                        "source": "short_trace_context",
                        "category": "short_term",
                        "structured_data": {
                            "trace_id": trace.get("trace_id"),
                            "source_field": field_name,
                        },
                        "importance": score,
                        "confidence": score,
                        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                    }
                )
        safe_limit = max(1, int(limit))
        out.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                str(item.get("created_at") or ""),
            ),
            reverse=True,
        )
        return out[:safe_limit]

    def list_short_term_context_facts_any_scope(self, *, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        query_tokens = {tok for tok in re.findall(r"\w+", q) if len(tok) >= 2}
        if not query_tokens:
            return []

        traces = self.repo.list_recent_short_traces_any_scope(limit=SHORT_TERM_TRACE_MAX_ITEMS)
        if not traces:
            return []

        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for trace in traces:
            created = trace.get("created_at")
            trace_scope = str(trace.get("memory_scope") or "global").strip() or "global"
            base_conf = max(0.0, min(1.0, float(trace.get("confidence_score") or 0.0)))
            for field_name in ("user_message", "assistant_response"):
                text = str(trace.get(field_name) or "").strip()
                if not text:
                    continue
                lowered = text.lower()
                text_tokens = {tok for tok in re.findall(r"\w+", lowered) if len(tok) >= 2}
                if not text_tokens:
                    continue
                overlap = len(query_tokens.intersection(text_tokens))
                if overlap <= 0:
                    continue
                overlap_norm = overlap / max(1.0, float(len(query_tokens)))
                score = max(0.2, min(1.0, (0.55 * overlap_norm) + (0.45 * base_conf)))
                dedupe = hashlib.sha256(f"{trace_scope}|{field_name}|{lowered}".encode("utf-8")).hexdigest()
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                out.append(
                    {
                        "id": hashlib.sha256(
                            f"short-ctx-any|{str(trace.get('id') or '')}|{field_name}|{lowered}".encode("utf-8")
                        ).hexdigest(),
                        "memory_scope": trace_scope,
                        "text": text,
                        "score": score,
                        "source": "short_trace_context",
                        "category": "short_term",
                        "structured_data": {
                            "trace_id": trace.get("trace_id"),
                            "source_field": field_name,
                        },
                        "importance": score,
                        "confidence": score,
                        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
                    }
                )
        safe_limit = max(1, int(limit))
        out.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                float(item.get("confidence") or 0.0),
                str(item.get("created_at") or ""),
            ),
            reverse=True,
        )
        return out[:safe_limit]

    def get_memory_observability(self, *, memory_scope: str = "global") -> dict[str, Any]:
        scope = (memory_scope or "global").strip() or "global"
        queue_counts = self.repo.get_short_queue_counts(memory_scope=scope)
        retrieval_method_counts = self.repo.get_short_retrieval_method_counts(memory_scope=scope)
        embedding_signal_counts = self.repo.get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="embedding.",
        )
        legacy_total = self.repo.count(memory_scope=scope)
        legacy_profile_like = self.repo.count_by_sources(
            memory_scope=scope,
            sources=["profile_fact", "profile_full", "chat_user", "manual"],
        )
        queue_total = int(queue_counts.get("pending", 0) + queue_counts.get("processed", 0) + queue_counts.get("rejected", 0))
        processed = int(queue_counts.get("processed", 0))
        promotion_rate = (float(processed) / float(queue_total)) if queue_total > 0 else 0.0
        return {
            "memory_scope": scope,
            "queue": {
                "total": queue_total,
                "pending": int(queue_counts.get("pending", 0)),
                "processed": processed,
                "rejected": int(queue_counts.get("rejected", 0)),
                "promotion_rate": promotion_rate,
            },
            "retrieval_method_mix": retrieval_method_counts,
            "embedding_health": {
                "fallback_total": int(embedding_signal_counts.get("embedding.fallback.total", 0)),
                "api_error_http_400": int(embedding_signal_counts.get("embedding.api_error.http_400", 0)),
                "api_error_http_401": int(embedding_signal_counts.get("embedding.api_error.http_401", 0)),
                "api_error_http_403": int(embedding_signal_counts.get("embedding.api_error.http_403", 0)),
                "api_error_http_429": int(embedding_signal_counts.get("embedding.api_error.http_429", 0)),
                "api_error_http_500": int(embedding_signal_counts.get("embedding.api_error.http_500", 0)),
                "signals": embedding_signal_counts,
            },
            "legacy_vs_long_mismatch": self._legacy_vs_long_mismatch(memory_scope=scope),
            "legacy_migration_state": {
                "legacy_write_enabled": bool(LEGACY_WRITE_ENABLED),
                "legacy_read_fallback_enabled": bool(LEGACY_READ_FALLBACK_ENABLED),
                "legacy_records_total": int(legacy_total),
                "legacy_profile_like_records": int(legacy_profile_like),
            },
        }

    def maybe_store_from_assistant_turn(self, *, text: str, memory_scope: str = "global") -> None:
        if not MEMORY_AUTO_STORE or not MEMORY_STORE_ASSISTANT_TURNS:
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="assistant_store_disabled")
            return
        t = (text or "").strip()
        if not self.should_store_memory_text(t):
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="assistant_text_filter_reject")
            return
        lower = t.lower()
        # Avoid storing uncertainty/meta chatter as durable memory.
        if any(
            sig in lower
            for sig in (
                "i couldn't find",
                "not fully verified",
                "please share",
                "i don't have",
                "saved fact:",
                "possible memory",
            )
        ):
            return
        classification = self.classify_memory_candidate(t)
        if not classification["should_store"]:
            self._record_memory_filter_decision(memory_scope=memory_scope, decision="assistant_classifier_reject")
            return
        self.add_memory(
            text=t,
            memory_scope=memory_scope,
            source="chat_assistant",
            importance=max(0.3, classification["importance_score"] * 0.8),
            confidence=max(0.25, classification["importance_score"] * 0.75),
            category=classification["category"],
            structured_data=classification["structured_data"],
        )
        self._record_memory_filter_decision(memory_scope=memory_scope, decision="assistant_store")
        prom_score = max(0.0, min(1.0, float(classification.get("importance_score") or 0.0)))
        if prom_score >= LONG_TERM_PROMOTE_MIN_SCORE:
            self._promote_user_fact_to_long_term(
                memory_scope=memory_scope,
                text=t,
                classification=classification,
            )

    def _heuristic_classify_memory_candidate(self, text: str) -> dict[str, Any]:
        t = (text or "").strip()
        lowered = t.lower()
        extracted: dict[str, str] = {}
        category = "general"
        score = 0.05
        if not t:
            return {"should_store": False, "importance_score": 0.0, "category": category, "structured_data": extracted}

        for key, pattern in (
            ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            ("phone", r"\+?\d[\d\s\-]{7,}\d"),
        ):
            match = re.search(pattern, t)
            if match:
                extracted[key] = match.group(0).strip()

        for key in ("name", "university", "education", "location", "company", "role", "hobby", "favorite"):
            m = re.search(rf"\b{key}\s*:\s*([^\n]{{2,160}})", t, flags=re.IGNORECASE)
            if m:
                extracted[key] = m.group(1).strip()

        if extracted.get("education"):
            category = "education"
            score = max(score, 0.85)
        if any(k in lowered for k in ("my name is", "i am ", "name:", "আমার নাম")):
            category = "person"
            score = max(score, 0.9)
        if any(k in lowered for k in ("university", "education", "college", "school")):
            category = "education"
            score = max(score, 0.85)
        if any(k in lowered for k in ("company", "employer", "role", "work", "office")):
            category = "work"
            score = max(score, 0.82)
        if any(k in lowered for k in ("prefer", "favorite", "favourite", "like ", "dislike")):
            category = "preference"
            score = max(score, 0.72)
        if any(k in lowered for k in ("birthday", "anniversary", "event", "appointment")):
            category = "event"
            score = max(score, 0.68)
        if extracted.get("email") or extracted.get("phone"):
            category = "contact"
            score = max(score, 0.9)

        should_store = score >= LONG_TERM_PROMOTE_MIN_SCORE
        return {
            "should_store": should_store,
            "importance_score": min(1.0, score),
            "category": category,
            "structured_data": extracted,
        }

    def classify_memory_candidate(self, text: str) -> dict[str, Any]:
        if self._typed_classification_chain is None:
            return self._heuristic_classify_memory_candidate(text)
        try:
            result = self._typed_classification_chain.invoke(text)
            if isinstance(result, dict):
                logger.debug("typed_classification_success")
                return self._normalize_classification_result(result)
        except Exception:
            logger.debug("typed_classification_fallback", exc_info=True)
        return self._heuristic_classify_memory_candidate(text)

    def _looks_like_structured_text(self, text: str) -> bool:
        lower = (text or "").lower()
        # Keep dense structured detection aligned with gateway.memory_logic.looks_like_structured_document_text
        # to avoid false "persistence failed" acknowledgements.
        if len(lower) > 700:
            return True
        signals = ("\\documentclass", "\\begin{document}", "\\section", "curriculum vitae", "resume", "latex")
        if sum(1 for s in signals if s in lower) >= 2:
            return True
        # Also treat dense profile-style key:value text as structured.
        key_value_lines = _STRUCTURED_KV_LINE_RE.findall(text or "")
        return len(key_value_lines) >= 4

    def _store_structured_facts(self, text: str, *, memory_scope: str) -> None:
        # Store full original structured text once for richer downstream use-cases
        # (e.g. regenerate CV, section-aware edits) while still indexing concise facts.
        self._store_full_profile_text(text, memory_scope=memory_scope)

        facts = self._extract_structured_facts(text)
        for fact_text in facts:
            classification = self.classify_memory_candidate(fact_text)
            self.add_memory(
                text=fact_text,
                memory_scope=memory_scope,
                source="profile_fact",
                importance=0.95,
                confidence=0.95,
                category="profile",
            )
            # Ensure structured-profile ingestion also feeds long-term entity memory.
            self._promote_user_fact_to_long_term(
                memory_scope=memory_scope,
                text=fact_text,
                classification=classification,
            )

    def _store_full_profile_text(self, text: str, *, memory_scope: str) -> None:
        raw = (text or "").strip()
        if not raw:
            return
        normalized = re.sub(r"\s+", " ", raw).strip().lower()
        recent = self.repo.list(memory_scope=memory_scope, limit=50, offset=0)
        for row in recent:
            if (row.source or "").strip().lower() != "profile_full":
                continue
            existing = re.sub(r"\s+", " ", (row.text or "").strip()).lower()
            if existing == normalized:
                return
        self.add_memory(
            text=raw,
            memory_scope=memory_scope,
            source="profile_full",
            importance=0.98,
            confidence=0.98,
            category="profile",
            structured_data={"kind": "full_document"},
        )

    def _extract_structured_facts(self, text: str) -> list[str]:
        out: list[str] = []
        src = text or ""
        normalized = self._normalize_document_text(src)
        key_aliases = {
            "full name": "name",
            "current role": "role",
            "job role": "role",
            "company name": "company",
            "home district": "home_district",
            "goals and future direction": "goals",
            "learning and development approach": "learning",
            "personality and work style": "work_style",
            "lifestyle and personal preferences": "preferences",
        }

        # Capture common resume headline name from LaTeX centered header.
        for m in re.finditer(r"\\color\{headcolor\}\s*([^}\\]{3,80})\}\s*\\\\", src):
            candidate = m.group(1).strip()
            if re.search(r"[A-Za-z]", candidate):
                out.append(f"name: {candidate}")
                break

        # Generic "key: value" facts (works for profile, project specs, metadata etc.)
        for m in _STRUCTURED_KV_CAPTURE_RE.finditer(normalized):
            key = m.group(1).strip().lower().replace("  ", " ")
            key = key_aliases.get(key, key)
            value = re.sub(r"^[*\-\s]+", "", m.group(2).strip())
            if self._is_valid_fact_pair(key, value):
                out.append(f"{key}: {value}")

        # Section-aware bullet extraction (captures richer profile text without
        # requiring every line to be strict key:value).
        section_to_key = {
            "technical skills": "skills",
            "interests": "interests",
            "goals and future direction": "goals",
            "learning and development approach": "learning",
            "personality and work style": "work_style",
            "lifestyle and personal preferences": "preferences",
            "engineering and research projects": "projects",
        }
        current_section_key = ""
        bucket: dict[str, list[str]] = {v: [] for v in section_to_key.values()}
        for raw_line in normalized.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower().strip(":")
            if lowered in section_to_key:
                current_section_key = section_to_key[lowered]
                continue
            if not current_section_key:
                continue
            cleaned = re.sub(r"^[*\d.\s-]+", "", line).strip()
            if len(cleaned) < 3:
                continue
            if cleaned.lower().startswith(("input:", "processing:", "output:", "deployment:", "focus:")):
                # Keep project sub-lines concise.
                cleaned = cleaned[:140]
            bucket[current_section_key].append(cleaned)
        for key, values in bucket.items():
            if not values:
                continue
            merged = "; ".join(values[:8])
            if len(merged) > 240:
                merged = merged[:240].rstrip(" ,;") + "..."
            if self._is_valid_fact_pair(key, merged):
                out.append(f"{key}: {merged}")

        # Generic first-person statements: "my X is Y"
        for m in re.finditer(r"(?im)\bmy\s+([a-z][a-z0-9 _/-]{1,40})\s+is\s+([^.\n]{2,160})", normalized):
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            if self._is_valid_fact_pair(key, value):
                out.append(f"{key}: {value}")

        # Keep useful special entities genericly (e.g., emails) without domain-specific assumptions.
        for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", normalized):
            out.append(f"email: {email.strip()}")
        for website in re.findall(r"https?://[^\s}]+|www\.[^\s}]+", normalized):
            site = website.strip().rstrip(".,;)")
            if site:
                out.append(f"website: {site}")

        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for item in out:
            key = item.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        collapse_keys = {"skills", "interests", "goals", "learning", "work_style", "preferences", "projects"}
        best_for_key: dict[str, tuple[int, int]] = {}
        compacted: list[str] = []
        for item in deduped:
            if ":" not in item:
                compacted.append(item)
                continue
            raw_key, raw_value = item.split(":", 1)
            key = raw_key.strip().lower()
            value = raw_value.strip()
            if key not in collapse_keys:
                compacted.append(item)
                continue
            existing = best_for_key.get(key)
            score = len(value)
            if existing is None:
                best_for_key[key] = (len(compacted), score)
                compacted.append(f"{key}: {value}")
                continue
            idx, prev_score = existing
            if score > prev_score:
                compacted[idx] = f"{key}: {value}"
                best_for_key[key] = (idx, score)
        return compacted[:40]

    def _normalize_document_text(self, text: str) -> str:
        s = text
        # Convert common latex commands into plain-text-like lines.
        s = re.sub(r"\\([A-Za-z]+)\{([^}]*)\}", r"\1: \2", s)
        s = re.sub(r"\\item\s+", "- ", s)
        s = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", s)
        s = re.sub(r"[{}]", " ", s)
        return re.sub(r"\s+\n", "\n", s)

    def _is_valid_fact_pair(self, key: str, value: str) -> bool:
        key = (key or "").strip().lower()
        value = (value or "").strip()
        if not key or not value:
            return False
        if len(key) > 40 or len(value) > 180:
            return False
        bad_keys = {
            "section",
            "subsection",
            "documentclass",
            "begin",
            "end",
            "item",
            "usepackage",
            "definecolor",
            "titleformat",
            "titlespacing",
            "setlist",
            "newcommand",
            "href",
            "color",
            "entryheader",
            "entrysubheader",
            "skillrow",
            "promotionnote",
            "pagestyle",
            "hypersetup",
        }
        if key in bad_keys:
            return False
        if "\\" in key or "{" in key or "}" in key:
            return False
        if key.startswith("%"):
            return False
        # Keep profile-like facts, avoid technical/style directives.
        allowed_prefixes = (
            "name",
            "full name",
            "email",
            "phone",
            "mobile",
            "website",
            "linkedin",
            "github",
            "location",
            "home district",
            "education",
            "university",
            "experience",
            "skills",
            "interests",
            "goals",
            "projects",
            "learning",
            "work style",
            "work_style",
            "preferences",
            "summary",
            "objective",
            "role",
            "current role",
            "company",
            "team",
        )
        if not key.startswith(allowed_prefixes):
            return False
        bad_values = ("### task:", "<chat_history>", "guidelines:", "json format:")
        lowered_value = value.lower()
        if any(sig in lowered_value for sig in bad_values):
            return False
        if "\\usepackage" in lowered_value or "\\definecolor" in lowered_value:
            return False
        return True

    def _prune_scope_if_needed(self, memory_scope: str) -> None:
        total = self.repo.count(memory_scope=memory_scope)
        if total <= MEMORY_MAX_ITEMS:
            return
        overflow = total - MEMORY_MAX_ITEMS
        # Fetch only ids that are guaranteed to be removed.
        rows = self.repo.list(
            memory_scope=memory_scope,
            limit=max(1, overflow),
            offset=max(0, MEMORY_MAX_ITEMS),
        )
        if not rows:
            return
        # Keep newest MEMORY_MAX_ITEMS; remove older records.
        to_remove_ids = [row.id for row in rows]
        self.repo.delete_many(memory_ids=to_remove_ids, memory_scope=memory_scope)
        self.reindex(memory_scope=memory_scope)


memory_service = MemoryService()

