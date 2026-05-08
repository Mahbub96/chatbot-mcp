from __future__ import annotations

import uuid
from datetime import datetime, UTC

from sqlalchemy import text as sql_text


class LongTermRepositoryMixin:
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

    def list_long_attributes_by_keys(
        self,
        *,
        memory_scope: str,
        attribute_keys: list[str],
        limit: int = 20,
    ) -> list[dict]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        keys = [str(k).strip().lower() for k in (attribute_keys or []) if str(k).strip()]
        if not keys:
            return []
        safe_limit = max(1, min(100, int(limit)))
        placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
        params: dict[str, object] = {"scope": normalized_scope, "lim": safe_limit}
        for i, value in enumerate(keys):
            params[f"k{i}"] = value
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    f"""
                    SELECT
                        a.id,
                        a.entity_id,
                        a.attribute_key,
                        a.attribute_value,
                        a.value_type,
                        a.confidence_score,
                        a.created_at,
                        e.entity_type,
                        e.canonical_name,
                        e.description,
                        e.importance_score,
                        e.updated_at
                    FROM long_attributes a
                    JOIN long_entities e ON e.id = a.entity_id
                    WHERE e.memory_scope = :scope
                      AND a.attribute_key IN ({placeholders})
                    ORDER BY a.confidence_score DESC, e.updated_at DESC, a.created_at DESC
                    LIMIT :lim
                    """
                ),
                params,
            ).mappings().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "entity_id": str(row["entity_id"]),
                    "entity_type": str(row["entity_type"] or ""),
                    "canonical_name": str(row["canonical_name"] or ""),
                    "description": str(row["description"] or ""),
                    "importance_score": float(row["importance_score"] or 0.0),
                    "attribute_key": str(row["attribute_key"] or ""),
                    "attribute_value": str(row["attribute_value"] or ""),
                    "value_type": str(row["value_type"] or "string"),
                    "confidence_score": float(row["confidence_score"] or 0.0),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def search_long_text_fts(self, *, memory_scope: str, query: str, limit: int = 20) -> list[dict]:
        memory_scope = (memory_scope or "global").strip() or "global"
        q = (query or "").strip()
        if not q:
            return []
        safe_limit = max(1, min(500, int(limit)))
        sql = sql_text(
            "SELECT s.entity_id, s.canonical_name, s.description, s.attributes_text, s.updated_at, "
            "bm25(long_memory_fts) AS rank "
            "FROM long_memory_fts f "
            "JOIN long_memory_fts_source s ON s.rowid = f.rowid "
            "WHERE long_memory_fts MATCH :q AND s.memory_scope = :scope "
            "ORDER BY rank ASC, s.updated_at DESC "
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
                    "entity_id": str(row["entity_id"] or ""),
                    "canonical_name": str(row["canonical_name"] or ""),
                    "description": str(row["description"] or ""),
                    "attributes_text": str(row["attributes_text"] or ""),
                    "updated_at": row["updated_at"],
                    "rank": float(row["rank"] or 0.0),
                }
            )
        return out

    def list_long_attributes_by_keys_any_scope(
        self,
        *,
        attribute_keys: list[str],
        limit: int = 20,
    ) -> list[dict]:
        keys = [str(k).strip().lower() for k in (attribute_keys or []) if str(k).strip()]
        if not keys:
            return []
        safe_limit = max(1, min(200, int(limit)))
        placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
        params: dict[str, object] = {"lim": safe_limit}
        for i, value in enumerate(keys):
            params[f"k{i}"] = value
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    f"""
                    SELECT
                        a.id,
                        a.entity_id,
                        a.attribute_key,
                        a.attribute_value,
                        a.value_type,
                        a.confidence_score,
                        a.created_at,
                        e.memory_scope,
                        e.entity_type,
                        e.canonical_name,
                        e.description,
                        e.importance_score,
                        e.updated_at
                    FROM long_attributes a
                    JOIN long_entities e ON e.id = a.entity_id
                    WHERE a.attribute_key IN ({placeholders})
                    ORDER BY a.confidence_score DESC, e.updated_at DESC, a.created_at DESC
                    LIMIT :lim
                    """
                ),
                params,
            ).mappings().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "entity_id": str(row["entity_id"]),
                    "memory_scope": str(row["memory_scope"] or "global"),
                    "entity_type": str(row["entity_type"] or ""),
                    "canonical_name": str(row["canonical_name"] or ""),
                    "description": str(row["description"] or ""),
                    "importance_score": float(row["importance_score"] or 0.0),
                    "attribute_key": str(row["attribute_key"] or ""),
                    "attribute_value": str(row["attribute_value"] or ""),
                    "value_type": str(row["value_type"] or "string"),
                    "confidence_score": float(row["confidence_score"] or 0.0),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def upsert_long_attribute(
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
        normalized_key = (attribute_key or "").strip().lower()
        normalized_value = (attribute_value or "").strip()
        if not normalized_key or not normalized_value:
            return ""
        normalized_value_type = (value_type or "string").strip().lower() or "string"
        if normalized_value_type not in {"string", "number", "boolean", "json", "date"}:
            normalized_value_type = "string"
        with self._session_factory() as session:
            existing = session.execute(
                sql_text(
                    """
                    SELECT id, attribute_value, confidence_score
                    FROM long_attributes
                    WHERE entity_id = :entity_id
                      AND attribute_key = :attribute_key
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "entity_id": str(entity_id),
                    "attribute_key": normalized_key,
                },
            ).first()
            if existing:
                row_id = str(existing[0])
                current_value = str(existing[1] or "").strip()
                current_conf = float(existing[2] or 0.0)
                incoming_conf = max(0.0, min(1.0, float(confidence_score)))
                # Override stale/incorrect values when new fact is stronger or changed.
                should_update = (
                    current_value.lower() != normalized_value.lower()
                    or incoming_conf >= current_conf
                )
                if not should_update:
                    return row_id
                session.execute(
                    sql_text(
                        """
                        UPDATE long_attributes
                        SET
                            attribute_value = :attribute_value,
                            value_type = :value_type,
                            confidence_score = :confidence_score,
                            source_trace_id = :source_trace_id,
                            source_queue_id = :source_queue_id,
                            created_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row_id,
                        "attribute_value": normalized_value,
                        "value_type": normalized_value_type,
                        "confidence_score": incoming_conf,
                        "source_trace_id": (source_trace_id or "").strip() or None,
                        "source_queue_id": (source_queue_id or "").strip() or None,
                    },
                )
                session.commit()
                return row_id
        return self.create_long_attribute(
            entity_id=str(entity_id),
            attribute_key=normalized_key,
            attribute_value=normalized_value,
            value_type=normalized_value_type,
            confidence_score=confidence_score,
            source_trace_id=source_trace_id,
            source_queue_id=source_queue_id,
        )

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

