from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent.llm import edit_image, generate_image
from config import (
    IMAGE_BASE_URL,
    IMAGE_EDIT_BASE_URL,
    IMAGE_EDIT_MODEL,
    IMAGE_GEN_MODEL,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from gateway.helpers.http_utils import json_error
from gateway.helpers.rate_limiter import InMemoryRateLimiter

ERR_TOO_MANY_REQUESTS = "Too many requests"
ERR_INVALID_JSON_BODY = "Invalid JSON body"
ERR_BODY_OBJECT_REQUIRED = "Request body must be an object"
router = APIRouter()
rate_limiter = InMemoryRateLimiter(
    window_seconds=max(1, RATE_LIMIT_WINDOW_SECONDS),
    max_requests=max(1, RATE_LIMIT_MAX_REQUESTS),
)
def normalize_image_error(exc: Exception, *, model: str, endpoint: str, action: str) -> str:
    msg = str(exc)
    if "[LLM_ERROR 404]" in msg:
        return (
            f"{action} endpoint/model not available for current NVIDIA account. "
            f"model={model}, endpoint={endpoint}. "
            "Set a valid model/endpoint pair for your account."
        )
    return msg
@router.post("/v1/images/generations")
async def images_generations(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, ERR_TOO_MANY_REQUESTS)

    try:
        body = await request.json()
    except Exception:
        return json_error(400, ERR_INVALID_JSON_BODY)

    if not isinstance(body, dict):
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    prompt = body.get("prompt", "")
    model = body.get("model") or IMAGE_GEN_MODEL
    size = body.get("size", "1024x1024")
    n = body.get("n", 1)

    try:
        return await generate_image(prompt=prompt, model=model, size=size, n=n)
    except Exception as exc:
        return json_error(
            502,
            normalize_image_error(
                exc,
                model=model,
                endpoint=IMAGE_BASE_URL,
                action="Image generation",
            ),
        )
@router.post("/v1/images/edits")
async def images_edits(request: Request) -> Any:
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_limited(client_ip):
        return json_error(429, ERR_TOO_MANY_REQUESTS)

    try:
        body = await request.json()
    except Exception:
        return json_error(400, ERR_INVALID_JSON_BODY)

    if not isinstance(body, dict):
        return json_error(400, ERR_BODY_OBJECT_REQUIRED)

    prompt = body.get("prompt", "")
    image = body.get("image", "")
    mask = body.get("mask")
    model = body.get("model") or IMAGE_EDIT_MODEL
    size = body.get("size", "1024x1024")
    n = body.get("n", 1)

    try:
        return await edit_image(
            prompt=prompt,
            image=image,
            model=model,
            size=size,
            n=n,
            mask=mask,
        )
    except Exception as exc:
        return json_error(502, normalize_image_error(exc, model=model, endpoint=IMAGE_EDIT_BASE_URL, action="Image edit"))
