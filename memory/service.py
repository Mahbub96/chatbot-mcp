from __future__ import annotations

import re
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

    def list_profile_facts(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repo.list(memory_scope=memory_scope, limit=500, offset=0)
        facts = []
        for r in rows:
            if (r.source or "").strip().lower() != "profile_fact":
                continue
            facts.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "importance": r.importance,
                    "created_at": r.created_at.isoformat(),
                }
            )
            if len(facts) >= max(1, limit):
                break
        return facts

    def list_profile_memories(self, *, memory_scope: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repo.list(memory_scope=memory_scope, limit=500, offset=0)
        items = []
        for r in rows:
            source = (r.source or "").strip().lower()
            if source not in {"profile_fact", "profile_full"}:
                continue
            items.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "importance": r.importance,
                    "created_at": r.created_at.isoformat(),
                }
            )
            if len(items) >= max(1, limit):
                break
        return items

    def list_profile_facts_any_scope(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repo.list_all(limit=5000, offset=0)
        facts = []
        for r in rows:
            if (r.source or "").strip().lower() != "profile_fact":
                continue
            facts.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "importance": r.importance,
                    "created_at": r.created_at.isoformat(),
                }
            )
            if len(facts) >= max(1, limit):
                break
        return facts

    def list_profile_memories_any_scope(self, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.repo.list_all(limit=5000, offset=0)
        items = []
        for r in rows:
            source = (r.source or "").strip().lower()
            if source not in {"profile_fact", "profile_full", "chat_user", "chat_assistant", "manual"}:
                continue
            items.append(
                {
                    "id": r.id,
                    "memory_scope": r.memory_scope,
                    "text": r.text,
                    "source": r.source,
                    "importance": r.importance,
                    "created_at": r.created_at.isoformat(),
                }
            )
            if len(items) >= max(1, limit):
                break
        return items

    def latest_profile_full(self, *, memory_scope: str = "global") -> dict[str, Any] | None:
        rows = self.repo.list(memory_scope=memory_scope, limit=500, offset=0)
        for r in rows:
            if (r.source or "").strip().lower() != "profile_full":
                continue
            return {
                "id": r.id,
                "memory_scope": r.memory_scope,
                "text": r.text,
                "source": r.source,
                "importance": r.importance,
                "created_at": r.created_at.isoformat(),
            }
        return None

    def latest_profile_full_any_scope(self) -> dict[str, Any] | None:
        rows = self.repo.list_all(limit=5000, offset=0)
        for r in rows:
            if (r.source or "").strip().lower() != "profile_full":
                continue
            return {
                "id": r.id,
                "memory_scope": r.memory_scope,
                "text": r.text,
                "source": r.source,
                "importance": r.importance,
                "created_at": r.created_at.isoformat(),
            }
        return None

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
        # For long/structured text, store extracted concise facts instead of raw blob.
        if self._looks_like_structured_text(t):
            self._store_structured_facts(t, memory_scope=memory_scope)
            return
        if len(t) > 800:
            return
        self.add_memory(text=t, memory_scope=memory_scope, source="chat_user", importance=0.6)

    def maybe_store_from_assistant_turn(self, *, text: str, memory_scope: str = "global") -> None:
        t = (text or "").strip()
        if len(t) < 8:
            return
        lower = t.lower()
        # Avoid storing uncertainty/meta chatter as durable memory.
        if any(
            sig in lower
            for sig in (
                "i couldn't find",
                "not fully verified",
                "please share",
                "i don't have",
                "saved fact:",
                "possible memory",
            )
        ):
            return
        if len(t) > 1200:
            return
        self.add_memory(text=t, memory_scope=memory_scope, source="chat_assistant", importance=0.45)

    def _looks_like_structured_text(self, text: str) -> bool:
        lower = (text or "").lower()
        latex_signals = ("\\begin{document}", "\\section", "\\subsection", "\\textbf", "\\item", "\\cv")
        structure_signals = ("education", "experience", "skills", "email", "resume", "curriculum vitae", "profile")
        signal_count = sum(1 for s in latex_signals if s in lower) + sum(1 for s in structure_signals if s in lower)
        return signal_count >= 2 or len(text) > 1200

    def _store_structured_facts(self, text: str, *, memory_scope: str) -> None:
        # Store full original structured text once for richer downstream use-cases
        # (e.g. regenerate CV, section-aware edits) while still indexing concise facts.
        self._store_full_profile_text(text, memory_scope=memory_scope)

        facts = self._extract_structured_facts(text)
        for fact_text in facts:
            self.add_memory(
                text=fact_text,
                memory_scope=memory_scope,
                source="profile_fact",
                importance=0.95,
            )

    def _store_full_profile_text(self, text: str, *, memory_scope: str) -> None:
        raw = (text or "").strip()
        if not raw:
            return
        normalized = re.sub(r"\s+", " ", raw).strip().lower()
        recent = self.repo.list(memory_scope=memory_scope, limit=50, offset=0)
        for row in recent:
            if (row.source or "").strip().lower() != "profile_full":
                continue
            existing = re.sub(r"\s+", " ", (row.text or "").strip()).lower()
            if existing == normalized:
                return
        self.add_memory(
            text=raw,
            memory_scope=memory_scope,
            source="profile_full",
            importance=0.98,
        )

    def _extract_structured_facts(self, text: str) -> list[str]:
        out: list[str] = []
        src = text or ""
        normalized = self._normalize_document_text(src)

        # Capture common resume headline name from LaTeX centered header.
        for m in re.finditer(r"\\color\{headcolor\}\s*([^}\\]{3,80})\}\s*\\\\", src):
            candidate = m.group(1).strip()
            if re.search(r"[A-Za-z]", candidate):
                out.append(f"name: {candidate}")
                break

        # Generic "key: value" facts (works for profile, project specs, metadata etc.)
        for m in re.finditer(r"(?im)^\s*([A-Za-z][A-Za-z0-9 _/\-]{1,40})\s*[:\-]\s*([^\n]{2,180})\s*$", normalized):
            key = m.group(1).strip().lower().replace("  ", " ")
            value = m.group(2).strip()
            if self._is_valid_fact_pair(key, value):
                out.append(f"{key}: {value}")

        # Generic first-person statements: "my X is Y"
        for m in re.finditer(r"(?im)\bmy\s+([a-z][a-z0-9 _/\-]{1,40})\s+is\s+([^.\n]{2,160})", normalized):
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            if self._is_valid_fact_pair(key, value):
                out.append(f"{key}: {value}")

        # Keep useful special entities genericly (e.g., emails) without domain-specific assumptions.
        for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", normalized):
            out.append(f"email: {email.strip()}")
        for website in re.findall(r"https?://[^\s}]+|www\.[^\s}]+", normalized):
            site = website.strip().rstrip(".,;)")
            if site:
                out.append(f"website: {site}")

        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for item in out:
            key = item.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:10]

    def _normalize_document_text(self, text: str) -> str:
        s = text
        # Convert common latex commands into plain-text-like lines.
        s = re.sub(r"\\([A-Za-z]+)\{([^}]*)\}", r"\1: \2", s)
        s = re.sub(r"\\item\s+", "- ", s)
        s = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", s)
        s = re.sub(r"[{}]", " ", s)
        return re.sub(r"\s+\n", "\n", s)

    def _is_valid_fact_pair(self, key: str, value: str) -> bool:
        key = (key or "").strip().lower()
        value = (value or "").strip()
        if not key or not value:
            return False
        if len(key) > 40 or len(value) > 180:
            return False
        bad_keys = {
            "section",
            "subsection",
            "documentclass",
            "begin",
            "end",
            "item",
            "usepackage",
            "definecolor",
            "titleformat",
            "titlespacing",
            "setlist",
            "newcommand",
            "href",
            "color",
            "entryheader",
            "entrysubheader",
            "skillrow",
            "promotionnote",
            "pagestyle",
            "hypersetup",
        }
        if key in bad_keys:
            return False
        if "\\" in key or "{" in key or "}" in key:
            return False
        if key.startswith("%"):
            return False
        # Keep profile-like facts, avoid technical/style directives.
        allowed_prefixes = (
            "name",
            "full name",
            "email",
            "phone",
            "mobile",
            "website",
            "linkedin",
            "github",
            "location",
            "education",
            "university",
            "experience",
            "skills",
            "summary",
            "objective",
        )
        if not key.startswith(allowed_prefixes):
            return False
        bad_values = ("### task:", "<chat_history>", "guidelines:", "json format:")
        lowered_value = value.lower()
        if any(sig in lowered_value for sig in bad_values):
            return False
        if "\\usepackage" in lowered_value or "\\definecolor" in lowered_value:
            return False
        return True

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

