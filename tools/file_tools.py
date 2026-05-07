from pathlib import Path

# =========================
# BASE CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]
FILES_DIR = BASE_DIR / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# SAFE PATH
# =========================
def safe_path(path: str) -> Path:
    target = (FILES_DIR / path).resolve()

    if FILES_DIR not in target.parents and target != FILES_DIR:
        raise Exception("Access denied")

    return target


# =========================
# TOOL IDENTITY
# =========================
tool_name = "file_tools"


# =========================
# INTERNAL OPERATIONS
# =========================
def _read(path: str):
    p = safe_path(path)
    if not p.exists():
        return {"error": "file not found"}
    return {"content": p.read_text(encoding="utf-8")}


def _write(path: str, content: str):
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"status": "written"}


def _delete(path: str):
    p = safe_path(path)
    if not p.exists():
        return {"error": "file not found"}
    p.unlink()
    return {"status": "deleted"}


def _list(path: str = ""):
    p = safe_path(path)
    if not p.exists():
        return {"error": "directory not found"}

    return {
        "files": [
            str(x.relative_to(FILES_DIR))
            for x in p.rglob("*")
            if x.is_file()
        ]
    }


# =========================
# MCP ENTRYPOINT (IMPORTANT)
# =========================
def run(action: str, **kwargs):
    if action == "read":
        return _read(kwargs.get("path", ""))

    if action == "write":
        return _write(
            kwargs.get("path", ""),
            kwargs.get("content", "")
        )

    if action == "delete":
        return _delete(kwargs.get("path", ""))

    if action == "list":
        return _list(kwargs.get("path", ""))

    return {
        "error": "unknown action",
        "available": ["read", "write", "delete", "list"]
    }