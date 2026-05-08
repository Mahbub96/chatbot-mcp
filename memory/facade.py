from __future__ import annotations

from typing import Any

from memory import memory_service
from memory.services.extraction_service import ExtractionService
from memory.services.long_term_service import LongTermMemoryService
from memory.services.retrieval_service import RetrievalService
from memory.services.short_term_service import ShortTermMemoryService


class MemoryFacade:
    """
    Single entry point for memory operations used by gateway.
    """

    def __init__(self) -> None:
        self.short_term = ShortTermMemoryService()
        self.long_term = LongTermMemoryService()
        self.retrieval = RetrievalService()
        self.extraction = ExtractionService()

    def store_short_memory(self, *, request_id: str, memory_scope: str, user_text: str, assistant_text: str, model: str, retrieved_items: list[dict[str, Any]] | None = None, had_error: bool = False) -> None:
        self.short_term.store_trace(
            request_id=request_id,
            memory_scope=memory_scope,
            user_text=user_text,
            assistant_text=assistant_text,
            model=model,
            retrieved_items=retrieved_items,
            had_error=had_error,
        )

    def extract_long_memory(self, *, text: str) -> dict[str, Any]:
        return self.extraction.classify(text)

    def retrieve_memory(self, *, query: str, memory_scope: str, limit: int = 5) -> list[dict[str, Any]]:
        return self.retrieval.retrieve(query=query, memory_scope=memory_scope, limit=limit)

    # Backward-compatible pass-through methods used by existing modules.
    def add_memory(self, **kwargs) -> dict[str, Any]:
        return memory_service.add_memory(**kwargs)

    def search(self, **kwargs) -> list[dict[str, Any]]:
        return memory_service.search(**kwargs)

    def list_items(self, **kwargs) -> list[dict[str, Any]]:
        return memory_service.list_items(**kwargs)

    def reindex(self, **kwargs) -> dict[str, Any]:
        return memory_service.reindex(**kwargs)

    def delete_item(self, **kwargs) -> dict[str, Any]:
        return memory_service.delete_item(**kwargs)

    def __getattr__(self, name: str):
        # Compatibility bridge for existing gateway code paths.
        return getattr(memory_service, name)


memory_facade = MemoryFacade()

