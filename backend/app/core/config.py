"""Core configuration"""

import os
from pathlib import Path

# Load .env: infer project root from config location
_resolved = Path(__file__).resolve()
_backend_dir = _resolved.parent.parent.parent  # backend
_project_root = _resolved.parent.parent.parent.parent  # project root (peer of backend, contains .env)
try:
    from dotenv import load_dotenv
    # Load project-root .env first (SERPER_API_KEY etc.), then backend/.env if present
    for _d in (_project_root, _backend_dir):
        _env_file = _d / ".env"
        if _env_file.exists():
            load_dotenv(str(_env_file), override=False)
except Exception:
    pass

# Retrieval and reranking (overridable via env for A/B or per-environment tuning)
def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default

def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default

def _str_env(key: str, default: str = "") -> str:
    v = os.environ.get(key, default)
    return (v or "").strip()


TOP_K = _int_env("RAG_TOP_K", 12)
RERANKER_THRESHOLD = _float_env("RAG_RERANKER_THRESHOLD", 0.45)

# Embedding model for vector retrieval; configurable via env.
# Default: paraphrase-multilingual-MiniLM-L12-v2 (in A/B, angle_overlap is slightly better than all-MiniLM-L6-v2 with similar latency).
# Set RAG_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 to fall back to the English model.
EMBEDDING_MODEL_NAME: str = _str_env(
    "RAG_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# Timeouts: max wait time for the full reactive/active pitch request; on timeout return partial + timeout=True
# First request may load models and encode chunks, which can exceed 60s; increase via RAG_REQUEST_TIMEOUT (e.g. 180)
HARD_TIMEOUT_SEC = _int_env("RAG_REQUEST_TIMEOUT", 60)
TYPICAL_TIMEOUT_SEC = 15

# LLM (OpenAI-compatible API)
def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key, default) or os.environ.get(key.replace("LLM_", "OPENAI_"), default)
    return (v or "").strip()

LLM_API_KEY: str = _env("LLM_API_KEY") or _env("OPENAI_API_KEY")
_burl = _env("LLM_BASE_URL") or _env("OPENAI_BASE_URL")
LLM_BASE_URL: str | None = _burl if _burl else None
LLM_MODEL: str = _env("LLM_MODEL") or "gpt-4o-mini"
LLM_TIMEOUT_SEC: int = int(_env("LLM_TIMEOUT_SEC") or "45")

def llm_available() -> bool:
    """True if LLM is configured (API key set)."""
    return bool(LLM_API_KEY.strip())

# Serper (Google Search API) for Reactive web search
SERPER_API_KEY: str = _env("SERPER_API_KEY")
SERPER_ENDPOINT: str = "https://google.serper.dev/search"

def serper_available() -> bool:
    return bool(SERPER_API_KEY.strip())
