"""Corpus overview API routes."""

import json
from pathlib import Path

from fastapi import APIRouter

# backend/app/api/routes/corpus.py -> repo root = 5 parents
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
METADATA_PATH = PROJECT_ROOT / "data" / "metadata.json"

router = APIRouter(prefix="/api/corpus", tags=["corpus"])


@router.get("")
async def get_corpus_overview():
    """Return corpus metadata (indexed sources) and default retrieval policy."""
    if not METADATA_PATH.exists():
        return {
            "documents": [],
            "total": 0,
            "retrieval_policy": {
                "top_k": 5,
                "reranker_threshold": 0.35,
                "hybrid": "lexical + vector",
            },
        }
    data = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    docs = data.get("documents", [])
    return {
        "documents": [
            {
                "source_identifier": d.get("source_identifier"),
                "issuing_body": d.get("issuing_body"),
                "publication_date": d.get("publication_date"),
                "title": d.get("title"),
                "source_url": d.get("source_url"),
            }
            for d in docs
        ],
        "total": len(docs),
        "retrieval_policy": {
            "top_k": 5,
            "reranker_threshold": 0.35,
            "hybrid": "lexical + vector",
        },
    }
