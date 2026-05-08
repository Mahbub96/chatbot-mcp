from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from config import MEMORY_ENABLED, get_nvidia_api_key
from gateway.memory_pipeline import memory_pipeline
from memory.facade import memory_facade as memory_service

router = APIRouter()
EXPECTED_ENDPOINTS = {
    "/health/live",
    "/health/ready",
    "/v1/chat/completions",
    "/v1/models",
    "/memory/stats",
}


@router.get("/health/live")
def health_live():
    return {"status": "ok", "service": "local-mcp-gateway", "ts": datetime.now(UTC).isoformat()}


@router.get("/health/ready")
def health_ready(request: Request):
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
    route_paths = {
        route.path
        for route in request.app.routes
        if getattr(route, "path", None)
    }
    missing_endpoints = sorted(EXPECTED_ENDPOINTS.difference(route_paths))
    checks["expected_endpoints"] = not bool(missing_endpoints)
    if missing_endpoints:
        reasons.append(f"missing endpoints in running process: {', '.join(missing_endpoints)}")
    ready = all(checks.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "route_manifest": {
            "expected_count": len(EXPECTED_ENDPOINTS),
            "missing": missing_endpoints,
        },
        "memory_queue_depth": memory_pipeline.queue_size if MEMORY_ENABLED else 0,
        "reasons": reasons,
        "ts": datetime.now(UTC).isoformat(),
    }
    if ready:
        return payload
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)


@router.get("/health/routes")
def health_routes(request: Request):
    route_paths = sorted(
        {
            route.path
            for route in request.app.routes
            if getattr(route, "path", None)
        }
    )
    return {
        "status": "ok",
        "routes_count": len(route_paths),
        "routes": route_paths,
        "expected_endpoints": sorted(EXPECTED_ENDPOINTS),
        "missing_expected_endpoints": sorted(set(EXPECTED_ENDPOINTS).difference(set(route_paths))),
        "ts": datetime.now(UTC).isoformat(),
    }
