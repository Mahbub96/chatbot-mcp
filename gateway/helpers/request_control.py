from __future__ import annotations

from dataclasses import dataclass

from config import MAX_RETRIES, MAX_STREAM_IDLE_TIMEOUTS, MAX_TOOL_ACTIONS_PER_REQUEST


@dataclass(frozen=True)
class RequestControlPolicy:
    max_retries: int = MAX_RETRIES
    max_stream_idle_timeouts: int = MAX_STREAM_IDLE_TIMEOUTS
    max_tool_actions_per_request: int = MAX_TOOL_ACTIONS_PER_REQUEST

    def allows_tool_action(self, tool_actions_used: int) -> bool:
        return tool_actions_used < self.max_tool_actions_per_request


@dataclass
class RetryBudget:
    max_attempts: int
    used_attempts: int = 0

    def consume(self) -> bool:
        if self.used_attempts >= max(1, int(self.max_attempts)):
            return False
        self.used_attempts += 1
        return True


DEFAULT_REQUEST_CONTROL_POLICY = RequestControlPolicy()
