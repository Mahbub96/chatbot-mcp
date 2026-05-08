import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# load .env safely
load_dotenv(BASE_DIR / ".env")


def get_env(key: str, required: bool = True):
    value = os.getenv(key)
    if required and not value:
        raise RuntimeError(f"Missing environment variable: {key}")
    return value


# LLM CONFIG
MODEL = os.getenv("DEFAULT_MODEL") or "meta/llama-3.1-70b-instruct"
BANGLA_MODEL = os.getenv("BANGLA_MODEL") or ""
CODE_MODEL = os.getenv("CODE_MODEL") or ""
VISION_MODEL = os.getenv("VISION_MODEL") or ""
IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL") or "qwen/qwen-image"
IMAGE_EDIT_MODEL = os.getenv("IMAGE_EDIT_MODEL") or "qwen/qwen-image-edit"
BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or "https://integrate.api.nvidia.com/v1/images/generations"
IMAGE_EDIT_BASE_URL = os.getenv("IMAGE_EDIT_BASE_URL") or "https://integrate.api.nvidia.com/v1/images/edits"
MEMORY_ENABLED = (os.getenv("MEMORY_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_SQLITE_URL = os.getenv("MEMORY_SQLITE_URL") or f"sqlite:///{(BASE_DIR / 'files' / 'memory.db').as_posix()}"
MEMORY_VECTOR_PATH = os.getenv("MEMORY_VECTOR_PATH") or str(BASE_DIR / "files" / "faiss_store")
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K") or "5")
MEMORY_MIN_SCORE = float(os.getenv("MEMORY_MIN_SCORE") or "0.20")
MEMORY_AUTO_STORE = (os.getenv("MEMORY_AUTO_STORE") or "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_MAX_ITEMS = int(os.getenv("MEMORY_MAX_ITEMS") or "5000")


def get_nvidia_api_key():
    return get_env("NVIDIA_API_KEY")