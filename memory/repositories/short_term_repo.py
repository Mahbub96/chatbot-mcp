from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text as sql_text


class ShortTermRepositoryMixin:
    def clear_short_term_memory(self, *, memory_scope: str | None = None) -> dict[str, int]:
        normalized_scope = (memory_scope or "").strip()
        where_scope = " WHERE memory_scope = :scope" if normalized_scope else ""
        params = {"scope": normalized_scope} if normalized_scope else {}
        tables = (
            "short_traces",
            "short_retrieval_logs",
            "short_memory_queue",
            "short_runtime_metrics",
            "short_scope_resolution_events",
        )
        counts: dict[str, int] = {}
        with self._session_factory() as session:
            for table in tables:
                result = session.execute(sql_text(f"DELETE FROM {table}{where_scope}"), params)
                counts[table] = int(result.rowcount or 0)
            session.commit()
        return counts

    def enforce_short_term_retention(
        self,
        *,
        memory_scope: str,
        retention_hours: int = 24,
        max_traces: int = 20000,
        max_queue_items: int = 25000,
        max_retrieval_logs: int = 25000,
    ) -> dict[str, int]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        safe_hours = max(1, int(retention_hours))
        safe_max_traces = max(100, int(max_traces))
        safe_max_queue = max(100, int(max_queue_items))
        safe_max_retrieval = max(100, int(max_retrieval_logs))
        pruned = {
            "short_traces_ttl": 0,
            "short_retrieval_logs_ttl": 0,
            "short_memory_queue_ttl": 0,
            "short_scope_resolution_events_ttl": 0,
            "short_runtime_metrics_stale": 0,
            "short_traces_overflow": 0,
            "short_memory_queue_overflow": 0,
            "short_retrieval_logs_overflow": 0,
        }
        with self._session_factory() as session:
            ttl_expr = f"datetime('now', '-{safe_hours} hours')"
            ttl_specs = (
                ("short_traces_ttl", "short_traces", "created_at"),
                ("short_retrieval_logs_ttl", "short_retrieval_logs", "created_at"),
                ("short_memory_queue_ttl", "short_memory_queue", "created_at"),
                ("short_scope_resolution_events_ttl", "short_scope_resolution_events", "created_at"),
                ("short_runtime_metrics_stale", "short_runtime_metrics", "updated_at"),
            )
            for metric_key, table, timestamp_col in ttl_specs:
                result = session.execute(
                    sql_text(
                        f"""
                        DELETE FROM {table}
                        WHERE memory_scope = :scope
                          AND {timestamp_col} < {ttl_expr}
                        """
                    ),
                    {"scope": normalized_scope},
                )
                pruned[metric_key] = int(result.rowcount or 0)

            overflow_specs = (
                ("short_traces_overflow", "short_traces", safe_max_traces),
                ("short_memory_queue_overflow", "short_memory_queue", safe_max_queue),
                ("short_retrieval_logs_overflow", "short_retrieval_logs", safe_max_retrieval),
            )
            for metric_key, table, keep_latest in overflow_specs:
                result = session.execute(
                    sql_text(
                        f"""
                        DELETE FROM {table}
                        WHERE id IN (
                            SELECT id
                            FROM {table}
                            WHERE memory_scope = :scope
                            ORDER BY created_at DESC
                            LIMIT -1 OFFSET :offset
                        )
                        """
                    ),
                    {"scope": normalized_scope, "offset": int(keep_latest)},
                )
                pruned[metric_key] = int(result.rowcount or 0)
            session.commit()
        return pruned

    def enforce_short_term_ttl_across_scopes(self, *, retention_hours: int = 24) -> dict[str, int]:
        """Delete short-* rows older than retention window for every memory_scope (boot hygiene)."""
        safe_hours = max(1, int(retention_hours))
        ttl_expr = f"datetime('now', '-{safe_hours} hours')"
        pruned = {
            "short_traces_ttl": 0,
            "short_retrieval_logs_ttl": 0,
            "short_memory_queue_ttl": 0,
            "short_scope_resolution_events_ttl": 0,
            "short_runtime_metrics_stale": 0,
        }
        ttl_specs = (
            ("short_traces_ttl", "short_traces", "created_at"),
            ("short_retrieval_logs_ttl", "short_retrieval_logs", "created_at"),
            ("short_memory_queue_ttl", "short_memory_queue", "created_at"),
            ("short_scope_resolution_events_ttl", "short_scope_resolution_events", "created_at"),
            ("short_runtime_metrics_stale", "short_runtime_metrics", "updated_at"),
        )
        with self._session_factory() as session:
            for metric_key, table, timestamp_col in ttl_specs:
                result = session.execute(
                    sql_text(
                        f"""
                        DELETE FROM {table}
                        WHERE {timestamp_col} < {ttl_expr}
                        """
                    ),
                )
                pruned[metric_key] = int(result.rowcount or 0)
            session.commit()
        return pruned

    def create_short_scope_resolution_event(
        self,
        *,
        memory_scope: str,
        source: str,
        source_key: str,
    ) -> str:
        row_id = str(uuid.uuid4())
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_source = (source or "default").strip().lower() or "default"
        normalized_key = (source_key or "").strip().lower()
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO short_scope_resolution_events(
                        id,
                        memory_scope,
                        source,
                        source_key
                    )
                    VALUES (
                        :id,
                        :memory_scope,
                        :source,
                        :source_key
                    )
                    """
                ),
                {
                    "id": row_id,
                    "memory_scope": normalized_scope,
                    "source": normalized_source,
                    "source_key": normalized_key,
                },
            )
            # keep only recent bounded events per scope
            session.execute(
                sql_text(
                    """
                    DELETE FROM short_scope_resolution_events
                    WHERE id IN (
                        SELECT id
                        FROM short_scope_resolution_events
                        WHERE memory_scope = :scope
                        ORDER BY created_at DESC
                        LIMIT -1 OFFSET 200
                    )
                    """
                ),
                {"scope": normalized_scope},
            )
            session.commit()
        return row_id

    def get_short_retrieval_method_counts(self, *, memory_scope: str) -> dict[str, int]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT method_used, COUNT(*) AS cnt
                    FROM short_retrieval_logs
                    WHERE memory_scope = :scope
                    GROUP BY method_used
                    """
                ),
                {"scope": normalized_scope},
            ).mappings().all()
        out = {"vector": 0, "fts": 0, "structured": 0, "hybrid": 0}
        for row in rows:
            key = str(row.get("method_used") or "").strip().lower()
            if key in out:
                out[key] = int(row.get("cnt") or 0)
        return out

    def prune_short_traces(self, *, memory_scope: str, keep_latest: int) -> int:
        safe_keep = max(1, int(keep_latest))
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            result = session.execute(
                sql_text(
                    """
                    DELETE FROM short_traces
                    WHERE id IN (
                        SELECT id
                        FROM short_traces
                        WHERE memory_scope = :scope
                        ORDER BY created_at DESC
                        LIMIT -1 OFFSET :offset
                    )
                    """
                ),
                {"scope": normalized_scope, "offset": safe_keep},
            )
            deleted = int(result.rowcount or 0)
            session.commit()
            return deleted

    def increment_short_runtime_metric(self, *, memory_scope: str, metric_key: str, delta: int = 1) -> None:
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_key = (metric_key or "").strip().lower()
        if not normalized_key:
            return
        safe_delta = max(0, int(delta))
        if safe_delta <= 0:
            return
        with self._session_factory() as session:
            session.execute(
                sql_text(
                    """
                    INSERT INTO short_runtime_metrics(memory_scope, metric_key, metric_value)
                    VALUES (:scope, :metric_key, :delta)
                    ON CONFLICT(memory_scope, metric_key)
                    DO UPDATE SET
                        metric_value = short_runtime_metrics.metric_value + :delta,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "scope": normalized_scope,
                    "metric_key": normalized_key,
                    "delta": safe_delta,
                },
            )
            session.commit()

    def get_short_runtime_metric_counts(self, *, memory_scope: str, prefix: str | None = None) -> dict[str, int]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        normalized_prefix = (prefix or "").strip().lower()
        query = (
            """
            SELECT metric_key, metric_value
            FROM short_runtime_metrics
            WHERE memory_scope = :scope
            """
        )
        params: dict[str, Any] = {"scope": normalized_scope}
        if normalized_prefix:
            query += " AND metric_key LIKE :prefix"
            params["prefix"] = f"{normalized_prefix}%"
        with self._session_factory() as session:
            rows = session.execute(sql_text(query), params).mappings().all()
        out: dict[str, int] = {}
        for row in rows:
            key = str(row.get("metric_key") or "").strip().lower()
            if not key:
                continue
            out[key] = int(row.get("metric_value") or 0)
        return out

    def mark_short_memory_queue_item(
        self,
        *,
        queue_id: str,
        extraction_status: str,
    ) -> bool:
        normalized_status = (extraction_status or "").strip().lower()
        if normalized_status not in {"processed", "rejected"}:
            return False
        target_id = (queue_id or "").strip()
        if not target_id:
            return False
        with self._session_factory() as session:
            result = session.execute(
                sql_text(
                    """
                    UPDATE short_memory_queue
                    SET
                        extraction_status = :extraction_status,
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {
                    "id": target_id,
                    "extraction_status": normalized_status,
                },
            )
            session.commit()
            return bool(result.rowcount or 0)

    def list_recent_short_traces(self, *, memory_scope: str, limit: int = 60) -> list[dict]:
        """Return recent traces without mutating rows (created_at drives TTL and ordering)."""
        normalized_scope = (memory_scope or "global").strip() or "global"
        safe_limit = max(1, min(50000, int(limit)))
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT
                        id,
                        trace_id,
                        user_message,
                        assistant_response,
                        confidence_score,
                        retrieval_method,
                        created_at
                    FROM short_traces
                    WHERE memory_scope = :scope
                    ORDER BY created_at DESC
                    LIMIT :lim
                    """
                ),
                {"scope": normalized_scope, "lim": safe_limit},
            ).mappings().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "trace_id": str(row["trace_id"] or ""),
                    "user_message": str(row["user_message"] or ""),
                    "assistant_response": str(row["assistant_response"] or ""),
                    "confidence_score": float(row["confidence_score"] or 0.0),
                    "retrieval_method": str(row["retrieval_method"] or "none"),
                    "created_at": row["created_at"],
                }
            )
        return out

    def list_recent_short_traces_any_scope(self, *, limit: int = 60) -> list[dict]:
        safe_limit = max(1, min(50000, int(limit)))
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT
                        id,
                        trace_id,
                        memory_scope,
                        user_message,
                        assistant_response,
                        confidence_score,
                        retrieval_method,
                        created_at
                    FROM short_traces
                    ORDER BY created_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": safe_limit},
            ).mappings().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "trace_id": str(row["trace_id"] or ""),
                    "memory_scope": str(row["memory_scope"] or "global"),
                    "user_message": str(row["user_message"] or ""),
                    "assistant_response": str(row["assistant_response"] or ""),
                    "confidence_score": float(row["confidence_score"] or 0.0),
                    "retrieval_method": str(row["retrieval_method"] or "none"),
                    "created_at": row["created_at"],
                }
            )
        return out

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

    def get_short_queue_counts(self, *, memory_scope: str) -> dict[str, int]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT extraction_status, COUNT(*) AS cnt
                    FROM short_memory_queue
                    WHERE memory_scope = :scope
                    GROUP BY extraction_status
                    """
                ),
                {"scope": normalized_scope},
            ).mappings().all()
        out = {"pending": 0, "processed": 0, "rejected": 0}
        for row in rows:
            key = str(row.get("extraction_status") or "").strip().lower()
            if key in out:
                out[key] = int(row.get("cnt") or 0)
        return out

    def list_short_scope_resolution_events(self, *, memory_scope: str, limit: int = 20) -> list[dict]:
        normalized_scope = (memory_scope or "global").strip() or "global"
        safe_limit = max(1, min(100, int(limit)))
        with self._session_factory() as session:
            rows = session.execute(
                sql_text(
                    """
                    SELECT source, source_key, created_at
                    FROM short_scope_resolution_events
                    WHERE memory_scope = :scope
                    ORDER BY created_at DESC
                    LIMIT :lim
                    """
                ),
                {"scope": normalized_scope, "lim": safe_limit},
            ).mappings().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "source": str(row.get("source") or ""),
                    "source_key": str(row.get("source_key") or ""),
                    "created_at": (
                        row.get("created_at").isoformat()
                        if hasattr(row.get("created_at"), "isoformat")
                        else str(row.get("created_at") or "")
                    ),
                }
            )
        return out

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

    def count_short_traces(self, *, memory_scope: str) -> int:
        normalized_scope = (memory_scope or "global").strip() or "global"
        with self._session_factory() as session:
            value = session.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM short_traces
                    WHERE memory_scope = :scope
                    """
                ),
                {"scope": normalized_scope},
            ).scalar()
        return int(value or 0)

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

