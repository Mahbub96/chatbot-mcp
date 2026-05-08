from __future__ import annotations

from memory.repositories.base_repo import BaseRepositoryMixin
from memory.repositories.legacy_repo import LegacyRepositoryMixin
from memory.repositories.long_term_repo import LongTermRepositoryMixin
from memory.repositories.short_term_repo import ShortTermRepositoryMixin


class MemoryRepository(
    BaseRepositoryMixin,
    LegacyRepositoryMixin,
    ShortTermRepositoryMixin,
    LongTermRepositoryMixin,
):
    """Composed repository split by concern for maintainability."""

    pass
