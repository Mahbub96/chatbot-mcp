from __future__ import annotations


def is_exact_duplicate(text: str, candidates: list[str]) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any((c or "").strip().lower() == normalized for c in candidates)

