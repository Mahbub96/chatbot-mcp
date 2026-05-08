from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC

from sqlalchemy import delete, func, select, text as sql_text

from memory.models import ChatTraceRecord, MemoryRecord


class MemoryRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create(
        self,
        *,
        memory_scope: str,
        text: str,
        source: str,
        importance: float,
        confidence: float = 0.5,
        category: str = "general",
        structured_data: str = "{}",
    ) -> MemoryRecord:
        normalized_source = (source or "chat").strip().lower() or "chat"
        memory = MemoryRecord(
            id=str(uuid.uuid4()),
            user_id=(memory_scope or "global").strip() or "global",
            memory_scope=(memory_scope or "global").strip() or "global",
            text=text.strip(),
            source=normalized_source,
            importance=max(0.0, min(1.0, float(importance))),
            confidence=max(0.0, min(1.0, float(confidence))),
            category=(category or "general").strip().lower() or "general",
            structured_data=structured_data or "{}",
            created_at=datetime.now(UTC),
        )
        with self._session_factory() as session:
            session.add(memory)
            session.commit()
            session.refresh(memory)
        return memory

    def create_chat_trace(
        self,
        *,
        request_id: str,
        memory_scope: str,
        user_text: str,
        assistant_text: str,
        model: str,
        confidence: float,
        retrieval_summary: str = "{}",
    ) -> ChatTraceRecord:
        trace = ChatTraceRecord(
            id=str(uuid.uuid4()),
            request_id=(request_id or "").strip() or str(uuid.uuid4()),
            user_id=(memory_scope or "global").strip() or "global",
            memory_scope=(memory_scope or "global").strip() or "global",
            user_text=(user_text or "").strip(),
            assistant_text=(assistant_text or "").strip(),
            model=(model or "").strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            retrieval_summary=retrieval_summary or "{}",
            created_at=datetime.now(UTC),
        )
        with self._session_factory() as session:
            session.add(trace)
            session.commit()
            session.refresh(trace)
        return trace

    def create_short_trace(
        self,
        *,
        trace_id: str,
        memory_scope: str,
        user_message: str,
        assistant_response: str,
        model_used: str,
        retrieved_memory_ids: list[str] | None = None,
        retrieval_method: str = "none",
        confidence_score: float = 0.5,
        latency_ms: int = 0,
    ) -> str:
        trace_row_id = str(uuid.uuid4())
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_method = (retrieval_method or "none").strip().lower() or "none"
        if normalized_method not in {"vector", "fts", "structured", "hybrid", "none"}:
            normalized_method = "none"
        retrieved_ids_json = json.dumps(
            [str(x).strip() for x in (retrieved_memory_ids or []) if str(x).strip()],
            ensure_ascii=True,
        )
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO short_traces(
                        id,
                        trace_id,
                        memory_scope,
                        user_message,
                        assistant_response,
                        model_used,
                        retrieved_memory_ids,
                        retrieval_method,
                        confidence_score,
                        latency_ms
                    )
                    VALUES (
                        :id,
                        :trace_id,
                        :memory_scope,
                        :user_message,
                        :assistant_response,
                        :model_used,
                        :retrieved_memory_ids,
                        :retrieval_method,
                        :confidence_score,
                        :latency_ms
                    )
                    """
                ),
                {
                    "id": trace_row_id,
                    "trace_id": (trace_id or "").strip() or trace_row_id,
                    "memory_scope": normalized_scope,
                    "user_message": (user_message or "").strip(),
                    "assistant_response": (assistant_response or "").strip(),
                    "model_used": (model_used or "").strip(),
                    "retrieved_memory_ids": retrieved_ids_json,
                    "retrieval_method": normalized_method,
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    "latency_ms": max(0, int(latency_ms)),
                },
            )
            session.commit()
        return trace_row_id

    def create_short_retrieval_log(
        self,
        *,
        trace_id: str,
        memory_scope: str,
        query_text: str,
        retrieved_ids: list[str] | None = None,
        method_used: str = "vector",
        score_distribution: dict | None = None,
        confidence_score: float = 0.5,
    ) -> str:
        row_id = str(uuid.uuid4())
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_method = (method_used or "vector").strip().lower() or "vector"
        if normalized_method not in {"vector", "fts", "structured", "hybrid"}:
            normalized_method = "vector"
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO short_retrieval_logs(
                        id,
                        trace_id,
                        memory_scope,
                        query_text,
                        retrieved_ids,
                        method_used,
                        score_distribution,
                        confidence_score
                    )
                    VALUES (
                        :id,
                        :trace_id,
                        :memory_scope,
                        :query_text,
                        :retrieved_ids,
                        :method_used,
                        :score_distribution,
                        :confidence_score
                    )
                    """
                ),
                {
                    "id": row_id,
                    "trace_id": (trace_id or "").strip() or row_id,
                    "memory_scope": normalized_scope,
                    "query_text": (query_text or "").strip(),
                    "retrieved_ids": json.dumps(
                        [str(x).strip() for x in (retrieved_ids or []) if str(x).strip()],
                        ensure_ascii=True,
                    ),
                    "method_used": normalized_method,
                    "score_distribution": json.dumps(score_distribution or {}, ensure_ascii=True),
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                },
            )
            session.commit()
        return row_id

    def create_short_memory_queue_item(
        self,
        *,
        trace_id: str,
        memory_scope: str,
        raw_content: str,
        extraction_status: str = "pending",
        importance_score: float = 0.0,
        confidence_score: float = 0.5,
        dedupe_fingerprint: str | None = None,
    ) -> str:
        row_id = str(uuid.uuid4())
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_status = (extraction_status or "pending").strip().lower() or "pending"
        if normalized_status not in {"pending", "processed", "rejected"}:
            normalized_status = "pending"
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO short_memory_queue(
                        id,
                        trace_id,
                        memory_scope,
                        raw_content,
                        extraction_status,
                        importance_score,
                        confidence_score,
                        dedupe_fingerprint
                    )
                    VALUES (
                        :id,
                        :trace_id,
                        :memory_scope,
                        :raw_content,
                        :extraction_status,
                        :importance_score,
                        :confidence_score,
                        :dedupe_fingerprint
                    )
                    """
                ),
                {
                    "id": row_id,
                    "trace_id": (trace_id or "").strip() or row_id,
                    "memory_scope": normalized_scope,
                    "raw_content": (raw_content or "").strip(),
                    "extraction_status": normalized_status,
                    "importance_score": max(0.0, min(1.0, float(importance_score))),
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    "dedupe_fingerprint": (dedupe_fingerprint or "").strip() or None,
                },
            )
            session.commit()
        return row_id

    def upsert_long_entity(
        self,
        *,
        memory_scope: str,
        entity_type: str,
        canonical_name: str,
        description: str,
        importance_score: float,
        confidence_score: float,
        dedupe_key: str,
        source_trace_id: str | None = None,
    ) -> str:
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_type = (entity_type or "fact").strip().lower() or "fact"
        normalized_name = (canonical_name or "").strip()
        if not normalized_name:
            normalized_name = "unknown"
        now_value = datetime.now(UTC)
        with self._session_factory() as session:
            existing = session.execute(
                sql_text(
                    """
                    SELECT id
                    FROM long_entities
                    WHERE memory_scope = :scope AND dedupe_key = :dedupe_key
                    LIMIT 1
                    """
                ),
                {"scope": normalized_scope, "dedupe_key": dedupe_key},
            ).first()
            if existing:
                entity_id = str(existing[0])
                session.execute(
                    sql_text(
                        """
                        UPDATE long_entities
                        SET
                            entity_type = :entity_type,
                            canonical_name = :canonical_name,
                            description = :description,
                            importance_score = :importance_score,
                            confidence_score = :confidence_score,
                            source_trace_id = :source_trace_id,
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": entity_id,
                        "entity_type": normalized_type,
                        "canonical_name": normalized_name,
                        "description": (description or "").strip(),
                        "importance_score": max(0.0, min(1.0, float(importance_score))),
                        "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                        "source_trace_id": (source_trace_id or "").strip() or None,
                        "updated_at": now_value,
                    },
                )
                session.commit()
                return entity_id
            entity_id = str(uuid.uuid4())
            session.execute(
                sql_text(
                    """
                    INSERT INTO long_entities(
                        id,
                        memory_scope,
                        entity_type,
                        canonical_name,
                        description,
                        importance_score,
                        confidence_score,
                        dedupe_key,
                        source_trace_id,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :id,
                        :memory_scope,
                        :entity_type,
                        :canonical_name,
                        :description,
                        :importance_score,
                        :confidence_score,
                        :dedupe_key,
                        :source_trace_id,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "id": entity_id,
                    "memory_scope": normalized_scope,
                    "entity_type": normalized_type,
                    "canonical_name": normalized_name,
                    "description": (description or "").strip(),
                    "importance_score": max(0.0, min(1.0, float(importance_score))),
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    "dedupe_key": (dedupe_key or "").strip(),
                    "source_trace_id": (source_trace_id or "").strip() or None,
                    "created_at": now_value,
                    "updated_at": now_value,
                },
            )
            session.commit()
            return entity_id

    def create_long_attribute(
        self,
        *,
        entity_id: str,
        attribute_key: str,
        attribute_value: str,
        value_type: str = "string",
        confidence_score: float = 0.5,
        source_trace_id: str | None = None,
        source_queue_id: str | None = None,
    ) -> str:
        row_id = str(uuid.uuid4())
        normalized_value_type = (value_type or "string").strip().lower() or "string"
        if normalized_value_type not in {"string", "number", "boolean", "json", "date"}:
            normalized_value_type = "string"
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO long_attributes(
                        id,
                        entity_id,
                        attribute_key,
                        attribute_value,
                        value_type,
                        confidence_score,
                        source_trace_id,
                        source_queue_id
                    )
                    VALUES (
                        :id,
                        :entity_id,
                        :attribute_key,
                        :attribute_value,
                        :value_type,
                        :confidence_score,
                        :source_trace_id,
                        :source_queue_id
                    )
                    """
                ),
                {
                    "id": row_id,
                    "entity_id": str(entity_id),
                    "attribute_key": (attribute_key or "").strip().lower(),
                    "attribute_value": (attribute_value or "").strip(),
                    "value_type": normalized_value_type,
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    "source_trace_id": (source_trace_id or "").strip() or None,
                    "source_queue_id": (source_queue_id or "").strip() or None,
                },
            )
            session.commit()
        return row_id

    def upsert_long_memory_fts_source(
        self,
        *,
        entity_id: str,
        memory_scope: str,
        canonical_name: str,
        description: str,
        attributes_text: str,
    ) -> None:
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            exists = session.execute(
                sql_text("SELECT 1 FROM long_memory_fts_source WHERE entity_id = :entity_id LIMIT 1"),
                {"entity_id": str(entity_id)},
            ).first()
            if exists:
                session.execute(
                    sql_text(
                        """
                        UPDATE long_memory_fts_source
                        SET
                            memory_scope = :memory_scope,
                            canonical_name = :canonical_name,
                            description = :description,
                            attributes_text = :attributes_text,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE entity_id = :entity_id
                        """
                    ),
                    {
                        "entity_id": str(entity_id),
                        "memory_scope": normalized_scope,
                        "canonical_name": (canonical_name or "").strip(),
                        "description": (description or "").strip(),
                        "attributes_text": (attributes_text or "").strip(),
                    },
                )
            else:
                session.execute(
                    sql_text(
                        """
                        INSERT INTO long_memory_fts_source(
                            entity_id,
                            memory_scope,
                            canonical_name,
                            description,
                            attributes_text
                        )
                        VALUES (
                            :entity_id,
                            :memory_scope,
                            :canonical_name,
                            :description,
                            :attributes_text
                        )
                        """
                    ),
                    {
                        "entity_id": str(entity_id),
                        "memory_scope": normalized_scope,
                        "canonical_name": (canonical_name or "").strip(),
                        "description": (description or "").strip(),
                        "attributes_text": (attributes_text or "").strip(),
                    },
                )
            session.commit()

    def upsert_long_embedding(
        self,
        *,
        entity_id: str,
        model_name: str,
        embedding_ref: str,
        confidence_score: float = 0.5,
    ) -> str:
        normalized_model = (model_name or "").strip()
        if not normalized_model:
            normalized_model = "unknown-model"
        with self._session_factory() as session:
            existing = session.execute(
                sql_text(
                    """
                    SELECT id
                    FROM long_embeddings
                    WHERE entity_id = :entity_id AND model_name = :model_name
                    LIMIT 1
                    """
                ),
                {"entity_id": str(entity_id), "model_name": normalized_model},
            ).first()
            if existing:
                row_id = str(existing[0])
                session.execute(
                    sql_text(
                        """
                        UPDATE long_embeddings
                        SET
                            embedding_ref = :embedding_ref,
                            confidence_score = :confidence_score,
                            created_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row_id,
                        "embedding_ref": (embedding_ref or "").strip(),
                        "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    },
                )
                session.commit()
                return row_id
            row_id = str(uuid.uuid4())
            session.execute(
                sql_text(
                    """
                    INSERT INTO long_embeddings(
                        id,
                        entity_id,
                        embedding_ref,
                        model_name,
                        confidence_score
                    )
                    VALUES (
                        :id,
                        :entity_id,
                        :embedding_ref,
                        :model_name,
                        :confidence_score
                    )
                    """
                ),
                {
                    "id": row_id,
                    "entity_id": str(entity_id),
                    "embedding_ref": (embedding_ref or "").strip(),
                    "model_name": normalized_model,
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                },
            )
            session.commit()
            return row_id

    def upsert_long_relationship(
        self,
        *,
        from_entity_id: str,
        to_entity_id: str,
        relation_type: str,
        confidence_score: float = 0.5,
        source_trace_id: str | None = None,
    ) -> str:
        if str(from_entity_id) == str(to_entity_id):
            return ""
        normalized_relation = (relation_type or "related_to").strip().lower() or "related_to"
        with self._session_factory() as session:
            existing = session.execute(
                sql_text(
                    """
                    SELECT id
                    FROM long_relationships
                    WHERE from_entity_id = :from_entity_id
                      AND to_entity_id = :to_entity_id
                      AND relation_type = :relation_type
                    LIMIT 1
                    """
                ),
                {
                    "from_entity_id": str(from_entity_id),
                    "to_entity_id": str(to_entity_id),
                    "relation_type": normalized_relation,
                },
            ).first()
            if existing:
                row_id = str(existing[0])
                session.execute(
                    sql_text(
                        """
                        UPDATE long_relationships
                        SET
                            confidence_score = :confidence_score,
                            source_trace_id = :source_trace_id
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row_id,
                        "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                        "source_trace_id": (source_trace_id or "").strip() or None,
                    },
                )
                session.commit()
                return row_id
            row_id = str(uuid.uuid4())
            session.execute(
                sql_text(
                    """
                    INSERT INTO long_relationships(
                        id,
                        from_entity_id,
                        to_entity_id,
                        relation_type,
                        confidence_score,
                        source_trace_id
                    )
                    VALUES (
                        :id,
                        :from_entity_id,
                        :to_entity_id,
                        :relation_type,
                        :confidence_score,
                        :source_trace_id
                    )
                    """
                ),
                {
                    "id": row_id,
                    "from_entity_id": str(from_entity_id),
                    "to_entity_id": str(to_entity_id),
                    "relation_type": normalized_relation,
                    "confidence_score": max(0.0, min(1.0, float(confidence_score))),
                    "source_trace_id": (source_trace_id or "").strip() or None,
                },
            )
            session.commit()
            return row_id

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._session_factory() as session:
            return session.execute(select(MemoryRecord).where(MemoryRecord.id == memory_id)).scalar_one_or_none()

    def list(self, *, memory_scope: str, limit: int = 50, offset: int = 0) -> list[MemoryRecord]:
        memory_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            return (
                session.execute(
                    select(MemoryRecord)
                    .where(MemoryRecord.memory_scope == memory_scope)
                    .order_by(MemoryRecord.created_at.desc())
                    .offset(max(0, offset))
                    .limit(max(1, min(500, limit)))
                )
                .scalars()
                .all()
            )

    def delete(self, *, memory_id: str, memory_scope: str) -> bool:
        memory_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            row = session.execute(
                select(MemoryRecord).where(
                    MemoryRecord.id == memory_id,
                    MemoryRecord.memory_scope == memory_scope,
                )
            ).scalar_one_or_none()
            if not row:
                return False
            session.execute(
                delete(MemoryRecord).where(
                    MemoryRecord.id == memory_id,
                    MemoryRecord.memory_scope == memory_scope,
                )
            )
            session.commit()
        return True

    def delete_many(self, *, memory_ids: list[str], memory_scope: str) -> int:
        memory_scope = (memory_scope or "global").strip() or "global"
        ids = [str(x).strip() for x in (memory_ids or []) if str(x).strip()]
        if not ids:
            return 0
        with self._session_factory() as session:
            result = session.execute(
                delete(MemoryRecord).where(
                    MemoryRecord.memory_scope == memory_scope,
                    MemoryRecord.id.in_(ids),
                )
            )
            session.commit()
            return int(result.rowcount or 0)

    def count(self, *, memory_scope: str) -> int:
        memory_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            return int(
                session.execute(
                    select(func.count()).select_from(MemoryRecord).where(MemoryRecord.memory_scope == memory_scope)
                ).scalar_one()
            )

    def list_all(self, *, limit: int = 500, offset: int = 0) -> list[MemoryRecord]:
        with self._session_factory() as session:
            return (
                session.execute(
                    select(MemoryRecord)
                    .order_by(MemoryRecord.created_at.desc())
                    .offset(max(0, offset))
                    .limit(max(1, min(5000, limit)))
                )
                .scalars()
                .all()
            )

    def list_by_sources(
        self,
        *,
        memory_scope: str,
        sources: list[str],
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        memory_scope = (memory_scope or "global").strip() or "global"
        normalized_sources = [s.strip().lower() for s in (sources or []) if isinstance(s, str) and s.strip()]
        if not normalized_sources:
            return []
        with self._session_factory() as session:
            return (
                session.execute(
                    select(MemoryRecord)
                    .where(
                        MemoryRecord.memory_scope == memory_scope,
                        MemoryRecord.source.in_(normalized_sources),
                    )
                    .order_by(MemoryRecord.created_at.desc())
                    .offset(max(0, offset))
                    .limit(max(1, min(5000, limit)))
                )
                .scalars()
                .all()
            )

    def list_all_by_sources(self, *, sources: list[str], limit: int = 500, offset: int = 0) -> list[MemoryRecord]:
        normalized_sources = [s.strip().lower() for s in (sources or []) if isinstance(s, str) and s.strip()]
        if not normalized_sources:
            return []
        with self._session_factory() as session:
            return (
                session.execute(
                    select(MemoryRecord)
                    .where(MemoryRecord.source.in_(normalized_sources))
                    .order_by(MemoryRecord.created_at.desc())
                    .offset(max(0, offset))
                    .limit(max(1, min(5000, limit)))
                )
                .scalars()
                .all()
            )

    def latest_by_source(self, *, memory_scope: str, source: str) -> MemoryRecord | None:
        memory_scope = (memory_scope or "global").strip() or "global"
        normalized_source = (source or "").strip().lower()
        if not normalized_source:
            return None
        with self._session_factory() as session:
            return session.execute(
                select(MemoryRecord)
                .where(
                    MemoryRecord.memory_scope == memory_scope,
                    MemoryRecord.source == normalized_source,
                )
                .order_by(MemoryRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

    def latest_by_source_any_scope(self, *, source: str) -> MemoryRecord | None:
        normalized_source = (source or "").strip().lower()
        if not normalized_source:
            return None
        with self._session_factory() as session:
            return session.execute(
                select(MemoryRecord)
                .where(MemoryRecord.source == normalized_source)
                .order_by(MemoryRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

    def search_text_fts(self, *, memory_scope: str, query: str, limit: int = 20) -> list[dict]:
        memory_scope = (memory_scope or "global").strip() or "global"
        q = (query or "").strip()
        if not q:
            return []
        safe_limit = max(1, min(500, int(limit)))
        sql = sql_text(
            "SELECT m.id, m.text, m.source, m.importance, m.created_at, bm25(memory_records_fts) AS rank "
            "FROM memory_records_fts f "
            "JOIN memory_records m ON m.rowid = f.rowid "
            "WHERE memory_records_fts MATCH :q AND m.memory_scope = :scope "
            "ORDER BY rank ASC, m.created_at DESC "
            "LIMIT :lim"
        )
        with self._session_factory() as session:
            try:
                rows = session.execute(sql, {"q": q, "scope": memory_scope, "lim": safe_limit}).mappings().all()
            except Exception:
                return []
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "text": str(row["text"] or ""),
                    "source": str(row["source"] or ""),
                    "importance": float(row["importance"] or 0.0),
                    "created_at": row["created_at"],
                    "rank": float(row["rank"] or 0.0),
                }
            )
        return out

    def prune_chat_traces(self, *, memory_scope: str, keep_latest: int) -> int:
        safe_keep = max(1, int(keep_latest))
        memory_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            ids = session.execute(
                select(ChatTraceRecord.id)
                .where(ChatTraceRecord.memory_scope == memory_scope)
                .order_by(ChatTraceRecord.created_at.desc())
                .offset(safe_keep)
            ).scalars().all()
            if not ids:
                return 0
            result = session.execute(
                delete(ChatTraceRecord).where(
                    ChatTraceRecord.memory_scope == memory_scope,
                    ChatTraceRecord.id.in_(ids),
                )
            )
            session.commit()
            return int(result.rowcount or 0)

    def prune_short_traces(self, *, memory_scope: str, keep_latest: int) -> int:
        safe_keep = max(1, int(keep_latest))
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            ids = session.execute(
                sql_text(
                    """
                    SELECT id
                    FROM short_traces
                    WHERE memory_scope = :scope
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET :offset
                    """
                ),
                {"scope": normalized_scope, "offset": safe_keep},
            ).scalars().all()
            if not ids:
                return 0
            deleted = 0
            for row_id in ids:
                result = session.execute(
                    sql_text(
                        "DELETE FROM short_traces WHERE memory_scope = :scope AND id = :id"
                    ),
                    {"scope": normalized_scope, "id": str(row_id)},
                )
                deleted += int(result.rowcount or 0)
            session.commit()
            return deleted

