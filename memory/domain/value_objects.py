from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfidenceScore:
    value: float

    def normalized(self) -> float:
        return max(0.0, min(1.0, float(self.value)))


@dataclass(frozen=True, slots=True)
class MemoryScope:
    value: str

    def normalized(self) -> str:
        text = (self.value or "").strip()
        return text or "global"

