#!/usr/bin/env python3
"""
Check whether real retrieval (BM25 + vector + hybrid) is working.

Run from the project root:
  python scripts/test_retrieval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Project root directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

def main() -> None:
    chunks_path = ROOT / "data" / "chunks" / "chunks_index.json"
    print("1) Chunks index")
    if not chunks_path.exists():
        print(f"   Not found: {chunks_path}")
        print("   Please run knowledge_base/scripts/chunk.py first to generate chunks_index.json")
    else:
        try:
            data = json.loads(chunks_path.read_text(encoding="utf-8"))
            n = len(data.get("chunks", []))
            print(f"   Path: {chunks_path}")
            print(f"   Chunk count: {n}")
        except Exception as e:
            print(f"   Read failed: {e}")

    print("\n2) Optional dependencies")
    try:
        import rank_bm25
        print("   rank_bm25: installed")
    except ImportError:
        print("   rank_bm25: not installed (pip install rank-bm25)")

    try:
        import sentence_transformers
        print("   sentence_transformers: installed")
    except ImportError:
        print("   sentence_transformers: not installed (pip install sentence-transformers)")

    print("\n3) Call retrieval functions")
    try:
        from app.services.retrieval.retrieval import (
            lexical_search,
            vector_search,
            hybrid_retrieve,
        )
    except ImportError as e:
        print(f"   Import failed: {e}")
        print("   Make sure you run this from project root: python scripts/test_retrieval.py")
        sys.exit(1)
    except Exception as e:
        print(f"   Exception during import (possibly dependency or environment issue): {e}")
        sys.exit(1)

    q1 = "Hainan Free Trade Port tax policy"
    q2 = "Hainan Free Trade Port policy"
    for name, q in [("lexical_search", q1), ("vector_search", q1)]:
        fn = lexical_search if name == "lexical_search" else vector_search
        try:
            spans = fn(q, top_n=10)
            print(f"   {name}(query, top_n=10) returned {len(spans)} results")
        except Exception as e:
            print(f"   {name} exception: {type(e).__name__}: {e}")

    for label, query in [("Query A", q1), ("Query B", q2)]:
        print(f"\n4) hybrid_retrieve — {label}: {query!r}")
        try:
            result = hybrid_retrieve(query, top_k=5, original_topic=query)
        except Exception as e:
            print(f"   Exception: {e}")
            continue
        print(f"   evidence_sufficient: {result.evidence_sufficient}")
        print(f"   downgrade_reason: {result.downgrade_reason}")
        print(f"   Span count: {len(result.spans)}")
        if not result.spans:
            if not chunks_path.exists():
                print("   (No chunks or missing dependencies; currently fallback retrieval or empty result)")
            continue
        for i, s in enumerate(result.spans[:5], 1):
            score = s.reranker_score if s.reranker_score is not None else 0.0
            body = getattr(s.metadata, "issuing_body", "—") if s.metadata else "—"
            text = (s.text or "")[:80].replace("\n", " ")
            print(f"   [{i}] span_id={s.span_id[:20]}... score={score:.3f} issuing_body={body}")
            print(f"       text: {text}...")

    lexical_any = False
    vector_any = False
    try:
        lexical_any = len(lexical_search(q1, top_n=5)) > 0
        vector_any = len(vector_search(q1, top_n=5)) > 0
    except Exception:
        pass
    print("\n5) Conclusion")
    if lexical_any or vector_any:
        print("   Real retrieval is enabled (BM25 and/or vector retrieval returned results)")
    else:
        print("   Currently using fallback retrieval (BM25 and vector both returned no results, or dependencies/data are not ready)")


if __name__ == "__main__":
    main()
