from __future__ import annotations

import hashlib
import math
import os
import re
import time
from collections import OrderedDict

import httpx

from config import EMBEDDING_BASE_URL, EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDING_TIMEOUT_SECONDS


class HashEmbedder:
    def __init__(self, dim: int = 256):
        self.dim = dim

    def _tokenize(self, text: str) -> list[str]:
        if not isinstance(text, str):
            return []
        return re.findall(r"\w+", text.lower(), flags=re.UNICODE)

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec

        for tok in tokens:
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if (digest[4] % 2 == 0) else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vec[idx] += sign * weight

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


class NvidiaEmbeddingService:
    """
    Real embedding client (OpenAI-compatible embeddings API).

    Falls back to deterministic hash embeddings when upstream is unavailable
    to keep the memory pipeline resilient in local/dev environments.
    """

    def __init__(self, *, dim: int = EMBEDDING_DIM):
        self.dim = dim
        self._fallback = HashEmbedder(dim=dim)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = 2000
        self._api_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
        self._disabled = not bool(self._api_key)
        self._cooldown_seconds = max(30, int(os.getenv("EMBEDDING_FAILURE_COOLDOWN_SECONDS") or "300"))
        self._disabled_until = 0.0
        self._client = None
        if not self._disabled:
            self._client = httpx.Client(
                timeout=httpx.Timeout(EMBEDDING_TIMEOUT_SECONDS),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def embed(self, text: str) -> list[float]:
        vec, _meta = self.embed_with_meta(text)
        return vec

    def embed_with_meta(self, text: str) -> tuple[list[float], dict[str, object]]:
        normalized = (text or "").strip()
        if not normalized:
            return [0.0] * self.dim, {"provider": "empty", "reason": "empty_input"}
        cached = self._cache_get(normalized)
        if cached is not None:
            return cached, {"provider": "cache", "reason": "cache_hit"}
        vec, meta = self._embed_via_api(normalized)
        if vec is None:
            vec = self._fallback.embed(normalized)
            fallback_reason = str(meta.get("reason") or "api_unavailable")
            meta = {
                "provider": "fallback",
                "reason": fallback_reason,
            }
        self._cache_set(normalized, vec)
        return vec, meta

    def _embed_via_api(self, text: str) -> tuple[list[float] | None, dict[str, object]]:
        if self._disabled or self._client is None:
            return None, {"provider": "api", "reason": "disabled_no_api_key"}
        if self._disabled_until and time.time() < self._disabled_until:
            return None, {"provider": "api", "reason": "cooldown_active"}
        payload = {
            "model": EMBEDDING_MODEL,
            "input": text,
            "encoding_format": "float",
        }
        try:
            res = self._client.post(EMBEDDING_BASE_URL, json=payload)
            if res.status_code != 200:
                if 400 <= res.status_code < 500:
                    self._disabled_until = time.time() + self._cooldown_seconds
                return None, {"provider": "api", "reason": f"http_{int(res.status_code)}", "status_code": int(res.status_code)}
            obj = res.json()
            data = obj.get("data")
            if not isinstance(data, list) or not data:
                return None, {"provider": "api", "reason": "invalid_response_data"}
            embedding = data[0].get("embedding")
            if not isinstance(embedding, list) or not embedding:
                return None, {"provider": "api", "reason": "invalid_response_embedding"}
            vec = [float(x) for x in embedding]
            if len(vec) != self.dim:
                vec = self._fit_dim(vec)
            return self._normalize(vec), {"provider": "api", "reason": "ok", "status_code": 200}
        except Exception:
            self._disabled_until = time.time() + self._cooldown_seconds
            return None, {"provider": "api", "reason": "exception"}

    def _fit_dim(self, vec: list[float]) -> list[float]:
        if len(vec) == self.dim:
            return vec
        if len(vec) > self.dim:
            return vec[: self.dim]
        return vec + ([0.0] * (self.dim - len(vec)))

    def _normalize(self, vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def _cache_get(self, key: str) -> list[float] | None:
        value = self._cache.get(key)
        if value is None:
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_set(self, key: str, value: list[float]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

