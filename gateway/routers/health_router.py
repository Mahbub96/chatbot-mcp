from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from config import MEMORY_ENABLED, get_nvidia_api_key
from gateway.memory_pipeline import memory_pipeline
from memory.facade import memory_facade as memory_service

router = APIRouter()


@router.get("/health/live")
def health_live():
    return {"status": "ok", "service": "local-mcp-gateway", "ts": datetime.now(UTC).isoformat()}


@router.get("/health/ready")
def health_ready():
    checks: dict[str, bool] = {"nvidia_api_key": True, "memory": True}
    reasons: list[str] = []
    try:
        _ = get_nvidia_api_key()
    except Exception:
        checks["nvidia_api_key"] = False
        reasons.append("NVIDIA_API_KEY is missing")
    if MEMORY_ENABLED:
        try:
            memory_service.list_items(memory_scope="global", limit=1, offset=0)
        except Exception as exc:
            checks["memory"] = False
            reasons.append(f"memory backend unavailable: {exc}")
    ready = all(checks.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "memory_queue_depth": memory_pipeline.queue_size if MEMORY_ENABLED else 0,
        "reasons": reasons,
        "ts": datetime.now(UTC).isoformat(),
    }
    if ready:
        return payload
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
