"""
Retrieval Augmented News Pitch Assistant - FastAPI Backend

Hainan Free Trade Port policy reporting: retrieval, generation, evidence binding,
downgrade handling, audit logging, evaluation.
"""
# Force UTF-8 for stdout/stderr so no 'ascii' codec is used when logging or printing
import sys
import io
if hasattr(sys, "stdout") and hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys, "stderr") and hasattr(sys.stderr, "buffer"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import llm_available, serper_available

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Hainan Pitch Assistant API",
    description="RAG-based news pitch assistant for Hainan Free Trade Port policy reporting",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hainan Pitch Assistant API", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy", "llm_configured": llm_available()}


@app.on_event("startup")
async def startup():
    if llm_available():
        logger.info("LLM configured: Proactive pitch will use API (DeepSeek/OpenAI).")
    else:
        logger.warning(
            "LLM not configured: set LLM_API_KEY in .env (e.g. news/.env or backend/.env). Proactive will use deterministic fallback generation."
        )
    if serper_available():
        logger.info("Serper configured: web search enabled for pitch flows.")
    else:
        logger.warning(
            "Serper not configured: set SERPER_API_KEY in project root .env (e.g. news/.env). Web sources will be empty."
        )


# API routes
from app.api.routes import retrieval, generation, audit, corpus, evaluation, validate, reactive_pitch, active_search

app.include_router(retrieval.router)
app.include_router(generation.router)
app.include_router(validate.router)
app.include_router(reactive_pitch.router)
app.include_router(active_search.router)
app.include_router(audit.router)
app.include_router(corpus.router)
app.include_router(evaluation.router)
