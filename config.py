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
MODEL = "meta/llama-3.1-70b-instruct"
BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def get_nvidia_api_key():
    return get_env("NVIDIA_API_KEY")