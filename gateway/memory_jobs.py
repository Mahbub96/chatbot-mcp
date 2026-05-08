from __future__ import annotations

from memory import memory_service


def process_memory_task(payload: dict) -> None:
    """
    RQ job handler for memory persistence.
    """
    memory_scope = str(payload.get("memory_scope") or "global").strip() or "global"
    user_text = str(payload.get("user_text") or "").strip()
    assistant_text = str(payload.get("assistant_text") or "").strip()
    if not user_text and not assistant_text:
        return
    memory_service.maybe_store_from_user_turn(text=user_text, memory_scope=memory_scope)
    memory_service.maybe_store_from_assistant_turn(text=assistant_text, memory_scope=memory_scope)

