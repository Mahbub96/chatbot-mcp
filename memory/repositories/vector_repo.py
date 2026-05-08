from __future__ import annotations


class VectorRepository:
    """Adapter for vector store operations."""

    def __init__(self, vector_store):
        self._vector_store = vector_store

    @property
    def raw(self):
        return self._vector_store

