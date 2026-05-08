from __future__ import annotations

from fastapi import APIRouter

from tools.registry import TOOLS

MODEL_NAME = "local-mcp-model"

router = APIRouter()


@router.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@router.get("/mcp/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": name,
                "description": f"Auto-loaded tool: {name}",
                "parameters": {"type": "object"},
            }
            for name in sorted(TOOLS.keys())
        ]
    }

