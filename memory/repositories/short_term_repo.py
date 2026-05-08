from __future__ import annotations

from memory.repository import MemoryRepository


class ShortTermMemoryRepository:
    """Thin repository adapter for short-term trace writes."""

    def __init__(self, repo: MemoryRepository):
        self._repo = repo

    @property
    def raw(self) -> MemoryRepository:
        return self._repo

