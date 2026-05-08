from __future__ import annotations

from memory.repository import MemoryRepository


class LongTermMemoryRepository:
    """Thin repository adapter for durable memory reads/writes."""

    def __init__(self, repo: MemoryRepository):
        self._repo = repo

    @property
    def raw(self) -> MemoryRepository:
        return self._repo

