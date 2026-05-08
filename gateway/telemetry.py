from __future__ import annotations

from collections import defaultdict
from threading import Lock

_lock = Lock()
_request_total = 0
_request_by_path: dict[tuple[str, str, int], int] = defaultdict(int)
_latency_sum_ms = 0.0


def record_request(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    global _request_total, _latency_sum_ms
    with _lock:
        _request_total += 1
        _request_by_path[(method, path, int(status_code))] += 1
        _latency_sum_ms += max(0.0, float(duration_ms))


def render_prometheus() -> str:
    with _lock:
        lines = [
            "# HELP gateway_requests_total Total HTTP requests processed.",
            "# TYPE gateway_requests_total counter",
            f"gateway_requests_total {_request_total}",
            "# HELP gateway_request_duration_ms_sum Sum of request duration in milliseconds.",
            "# TYPE gateway_request_duration_ms_sum counter",
            f"gateway_request_duration_ms_sum {_latency_sum_ms:.3f}",
            "# HELP gateway_requests_by_path_total Requests grouped by method, path, status.",
            "# TYPE gateway_requests_by_path_total counter",
        ]
        for (method, path, status), count in sorted(_request_by_path.items()):
            safe_path = path.replace('"', '\\"')
            lines.append(
                f'gateway_requests_by_path_total{{method="{method}",path="{safe_path}",status="{status}"}} {count}'
            )
        return "\n".join(lines) + "\n"
