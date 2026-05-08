from __future__ import annotations

from fastapi import FastAPI

from gateway.routers.chat_router import router as chat_router
from gateway.routers.images_router import router as images_router
from gateway.routers.mcp_router import router as mcp_router
from gateway.routers.memory_router import router as memory_router
from gateway.routers.models_router import router as models_router

app = FastAPI(title="Local MCP Gateway", version="1.0.0")
app.include_router(models_router)
app.include_router(mcp_router)
app.include_router(memory_router)
app.include_router(chat_router)
app.include_router(images_router)
