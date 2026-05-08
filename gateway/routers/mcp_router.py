from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from gateway.controllers.tool_controller import execute_tool_with_policy
from permissions.approvals import approval_store

router = APIRouter()


@router.post("/mcp/execute")
async def execute_tool(payload: dict[str, Any]):
    name = payload.get("name")
    args = payload.get("arguments", {})
    approval_id = payload.get("approval_id")

    if not isinstance(name, str) or not name.strip():
        return {"success": False, "error": "Missing tool name"}
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    return execute_tool_with_policy(name, args, approval_id=approval_id)


@router.get("/mcp/approvals")
def list_pending_approvals():
    return {"pending": approval_store.list_pending()}


@router.post("/mcp/approve")
async def set_approval(payload: dict[str, Any]):
    approval_id = payload.get("approval_id")
    approved = payload.get("approved")
    if not isinstance(approval_id, str) or not approval_id.strip():
        return {"success": False, "error": "approval_id is required"}
    if not isinstance(approved, bool):
        return {"success": False, "error": "approved must be boolean"}

    item = approval_store.set_decision(approval_id, approved=approved)
    if not item:
        return {"success": False, "error": "Approval not found"}

    return {
        "success": True,
        "approval_id": item.approval_id,
        "approved": item.approved,
        "tool_name": item.tool_name,
    }

