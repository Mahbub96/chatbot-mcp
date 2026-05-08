from __future__ import annotations

from typing import TypedDict, Any


class RetrievalItem(TypedDict):
    id: str
    score: float
    text: str
    source: str
    category: str
    importance: float
    confidence: float
    structured_data: dict[str, Any]
    created_at: str


class RetrievalQuery(TypedDict, total=False):
    query: str
    memory_scope: str
    limit: int
    source_filter: str
    category_filter: str

