from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from config import DEBUG_MODE, LOG_JSON
from agent.llm import llm_client
from memory.facade import memory_facade as memory_service
from gateway.memory_pipeline import memory_pipeline
from gateway.routers.chat_router import router as chat_router
from gateway.routers.health_router import router as health_router
from gateway.routers.images_router import router as images_router
from gateway.routers.mcp_router import router as mcp_router
from gateway.routers.memory_router import router as memory_router
from gateway.routers.metrics_router import router as metrics_router
from gateway.routers.models_router import router as models_router
from gateway.telemetry import record_request

app = FastAPI(title="Local MCP Gateway", version="1.0.0")
logger = logging.getLogger("gateway.http")

def _configure_debug_logging() -> None:
    if not DEBUG_MODE:
        return
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in root.handlers:
        handler.setLevel(logging.DEBUG)
    logging.getLogger("uvicorn").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    logger.debug("debug_mode_enabled")


_configure_debug_logging()


@app.on_event("startup")
async def startup_init():
    if DEBUG_MODE:
        logger.debug("gateway_startup_init_begin")
    await memory_pipeline.start()
    if DEBUG_MODE:
        logger.debug("gateway_startup_init_done")


@app.on_event("shutdown")
async def shutdown_cleanup():
    if DEBUG_MODE:
        logger.debug("gateway_shutdown_cleanup_begin")
    try:
        await memory_pipeline.stop()
        logger.info(json.dumps({"event": "shutdown_cleanup", "status": "ok", "resource": "memory_pipeline"}))
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "shutdown_cleanup",
                    "status": "error",
                    "resource": "memory_pipeline",
                    "error": str(exc),
                }
            )
        )
    try:
        await llm_client.close()
        logger.info(json.dumps({"event": "shutdown_cleanup", "status": "ok", "resource": "llm_client"}))
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "shutdown_cleanup",
                    "status": "error",
                    "resource": "llm_client",
                    "error": str(exc),
                }
            )
        )
    try:
        memory_service.close()
        logger.info(json.dumps({"event": "shutdown_cleanup", "status": "ok", "resource": "memory_service"}))
    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "shutdown_cleanup",
                    "status": "error",
                    "resource": "memory_service",
                    "error": str(exc),
                }
            )
        )


@app.middleware("http")
async def request_context_middleware(request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    method = request.method
    path = request.url.path
    if DEBUG_MODE:
        logger.debug(
            json.dumps(
                {
                    "event": "http_request_begin",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                }
            )
        )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        record_request(method=method, path=path, status_code=500, duration_ms=elapsed_ms)
        response = JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "request_id": request_id},
        )
        if LOG_JSON:
            logger.error(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": method,
                        "path": path,
                        "status_code": 500,
                        "duration_ms": elapsed_ms,
                    }
                )
            )
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        response.headers["X-Request-Id"] = request_id
        if DEBUG_MODE:
            logger.debug(
                json.dumps(
                    {
                        "event": "http_request_end",
                        "request_id": request_id,
                        "method": method,
                        "path": path,
                        "status_code": 500,
                        "duration_ms": elapsed_ms,
                    }
                )
            )
        return response
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
    record_request(method=method, path=path, status_code=response.status_code, duration_ms=elapsed_ms)
    if LOG_JSON:
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                }
            )
        )
    if DEBUG_MODE:
        logger.debug(
            json.dumps(
                {
                    "event": "http_request_end",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                }
            )
        )
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    response.headers["X-Request-Id"] = request_id
    return response

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(models_router)
app.include_router(mcp_router)
app.include_router(memory_router)
app.include_router(chat_router)
app.include_router(images_router)
