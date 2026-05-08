from __future__ import annotations

import hashlib
import math
import re


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

