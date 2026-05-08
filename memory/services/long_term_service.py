from __future__ import annotations

from typing import Any

from memory.service import memory_service


class LongTermMemoryService:
    """Handles durable memory storage and retrieval."""

    def store(self, **kwargs) -> dict[str, Any]:
        return memory_service.add_memory(**kwargs)

    def search(
        self,
        *,
        query: str,
        memory_scope: str,
        limit: int,
        source_filter: str | None = None,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        return memory_service.search(
            query=query,
            memory_scope=memory_scope,
            limit=limit,
            source_filter=source_filter,
            category_filter=category_filter,
        )

    def maybe_store_user_turn(self, *, text: str, memory_scope: str) -> None:
        memory_service.maybe_store_from_user_turn(text=text, memory_scope=memory_scope)

    def maybe_store_assistant_turn(self, *, text: str, memory_scope: str) -> None:
        memory_service.maybe_store_from_assistant_turn(text=text, memory_scope=memory_scope)

