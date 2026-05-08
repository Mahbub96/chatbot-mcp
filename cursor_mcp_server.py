from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT_SECONDS = 30.0

mcp = FastMCP("local-mcp-gateway")


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{GATEWAY_URL}{path}"
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        if method == "GET":
            res = await client.get(url)
        else:
            res = await client.post(url, json=payload or {})
        res.raise_for_status()
        return res.json()


@mcp.tool()
async def gateway_health() -> dict[str, Any]:
    """
    Check whether the local gateway is reachable.
    """
    try:
        models = await _request("GET", "/v1/models")
        return {"ok": True, "gateway_url": GATEWAY_URL, "models": models}
    except Exception as exc:
        return {"ok": False, "gateway_url": GATEWAY_URL, "error": str(exc)}


@mcp.tool()
async def list_gateway_tools() -> dict[str, Any]:
    """
    List tools currently exposed by the local gateway.
    """
    return await _request("GET", "/mcp/tools")


@mcp.tool()
async def execute_gateway_tool(
    name: str,
    arguments_json: str = "{}",
    approval_id: str = "",
) -> dict[str, Any]:
    """
    Request execution of a gateway tool.

    - If policy requires approval, gateway returns `requires_approval=true` and an `approval_id`.
    - Call `approve_gateway_action` and then re-run this tool with that `approval_id`.
    """
    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"arguments_json is invalid JSON: {exc}"}

    if not isinstance(arguments, dict):
        return {"success": False, "error": "arguments_json must decode to a JSON object"}

    payload: dict[str, Any] = {"name": name, "arguments": arguments}
    if approval_id.strip():
        payload["approval_id"] = approval_id.strip()

    return await _request("POST", "/mcp/execute", payload)


@mcp.tool()
async def list_pending_approvals() -> dict[str, Any]:
    """
    List pending high-risk actions waiting for explicit approval.
    """
    return await _request("GET", "/mcp/approvals")


@mcp.tool()
async def approve_gateway_action(approval_id: str, approved: bool) -> dict[str, Any]:
    """
    Approve or reject a pending action by approval_id.
    """
    payload = {"approval_id": approval_id, "approved": approved}
    return await _request("POST", "/mcp/approve", payload)


if __name__ == "__main__":
    mcp.run()

