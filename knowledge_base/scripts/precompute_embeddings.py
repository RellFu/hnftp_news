#!/usr/bin/env python3
"""
Precompute and persist chunk embeddings for the current RAG embedding model.

Usage (from project root):
  cd /Users/a1-6/news
  python knowledge_base/scripts/precompute_embeddings.py

This script:
- Loads the embedding model configured via RAG_EMBEDDING_MODEL (or the default),
- Encodes all chunks from data/chunks/chunks_index.json,
- Persists embeddings to data/chunks/embeddings/<model>.npz,
so that subsequent hybrid retrieval cold starts are much faster.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"


def main() -> None:
    sys.path.insert(0, str(BACKEND_DIR))

    from app.core.config import EMBEDDING_MODEL_NAME  # type: ignore[import]
    from app.services.retrieval import vector_search  # type: ignore[import]

    print(f"Using embedding model: {EMBEDDING_MODEL_NAME}", flush=True)

    # Warm up vector_search once; this will trigger embedding model load and
    # encoding of all chunks, and persist embeddings to disk via the retrieval
    # module's caching logic.
    try:
        spans = vector_search("warmup embedding precompute", top_n=1)
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"[ERROR] Failed to precompute embeddings: {exc}", flush=True)
        sys.exit(1)

    count = len(spans)
    print(f"Vector index warm-up complete. Sampled spans returned: {count}", flush=True)
    print("If data/chunks/embeddings/ now contains a .npz file, embeddings have been precomputed.", flush=True)


if __name__ == "__main__":
    main()

