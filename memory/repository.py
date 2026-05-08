from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select

from memory.models import MemoryRecord


class MemoryRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create(self, *, memory_scope: str, text: str, source: str, importance: float) -> MemoryRecord:
        memory = MemoryRecord(
            id=str(uuid.uuid4()),
            user_id=(memory_scope or "global").strip() or "global",
            memory_scope=(memory_scope or "global").strip() or "global",
            text=text.strip(),
            source=source or "chat",
            importance=max(0.0, min(1.0, float(importance))),
            created_at=datetime.utcnow(),
        )
        with self._session_factory() as session:
            session.add(memory)
            session.commit()
            session.refresh(memory)
        return memory

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

    def count(self, *, memory_scope: str) -> int:
        return len(self.list(memory_scope=memory_scope, limit=100000, offset=0))

