#!/usr/bin/env python3
"""
Build lexical + vector indices for retrieval.

Reads from data/chunks/chunks_index.json.
Outputs indices to data/indices/ (skeleton: writes manifest for RAG wiring).

TODO: Wire to BM25 (e.g. rank-bm25) and vector store (e.g. FAISS, sentence-transformers).
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHUNKS_INDEX = DATA_DIR / "chunks" / "chunks_index.json"
INDICES_DIR = DATA_DIR / "indices"


def main():
    INDICES_DIR.mkdir(parents=True, exist_ok=True)
    if not CHUNKS_INDEX.exists():
        print("No chunks_index.json. Run chunk.py first.")
        return
    data = json.loads(CHUNKS_INDEX.read_text(encoding="utf-8"))
    chunks = data.get("chunks", [])
    manifest = {
        "chunk_count": len(chunks),
        "index_type": "skeleton",
        "lexical": "TODO: BM25",
        "vector": "TODO: FAISS / sentence-transformers",
    }
    manifest_path = INDICES_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Index manifest: {manifest_path}. {len(chunks)} chunks ready for wiring.")


if __name__ == "__main__":
    main()
