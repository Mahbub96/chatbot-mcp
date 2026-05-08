from __future__ import annotations

import re
import json
import hashlib
from typing import Any
from uuid import uuid4
import logging

from config import (
    MEMORY_AUTO_STORE,
    MEMORY_MAX_ITEMS,
    MEMORY_MIN_SCORE,
    MEMORY_TOP_K,
    MEMORY_VECTOR_BACKEND,
    SHORT_TERM_TRACE_MAX_ITEMS,
)
from memory.db import create_engine_and_session
from memory.embedder import NvidiaEmbeddingService
from memory.pgvector_store import PgVectorStore
from memory.repository import MemoryRepository
from memory.vector_store import FaissVectorStore

logger = logging.getLogger(__name__)

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
            result = parsed.model_dump()
            result["importance_score"] = max(0.0, min(1.0, float(result.get("importance_score") or 0.0)))
            result["category"] = str(result.get("category") or "general").strip().lower() or "general"
            if not isinstance(result.get("structured_data"), dict):
                result["structured_data"] = {}
            return result

        return RunnableLambda(_normalize) | RunnableLambda(_heuristic) | RunnableLambda(_typed)

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
    ) -> dict[str, Any]:
        text = (text or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not text:
            return {"success": False, "error": "text cannot be empty"}

        # Exact dedupe on recent scope items.
        recent = self.repo.list(memory_scope=memory_scope, limit=50, offset=0)
        if any((r.text or "").strip().lower() == text.lower() for r in recent):
            return {"success": True, "deduped": True}

        row = self.repo.create(
            memory_scope=memory_scope,
            text=text,
            source=source,
            importance=importance,
            confidence=float(confidence if confidence is not None else importance),
            category=category,
            structured_data=json.dumps(structured_data or {}, ensure_ascii=True),
        )
        try:
            self.vector.add(
                memory_id=row.id,
                memory_scope=row.memory_scope,
                embedding=self.embedder.embed(row.text),
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
        candidates = self.vector.search(
            memory_scope=memory_scope,
            embedding=self.embedder.embed(query),
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

    def list_items(self, *, memory_scope: str = "global", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
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

    def list_profile_facts(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repo.list_by_sources(
            memory_scope=memory_scope,
            sources=["profile_fact"],
            limit=max(1, limit),
            offset=0,
        )
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

    def list_profile_memories(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repo.list_by_sources(
            memory_scope=memory_scope,
            sources=["profile_fact", "profile_full"],
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

    def list_profile_facts_any_scope(self, *, limit: int = 20) -> list[dict[str, Any]]:
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
            retrieval_method = "none"
            if retrieved_items:
                retrieval_method = "vector"
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
            except Exception:
                # New short_* path should not break legacy path.
                pass
            self.repo.prune_chat_traces(memory_scope=memory_scope, keep_latest=SHORT_TERM_TRACE_MAX_ITEMS)
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
        confidence = max(0.0, min(1.0, score_distribution["max"]))
        try:
            self.repo.create_short_retrieval_log(
                trace_id=trace_id,
                memory_scope=memory_scope,
                query_text=query,
                retrieved_ids=[str(item.get("id") or "") for item in items if item.get("id")],
                method_used=method_used,
                score_distribution=score_distribution,
                confidence_score=confidence,
            )
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

    def maybe_store_from_user_turn(self, *, text: str, memory_scope: str = "global") -> None:
        if not MEMORY_AUTO_STORE:
            return
        t = (text or "").strip()
        if len(t) < 8:
            return
        self._enqueue_short_memory_candidate(text=t, memory_scope=memory_scope)
        if t.endswith("?") or t.endswith("؟"):
            return
        lowered = t.lower()
        if "### task:" in lowered or "<chat_history>" in lowered:
            return
        # For long/structured text, store extracted concise facts instead of raw blob.
        if self._looks_like_structured_text(t):
            self._store_structured_facts(t, memory_scope=memory_scope)
            return
        if len(t) > 800:
            return
        classification = self.classify_memory_candidate(t)
        if not classification["should_store"]:
            return
        self.add_memory(
            text=t,
            memory_scope=memory_scope,
            source="chat_user",
            importance=classification["importance_score"],
            confidence=classification["importance_score"],
            category=classification["category"],
            structured_data=classification["structured_data"],
        )
        self._promote_user_fact_to_long_term(
            memory_scope=memory_scope,
            text=t,
            classification=classification,
        )

    def _enqueue_short_memory_candidate(self, *, text: str, memory_scope: str) -> None:
        raw = (text or "").strip()
        if not raw:
            return
        classification = self.classify_memory_candidate(raw)
        fingerprint = hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()
        try:
            self.repo.create_short_memory_queue_item(
                trace_id=str(uuid4()),
                memory_scope=memory_scope,
                raw_content=raw,
                extraction_status="pending",
                importance_score=float(classification.get("importance_score") or 0.0),
                confidence_score=float(classification.get("importance_score") or 0.0),
                dedupe_fingerprint=fingerprint,
            )
        except Exception:
            # Queue staging should never block chat path.
            return

    def _promote_user_fact_to_long_term(
        self,
        *,
        memory_scope: str,
        text: str,
        classification: dict[str, Any],
    ) -> None:
        score = max(0.0, min(1.0, float(classification.get("importance_score") or 0.0)))
        if score < 0.6:
            return
        raw = (text or "").strip()
        if not raw:
            return
        structured = classification.get("structured_data") or {}
        if not isinstance(structured, dict):
            structured = {}
        category = (classification.get("category") or "fact").strip().lower() or "fact"
        canonical_name = str(structured.get("name") or structured.get("full_name") or "").strip() or raw[:80]
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
                self.repo.create_long_attribute(
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
                embedding = self.embedder.embed(raw[:1200])
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
                    self.repo.create_long_attribute(
                        entity_id=to_entity_id,
                        attribute_key="name",
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
        except Exception:
            # Long-term promotion is best-effort.
            return

    def maybe_store_from_assistant_turn(self, *, text: str, memory_scope: str = "global") -> None:
        t = (text or "").strip()
        if len(t) < 8:
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
        if len(t) > 1200:
            return
        classification = self.classify_memory_candidate(t)
        if not classification["should_store"]:
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

        for key in ("name", "university", "location", "company", "role", "hobby", "favorite"):
            m = re.search(rf"\b{key}\s*:\s*([^\n]{{2,160}})", t, flags=re.IGNORECASE)
            if m:
                extracted[key] = m.group(1).strip()

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

        should_store = score >= 0.6
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
                return result
        except Exception:
            logger.debug("typed_classification_fallback", exc_info=True)
        return self._heuristic_classify_memory_candidate(text)

    def _looks_like_structured_text(self, text: str) -> bool:
        lower = (text or "").lower()
        latex_signals = ("\\begin{document}", "\\section", "\\subsection", "\\textbf", "\\item", "\\cv")
        structure_signals = ("education", "experience", "skills", "email", "resume", "curriculum vitae", "profile")
        signal_count = sum(1 for s in latex_signals if s in lower) + sum(1 for s in structure_signals if s in lower)
        return signal_count >= 2 or len(text) > 1200

    def _store_structured_facts(self, text: str, *, memory_scope: str) -> None:
        # Store full original structured text once for richer downstream use-cases
        # (e.g. regenerate CV, section-aware edits) while still indexing concise facts.
        self._store_full_profile_text(text, memory_scope=memory_scope)

        facts = self._extract_structured_facts(text)
        for fact_text in facts:
            self.add_memory(
                text=fact_text,
                memory_scope=memory_scope,
                source="profile_fact",
                importance=0.95,
                confidence=0.95,
                category="profile",
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

        # Capture common resume headline name from LaTeX centered header.
        for m in re.finditer(r"\\color\{headcolor\}\s*([^}\\]{3,80})\}\s*\\\\", src):
            candidate = m.group(1).strip()
            if re.search(r"[A-Za-z]", candidate):
                out.append(f"name: {candidate}")
                break

        # Generic "key: value" facts (works for profile, project specs, metadata etc.)
        for m in re.finditer(r"(?im)^\s*([A-Za-z][A-Za-z0-9 _/\-]{1,40})\s*[:\-]\s*([^\n]{2,180})\s*$", normalized):
            key = m.group(1).strip().lower().replace("  ", " ")
            value = m.group(2).strip()
            if self._is_valid_fact_pair(key, value):
                out.append(f"{key}: {value}")

        # Generic first-person statements: "my X is Y"
        for m in re.finditer(r"(?im)\bmy\s+([a-z][a-z0-9 _/\-]{1,40})\s+is\s+([^.\n]{2,160})", normalized):
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
        return deduped[:10]

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
            "education",
            "university",
            "experience",
            "skills",
            "summary",
            "objective",
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

