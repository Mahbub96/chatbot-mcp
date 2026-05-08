from __future__ import annotations

import re
import subprocess
from pathlib import Path

tool_name = "shell_command"

BASE_DIR = Path(__file__).resolve().parents[1]

# Commands/patterns we never allow, even with approval.
# Keep this strict; expand as needed.
DENYLIST_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-fr\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bhalt\b",
    r"\bdd\s+if=",
    r"\bmkfs(\.\w+)?\b",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bchmod\s+-R\s+777\b",
    r"\bchown\s+-R\b",
    r":\(\)\s*\{",  # fork bomb pattern
    r"\bkillall\s+-9\b",
    r"\biptables\b",
    r"\bnft\b",
    r"\bcurl\b.*\|\s*(bash|sh)\b",
    r"\bwget\b.*\|\s*(bash|sh)\b",
]
DENYLIST = [re.compile(pat, re.IGNORECASE) for pat in DENYLIST_PATTERNS]


def _safe_cwd(cwd: str) -> Path:
    target = (BASE_DIR / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
    # Restrict execution cwd to repository tree.
    if BASE_DIR not in target.parents and target != BASE_DIR:
        raise ValueError("cwd is outside the repository.")
    return target


def _is_denied(command: str) -> str | None:
    for pattern in DENYLIST:
        if pattern.search(command):
            return pattern.pattern
    return None


def run(command: str, cwd: str = ".", timeout_seconds: int = 30):
    if not isinstance(command, str) or not command.strip():
        return {"success": False, "error": "command must be a non-empty string"}

    denied_by = _is_denied(command)
    if denied_by:
        return {
            "success": False,
            "error": "Command blocked by denylist policy.",
            "blocked_pattern": denied_by,
        }

    workdir = _safe_cwd(cwd)

    completed = subprocess.run(
        command,
        cwd=str(workdir),
        shell=True,
        text=True,
        capture_output=True,
        timeout=max(1, int(timeout_seconds)),
    )

    return {
        "success": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
        "cwd": str(workdir),
    }

