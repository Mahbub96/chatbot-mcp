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


def get_nvidia_api_key():
    return get_env("NVIDIA_API_KEY")