from __future__ import annotations

from typing import Any
import logging

from memory.service import memory_service

logger = logging.getLogger(__name__)

try:
    from pydantic import BaseModel, Field
    from langchain_core.runnables import RunnableLambda
except Exception:  # pragma: no cover - optional dependency path
    BaseModel = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    RunnableLambda = None  # type: ignore[assignment]


if BaseModel is not None:
    class ExtractionResult(BaseModel):
        should_store: bool = False
        importance_score: float = 0.0
        category: str = "general"
        structured_data: dict[str, str] = Field(default_factory=dict)


class ExtractionService:
    """Extraction/classification facade around existing memory service."""

    def __init__(self) -> None:
        self._chain = self._build_chain()

    def _build_chain(self):
        if RunnableLambda is None or BaseModel is None:
            return None

        def _normalize(text: str) -> str:
            return (text or "").strip()

        def _classify(text: str) -> dict[str, Any]:
            return memory_service.classify_memory_candidate(text)

        def _validate(payload: dict[str, Any]) -> dict[str, Any]:
            parsed = ExtractionResult(**(payload or {}))
            return parsed.model_dump()

        return RunnableLambda(_normalize) | RunnableLambda(_classify) | RunnableLambda(_validate)

    def classify(self, text: str) -> dict[str, Any]:
        if self._chain is None:
            return memory_service.classify_memory_candidate(text)
        try:
            result = self._chain.invoke(text)
            logger.debug("langchain_extraction_success")
            return result if isinstance(result, dict) else memory_service.classify_memory_candidate(text)
        except Exception:
            logger.debug("langchain_extraction_fallback", exc_info=True)
            return memory_service.classify_memory_candidate(text)

