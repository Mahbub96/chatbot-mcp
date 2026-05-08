from __future__ import annotations

from typing import Any

from config import MEMORY_AUTO_STORE, MEMORY_MAX_ITEMS, MEMORY_MIN_SCORE, MEMORY_TOP_K
from memory.db import create_engine_and_session
from memory.embedder import HashEmbedder
from memory.repository import MemoryRepository
from memory.vector_store import FaissVectorStore


class MemoryService:
    def __init__(self):
        _, session_factory = create_engine_and_session()
        self.repo = MemoryRepository(session_factory)
        self.embedder = HashEmbedder()
        self.vector = FaissVectorStore(dim=self.embedder.dim)

    def add_memory(
        self,
        *,
        text: str,
        memory_scope: str = "global",
        source: str = "chat",
        importance: float = 0.5,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not text:
            return {"success": False, "error": "text cannot be empty"}

        # Exact dedupe on recent scope items.
        recent = self.repo.list(memory_scope=memory_scope, limit=50, offset=0)
        if any((r.text or "").strip().lower() == text.lower() for r in recent):
            return {"success": True, "deduped": True}

        row = self.repo.create(
            memory_scope=memory_scope,
            text=text,
            source=source,
            importance=importance,
        )
        self.vector.add(
            memory_id=row.id,
            memory_scope=row.memory_scope,
            embedding=self.embedder.embed(row.text),
        )

        self._prune_scope_if_needed(memory_scope)

        return {
            "success": True,
            "id": row.id,
            "memory_scope": row.memory_scope,
            "text": row.text,
            "source": row.source,
            "importance": row.importance,
            "created_at": row.created_at.isoformat(),
        }

    def search(self, *, query: str, memory_scope: str = "global", limit: int | None = None) -> list[dict[str, Any]]:
        query = (query or "").strip()
        memory_scope = (memory_scope or "global").strip() or "global"
        if not query:
            return []
        top_k = max(1, int(limit or MEMORY_TOP_K))
        candidates = self.vector.search(
            memory_scope=memory_scope,
            embedding=self.embedder.embed(query),
            top_k=top_k,
        )
        results: list[dict[str, Any]] = []
        for item in candidates:
            if item["score"] < MEMORY_MIN_SCORE:
                continue
            row = self.repo.get(item["id"])
            if not row:
                continue
            results.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": item["score"],
                    "source": row.source,
                    "importance": row.importance,
                    "created_at": row.created_at.isoformat(),
                }
            )
        if results:
            return results

        # Fallback lexical retrieval when vector score threshold misses useful facts.
        query_terms = {t for t in query.lower().split() if t}
        lexical: list[dict[str, Any]] = []
        for row in self.repo.list(memory_scope=memory_scope, limit=500, offset=0):
            terms = {t for t in (row.text or "").lower().split() if t}
            overlap = len(query_terms.intersection(terms))
            if overlap <= 0:
                continue
            lexical.append(
                {
                    "id": row.id,
                    "text": row.text,
                    "score": float(overlap),
                    "source": row.source,
                    "importance": row.importance,
                    "created_at": row.created_at.isoformat(),
                }
            )
        lexical.sort(key=lambda x: x["score"], reverse=True)
        return lexical[:top_k]

    def list_items(self, *, memory_scope: str = "global", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.repo.list(memory_scope=memory_scope, limit=limit, offset=offset)
        return [
            {
                "id": r.id,
                "memory_scope": r.memory_scope,
                "text": r.text,
                "source": r.source,
                "importance": r.importance,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    def delete_item(self, *, item_id: str, memory_scope: str = "global") -> dict[str, Any]:
        ok = self.repo.delete(memory_id=item_id, memory_scope=memory_scope)
        if not ok:
            return {"success": False, "error": "memory not found"}
        self.reindex(memory_scope=memory_scope)
        return {"success": True, "id": item_id}

    def reindex(self, *, memory_scope: str = "global") -> dict[str, Any]:
        rows = self.repo.list(memory_scope=memory_scope, limit=100000, offset=0)
        payload = [{"id": r.id, "memory_scope": r.memory_scope, "text": r.text} for r in rows]
        self.vector.rebuild(rows=payload, embed_fn=self.embedder.embed)
        return {"success": True, "count": len(rows), "memory_scope": memory_scope}

    def maybe_store_from_user_turn(self, *, text: str, memory_scope: str = "global") -> None:
        if not MEMORY_AUTO_STORE:
            return
        t = (text or "").strip()
        if len(t) < 8:
            return
        if t.endswith("?") or t.endswith("؟"):
            return
        lowered = t.lower()
        if "### task:" in lowered or "<chat_history>" in lowered:
            return
        if len(t) > 800:
            return
        self.add_memory(text=t, memory_scope=memory_scope, source="chat_user", importance=0.6)

    def _prune_scope_if_needed(self, memory_scope: str) -> None:
        rows = self.repo.list(memory_scope=memory_scope, limit=100000, offset=0)
        if len(rows) <= MEMORY_MAX_ITEMS:
            return
        # Keep newest MEMORY_MAX_ITEMS; remove older records.
        to_remove = rows[MEMORY_MAX_ITEMS:]
        for row in to_remove:
            self.repo.delete(memory_id=row.id, memory_scope=memory_scope)
        self.reindex(memory_scope=memory_scope)


memory_service = MemoryService()

