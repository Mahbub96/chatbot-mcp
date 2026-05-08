from __future__ import annotations

import json
import os
from typing import Any

import faiss
import numpy as np

from config import MEMORY_VECTOR_PATH


class FaissVectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.base_path = MEMORY_VECTOR_PATH
        os.makedirs(self.base_path, exist_ok=True)
        self.index_path = os.path.join(self.base_path, "memory.index")
        self.meta_path = os.path.join(self.base_path, "memory.meta.json")
        self.index = faiss.IndexFlatIP(dim)
        self.ids: list[str] = []
        self.scopes: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self.index_path):
                self.index = faiss.read_index(self.index_path)
            if os.path.exists(self.meta_path):
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                    self.ids = list(obj.get("ids", []))
                    self.scopes = list(obj.get("scopes", []))
        except Exception:
            self.index = faiss.IndexFlatIP(self.dim)
            self.ids = []
            self.scopes = []

    def _persist(self) -> None:
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump({"ids": self.ids, "scopes": self.scopes}, f)

    def add(self, *, memory_id: str, memory_scope: str, embedding: list[float]) -> None:
        vec = np.array([embedding], dtype="float32")
        self.index.add(vec)
        self.ids.append(memory_id)
        self.scopes.append(memory_scope)
        self._persist()

    def search(self, *, memory_scope: str, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        if self.index.ntotal == 0:
            return []
        query = np.array([embedding], dtype="float32")
        k = min(max(1, top_k * 4), self.index.ntotal)
        distances, indices = self.index.search(query, k)
        results: list[dict[str, Any]] = []
        for idx, score in zip(indices[0], distances[0]):
            if idx < 0 or idx >= len(self.ids):
                continue
            if self.scopes[idx] != memory_scope:
                continue
            results.append({"id": self.ids[idx], "score": float(score)})
            if len(results) >= top_k:
                break
        return results

    def rebuild(self, *, rows: list[dict[str, Any]], embed_fn) -> None:
        self.index = faiss.IndexFlatIP(self.dim)
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

