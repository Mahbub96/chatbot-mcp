from __future__ import annotations


class BaseRepositoryMixin:
    def __init__(self, session_factory):
        self._session_factory = session_factory

