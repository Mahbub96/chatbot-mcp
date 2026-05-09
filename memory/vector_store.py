from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

import faiss
import numpy as np

from config import (
    MEMORY_SQLITE_URL,
    MEMORY_VECTOR_HNSW_EF_SEARCH,
    MEMORY_VECTOR_HNSW_M,
    MEMORY_VECTOR_INDEX_TYPE,
    MEMORY_VECTOR_PATH,
    MEMORY_VECTOR_PERSIST_EVERY,
)

SQLITE_URL_PREFIX = "sqlite:///"


class FaissVectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.base_path = MEMORY_VECTOR_PATH
        os.makedirs(self.base_path, exist_ok=True)
        self.index_path = os.path.join(self.base_path, "memory.index")
        self.meta_path = os.path.join(self.base_path, "memory.meta.json")
        self._sqlite_db_path = self._resolve_sqlite_db_path()
        self.index = self._build_index()
        self.ids: list[str] = []
        self.scopes: list[str] = []
        self._pending_writes = 0
        self._load()

    def _build_index(self):
        index_type = MEMORY_VECTOR_INDEX_TYPE
        if index_type == "flat":
            return faiss.IndexFlatIP(self.dim)
        # Default to HNSW for faster-than-linear ANN search at scale.
        index = faiss.IndexHNSWFlat(self.dim, MEMORY_VECTOR_HNSW_M, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efSearch = MEMORY_VECTOR_HNSW_EF_SEARCH
        return index

    def _load(self) -> None:
        try:
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
            if self._sqlite_db_path:
                self.ids, self.scopes = self._load_meta_from_sqlite()
                if not self.ids:
                    # Backward-compatible migration from legacy JSON metadata.
                    self.ids, self.scopes = self._load_meta_from_json()
                    if self.ids:
                        self._persist_meta_to_sqlite()
            else:
                self.ids, self.scopes = self._load_meta_from_json()
        except Exception:
            self.index = self._build_index()
            self.ids = []
            self.scopes = []

    def _persist(self) -> None:
        faiss.write_index(self.index, self.index_path)
        if self._sqlite_db_path:
            self._persist_meta_to_sqlite()
            return
        self._persist_meta_to_json()

    def _resolve_sqlite_db_path(self) -> str | None:
        if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
            return None
        db_path = MEMORY_SQLITE_URL.replace(SQLITE_URL_PREFIX, "", 1)
        return db_path or None

    def _load_meta_from_json(self) -> tuple[list[str], list[str]]:
        if not os.path.exists(self.meta_path):
            return [], []
        with open(self.meta_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return list(obj.get("ids", [])), list(obj.get("scopes", []))

    def _persist_meta_to_json(self) -> None:
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump({"ids": self.ids, "scopes": self.scopes}, f)

    def _ensure_meta_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_vector_meta (
                position INTEGER PRIMARY KEY,
                memory_id TEXT NOT NULL,
                memory_scope TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_memory_vector_meta_scope ON memory_vector_meta(memory_scope)")

    def _load_meta_from_sqlite(self) -> tuple[list[str], list[str]]:
        if not self._sqlite_db_path:
            return [], []
        conn = sqlite3.connect(self._sqlite_db_path)
        try:
            self._ensure_meta_table(conn)
            rows = conn.execute(
                "SELECT memory_id, memory_scope FROM memory_vector_meta ORDER BY position ASC"
            ).fetchall()
        finally:
            conn.close()
        ids = [str(row[0]) for row in rows]
        scopes = [str(row[1]) for row in rows]
        return ids, scopes

    def _persist_meta_to_sqlite(self) -> None:
        if not self._sqlite_db_path:
            return
        conn = sqlite3.connect(self._sqlite_db_path)
        try:
            self._ensure_meta_table(conn)
            conn.execute("DELETE FROM memory_vector_meta")
            payload = [(idx, memory_id, self.scopes[idx]) for idx, memory_id in enumerate(self.ids)]
            conn.executemany(
                "INSERT INTO memory_vector_meta(position, memory_id, memory_scope) VALUES (?, ?, ?)",
                payload,
            )
            conn.commit()
        finally:
            conn.close()

    def add(self, *, memory_id: str, memory_scope: str, embedding: list[float]) -> None:
        vec = np.array([embedding], dtype="float32")
        self.index.add(vec)
        self.ids.append(memory_id)
        self.scopes.append(memory_scope)
        self._pending_writes += 1
        if self._pending_writes >= MEMORY_VECTOR_PERSIST_EVERY:
            self._persist()
            self._pending_writes = 0

    def _collect_scoped_candidates(
        self,
        *,
        memory_scope: str,
        indices: np.ndarray,
        distances: np.ndarray,
        shortlist_target: int,
    ) -> list[tuple[int, float]]:
        scoped_candidates: list[tuple[int, float]] = []
        for idx, score in zip(indices, distances):
            if idx < 0 or idx >= len(self.ids):
                continue
            if self.scopes[idx] != memory_scope:
                continue
            scoped_candidates.append((int(idx), float(score)))
            if len(scoped_candidates) >= shortlist_target:
                break
        return scoped_candidates

    def _rerank_exact(self, *, query_vec: np.ndarray, candidates: list[tuple[int, float]], top_k: int) -> list[dict[str, Any]]:
        reranked: list[tuple[str, float]] = []
        for idx, _ in candidates:
            try:
                vec = self.index.reconstruct(idx)
            except Exception:
                continue
            exact_score = float(np.dot(query_vec, vec))
            reranked.append((self.ids[idx], exact_score))
        if not reranked:
            return []
        reranked.sort(key=lambda x: x[1], reverse=True)
        return [{"id": item_id, "score": score} for item_id, score in reranked[:top_k]]

    def search(self, *, memory_scope: str, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        if self.index.ntotal == 0:
            return []
        query = np.array([embedding], dtype="float32")
        # HNSW shortlist stage (fast): pull extra candidates, then re-rank exactly.
        shortlist_target = max(20, top_k * 4)
        candidate_factor = 8 if MEMORY_VECTOR_INDEX_TYPE != "flat" else 4
        k = min(max(shortlist_target, top_k * candidate_factor), self.index.ntotal)
        distances, indices = self.index.search(query, k)
        scoped_candidates = self._collect_scoped_candidates(
            memory_scope=memory_scope,
            indices=indices[0],
            distances=distances[0],
            shortlist_target=shortlist_target,
        )

        if not scoped_candidates:
            return []

        # Accuracy stage: exact inner-product re-rank over shortlist.
        if MEMORY_VECTOR_INDEX_TYPE != "flat":
            reranked = self._rerank_exact(query_vec=query[0], candidates=scoped_candidates, top_k=top_k)
            if reranked:
                return reranked

        # Fallback path (flat index or reconstruction unavailable).
        return [{"id": self.ids[idx], "score": score} for idx, score in scoped_candidates[:top_k]]

    def rebuild(self, *, rows: list[dict[str, Any]], embed_fn) -> None:
        self.index = self._build_index()
        self.ids = []
        self.scopes = []
        vectors: list[list[float]] = []
        for row in rows:
            vectors.append(embed_fn(row["text"]))
            self.ids.append(row["id"])
            self.scopes.append(row["memory_scope"])
        if vectors:
            arr = np.array(vectors, dtype="float32")
            self.index.add(arr)
        self._persist()
        self._pending_writes = 0

    def flush(self) -> None:
        if self._pending_writes <= 0:
            return
        self._persist()
        self._pending_writes = 0

