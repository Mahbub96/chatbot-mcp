from __future__ import annotations

from typing import Any

from permissions.approvals import approval_store
from permissions.policy import evaluate_tool_action
from tools.registry import run_tool


def execute_tool_with_policy(name: str, args: dict[str, Any], approval_id: str | None = None) -> dict[str, Any]:
    policy = evaluate_tool_action(name, args)
    if policy.requires_approval:
        if isinstance(approval_id, str) and approval_id.strip():
            ok, reason = approval_store.consume_if_valid(approval_id, name, args)
            if not ok:
                return {
                    "success": False,
                    "requires_approval": True,
                    "error": reason,
                }
        else:
            pending = approval_store.create(
                tool_name=name,
                arguments=args,
                reason=policy.reason,
                risk_level=policy.risk_level,
            )
            return {
                "success": False,
                "requires_approval": True,
                "approval_id": pending.approval_id,
                "risk_level": pending.risk_level,
                "reason": pending.reason,
                "tool": name,
                "arguments": args,
            }
    return {"success": True, "tool": name, "result": run_tool(name, args)}

