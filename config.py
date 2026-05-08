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
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or "https://integrate.api.nvidia.com/v1/embeddings"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "nvidia/nv-embedqa-e5-v5"
EMBEDDING_DIM = max(128, int(os.getenv("EMBEDDING_DIM") or "1024"))
EMBEDDING_TIMEOUT_SECONDS = max(5, int(os.getenv("EMBEDDING_TIMEOUT_SECONDS") or "20"))
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or "https://integrate.api.nvidia.com/v1/images/generations"
IMAGE_EDIT_BASE_URL = os.getenv("IMAGE_EDIT_BASE_URL") or "https://integrate.api.nvidia.com/v1/images/edits"
MEMORY_ENABLED = (os.getenv("MEMORY_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_SQLITE_URL = os.getenv("MEMORY_SQLITE_URL") or f"sqlite:///{(BASE_DIR / 'files' / 'memory.db').as_posix()}"
MEMORY_VECTOR_PATH = os.getenv("MEMORY_VECTOR_PATH") or str(BASE_DIR / "files" / "faiss_store")
MEMORY_VECTOR_BACKEND = (os.getenv("MEMORY_VECTOR_BACKEND") or "faiss").strip().lower()
MEMORY_VECTOR_PERSIST_EVERY = max(1, int(os.getenv("MEMORY_VECTOR_PERSIST_EVERY") or "50"))
MEMORY_VECTOR_INDEX_TYPE = (os.getenv("MEMORY_VECTOR_INDEX_TYPE") or "hnsw").strip().lower()
MEMORY_VECTOR_HNSW_M = max(8, int(os.getenv("MEMORY_VECTOR_HNSW_M") or "32"))
MEMORY_VECTOR_HNSW_EF_SEARCH = max(16, int(os.getenv("MEMORY_VECTOR_HNSW_EF_SEARCH") or "128"))
PGVECTOR_HNSW_M = max(8, int(os.getenv("PGVECTOR_HNSW_M") or "16"))
PGVECTOR_HNSW_EF_CONSTRUCTION = max(16, int(os.getenv("PGVECTOR_HNSW_EF_CONSTRUCTION") or "64"))
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K") or "5")
MEMORY_MIN_SCORE = float(os.getenv("MEMORY_MIN_SCORE") or "0.20")
MEMORY_AUTO_STORE = (os.getenv("MEMORY_AUTO_STORE") or "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_MAX_ITEMS = int(os.getenv("MEMORY_MAX_ITEMS") or "5000")
SHORT_TERM_TRACE_MAX_ITEMS = int(os.getenv("SHORT_TERM_TRACE_MAX_ITEMS") or "20000")
SHORT_TERM_RETENTION_HOURS = max(1, int(os.getenv("SHORT_TERM_RETENTION_HOURS") or "24"))
SHORT_TERM_MAX_QUEUE_ITEMS = max(100, int(os.getenv("SHORT_TERM_MAX_QUEUE_ITEMS") or "25000"))
SHORT_TERM_MAX_RETRIEVAL_LOG_ITEMS = max(100, int(os.getenv("SHORT_TERM_MAX_RETRIEVAL_LOG_ITEMS") or "25000"))
SHORT_TERM_CLEAR_ON_RESTART = (os.getenv("SHORT_TERM_CLEAR_ON_RESTART") or "true").strip().lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS") or "100")
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS") or "100")
LOG_JSON = (os.getenv("LOG_JSON") or "true").strip().lower() in {"1", "true", "yes", "on"}
DEBUG_MODE = (os.getenv("DEBUG_MODE") or "false").strip().lower() in {"1", "true", "yes", "on"}
VISION_STREAM_TIMEOUT_SECONDS = int(os.getenv("VISION_STREAM_TIMEOUT_SECONDS") or "90")
HUMANIZE_RESPONSES = (os.getenv("HUMANIZE_RESPONSES") or "true").strip().lower() in {"1", "true", "yes", "on"}
HUMAN_TONE_INSTRUCTION = (
    os.getenv("HUMAN_TONE_INSTRUCTION")
    or "Respond in a natural, warm, and human tone. Be clear, concise, and conversational."
)
SHADOW_MONITOR_ENABLED = (os.getenv("SHADOW_MONITOR_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
LEGACY_READ_FALLBACK_ENABLED = (os.getenv("LEGACY_READ_FALLBACK_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
LEGACY_WRITE_ENABLED = (os.getenv("LEGACY_WRITE_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
PROFILE_ANY_SCOPE_FALLBACK_ENABLED = (os.getenv("PROFILE_ANY_SCOPE_FALLBACK_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}


def get_nvidia_api_key():
    return get_env("NVIDIA_API_KEY")