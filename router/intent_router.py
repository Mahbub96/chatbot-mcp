from __future__ import annotations

from dataclasses import dataclass

VALID_INTENTS = {"direct", "memory_db", "internet_search", "tool", "llm"}


@dataclass(frozen=True)
class IntentRoute:
    route: str
    allow_tool: bool
    allow_llm: bool


def route_intent(user_text: str, *, has_memory_hits: bool, has_multimodal_input: bool) -> IntentRoute:
    normalized = (user_text or "").strip().lower()
    if not normalized:
        return IntentRoute(route="direct", allow_tool=False, allow_llm=True)
    if has_multimodal_input:
        return IntentRoute(route="llm", allow_tool=False, allow_llm=True)
    if any(token in normalized for token in ("search ", "google ", "internet ", "web ")):
        return IntentRoute(route="internet_search", allow_tool=True, allow_llm=True)
    if has_memory_hits:
        return IntentRoute(route="memory_db", allow_tool=False, allow_llm=True)
    if any(token in normalized for token in ("read file", "write file", "delete file", "pwd", "current directory")):
        return IntentRoute(route="tool", allow_tool=True, allow_llm=True)
    return IntentRoute(route="llm", allow_tool=False, allow_llm=True)


def normalize_intent_suggestion(raw: str) -> str | None:
    normalized = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in VALID_INTENTS:
        return normalized
    return None
