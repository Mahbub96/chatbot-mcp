from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    requires_approval: bool
    reason: str
    risk_level: str


def evaluate_tool_action(tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
    """
    Decide whether a tool action needs explicit user approval.
    """
    if tool_name == "shell_command":
        return PolicyDecision(
            requires_approval=True,
            reason="Shell execution can change system state or access sensitive data.",
            risk_level="high",
        )

    if tool_name == "file_tools":
        action = str(arguments.get("action", "")).lower()
        if action in {"write", "delete"}:
            return PolicyDecision(
                requires_approval=True,
                reason=f"file_tools action '{action}' modifies local files.",
                risk_level="medium",
            )
        return PolicyDecision(requires_approval=False, reason="Read-only file action.", risk_level="low")

    # Conservative default for unknown tools.
    return PolicyDecision(
        requires_approval=True,
        reason=f"Unknown tool '{tool_name}' requires explicit approval by default.",
        risk_level="medium",
    )

