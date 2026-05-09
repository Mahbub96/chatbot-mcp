from __future__ import annotations

from typing import Any

from memory.service import memory_service


class ShortTermMemoryService:
    """Ephemeral layer: `short_traces`, retrieval logs, and `short_memory_queue` staging.

    Promotion to durable memory (`memory_records`, embeddings, long_term entities) goes through
    `MemoryService.maybe_store_from_*` / `log_chat_trace`, not through this facade alone.
    """

    def store_trace(
        self,
        *,
        request_id: str,
        memory_scope: str,
        user_text: str,
        assistant_text: str,
        model: str,
        retrieved_items: list[dict[str, Any]] | None = None,
        had_error: bool = False,
    ) -> None:
        memory_service.log_chat_trace(
            request_id=request_id,
            memory_scope=memory_scope,
            user_text=user_text,
            assistant_text=assistant_text,
            model=model,
            retrieved_items=retrieved_items,
            had_error=had_error,
        )

