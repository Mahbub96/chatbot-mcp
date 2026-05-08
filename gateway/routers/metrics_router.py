from __future__ import annotations

from fastapi import APIRouter, Response

from gateway.telemetry import render_prometheus

router = APIRouter()


@router.get("/metrics")
def metrics():
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")
