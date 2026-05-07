import os
from config import BASE_DIR
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
FILES_DIR = BASE_DIR / "files"
FILES_DIR.mkdir(exist_ok=True)

def safe_path(path):
    full = os.path.abspath(os.path.join(BASE_DIR, path))
    base = os.path.abspath(BASE_DIR)

    if not full.startswith(base):
        raise Exception("Access denied")

    return full


def read_file(path):
    try:
        with open(safe_path(path), "r") as f:
            return {"content": f.read()}
    except Exception as e:
        return {"error": str(e)}


def write_file(path, content):
    try:
        with open(safe_path(path), "w") as f:
            f.write(content)
        return {"status": "written"}
    except Exception as e:
        return {"error": str(e)}


def delete_file(path):
    try:
        os.remove(safe_path(path))
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}