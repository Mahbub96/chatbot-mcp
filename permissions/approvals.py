from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingApproval:
    approval_id: str
    tool_name: str
    arguments_hash: str
    reason: str
    risk_level: str
    created_at: float
    approved: bool | None = None
    consumed: bool = False


class ApprovalStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, PendingApproval] = {}

    @staticmethod
    def _hash_args(arguments: dict[str, Any]) -> str:
        serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def create(self, tool_name: str, arguments: dict[str, Any], reason: str, risk_level: str) -> PendingApproval:
        item = PendingApproval(
            approval_id=str(uuid.uuid4()),
            tool_name=tool_name,
            arguments_hash=self._hash_args(arguments),
            reason=reason,
            risk_level=risk_level,
            created_at=time.time(),
        )
        with self._lock:
            self._items[item.approval_id] = item
        return item

    def set_decision(self, approval_id: str, approved: bool) -> PendingApproval | None:
        with self._lock:
            item = self._items.get(approval_id)
            if not item:
                return None
            item.approved = approved
            return item

    def consume_if_valid(self, approval_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        with self._lock:
            item = self._items.get(approval_id)
            if not item:
                return False, "Approval not found."
            if item.consumed:
                return False, "Approval already used."
            if item.tool_name != tool_name:
                return False, "Approval tool mismatch."
            if item.arguments_hash != self._hash_args(arguments):
                return False, "Approval arguments mismatch."
            if item.approved is not True:
                return False, "Approval not granted."

            item.consumed = True
            return True, "Approved"

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for item in self._items.values():
                if item.approved is None and not item.consumed:
                    result.append(
                        {
                            "approval_id": item.approval_id,
                            "tool_name": item.tool_name,
                            "reason": item.reason,
                            "risk_level": item.risk_level,
                            "created_at": item.created_at,
                        }
                    )
            return sorted(result, key=lambda x: x["created_at"], reverse=True)


approval_store = ApprovalStore()

