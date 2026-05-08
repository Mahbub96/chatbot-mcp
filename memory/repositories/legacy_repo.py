from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from typing import Any

from sqlalchemy import delete, func, select, text as sql_text

from memory.models import ChatTraceRecord, MemoryRecord


class LegacyRepositoryMixin:
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

    def count_by_sources(self, *, memory_scope: str, sources: list[str]) -> int:
        memory_scope = (memory_scope or "global").strip() or "global"
        normalized_sources = [s.strip().lower() for s in (sources or []) if isinstance(s, str) and s.strip()]
        if not normalized_sources:
            return 0
        with self._session_factory() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(MemoryRecord)
                    .where(
                        MemoryRecord.memory_scope == memory_scope,
                        MemoryRecord.source.in_(normalized_sources),
                    )
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

