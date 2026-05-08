from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MemoryEntity:
    """Domain object for durable memory."""

    id: str
    memory_scope: str
    text: str
    source: str
    category: str
    importance: float
    confidence: float
    created_at: datetime
    structured_data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatTraceEntity:
    """Domain object for short-term memory traces."""

    id: str
    request_id: str
    memory_scope: str
    user_text: str
    assistant_text: str
    model: str
    confidence: float
    created_at: datetime
    retrieval_summary: dict[str, Any] = field(default_factory=dict)

