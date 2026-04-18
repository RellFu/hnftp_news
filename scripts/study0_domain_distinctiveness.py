#!/usr/bin/env python3
"""
Study 0: Domain distinctiveness for Hainan Free Trade Port policy reporting.

Both Hainan and non-Hainan corpora are isolated from the project main corpus:
  - Hainan corpus: Nanhai Net, Hainan Daily, Hainan Broadcasting Group, Xinhua Hainan, People.cn Hainan
  - Non-Hainan corpus: Xinhua, People.cn, BBC, New York Times, Reuters, AFP

Data is read only from `data/study0/` manifests and article files, not from `data/metadata.json` or `data/raw/articles`.

Usage:
  python scripts/study0_domain_distinctiveness.py
  python scripts/study0_domain_distinctiveness.py --max-docs 400 --permutations 500 --no-plot
  python scripts/study0_domain_distinctiveness.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STUDY0_DIR = DATA_DIR / "study0"
OUT_DIR = PROJECT_ROOT / "evaluation" / "study0"

HAINAN_MANIFEST = STUDY0_DIR / "hainan_manifest.json"
NON_HAINAN_MANIFEST = STUDY0_DIR / "non_hainan_manifest.json"
SOURCES_JSON = STUDY0_DIR / "sources.json"

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_DOC_CHARS = 4000
MIN_CHARS = 200


def _load_sources_config() -> tuple[list[str], list[str]]:
    """Load canonical outlet lists from data/study0/sources.json."""
    if not SOURCES_JSON.exists():
        return [], []
    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    hainan = data.get("hainan_outlets", [])
    non_hainan = data.get("non_hainan_outlets", [])
    return hainan, non_hainan


def _load_manifest(manifest_path: Path, base_dir: Path, is_hainan: bool) -> list[dict]:
    """
    Load documents from a Study 0 manifest.
    Each entry must have doc_id, source/outlet, publication_date, and either text or file_path.
    """
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("documents", [])
    docs = []
    for e in entries:
        doc_id = e.get("doc_id") or e.get("source_identifier") or ""
        if not doc_id:
            continue
        text = (e.get("text") or "").strip()
        fp = e.get("file_path") or e.get("text_path") or ""
        if not text and fp:
            path = base_dir / fp if not Path(fp).is_absolute() else Path(fp)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text or len(text) < MIN_CHARS:
            continue
        source = e.get("source") or e.get("outlet") or e.get("issuing_body") or ""
        docs.append({
            "doc_id": doc_id,
            "text": text[:MAX_DOC_CHARS],
            "publication_date": (e.get("publication_date") or "")[:10],
            "issuing_body": source,
            "outlet": source,
            "title": (e.get("title") or "")[:200],
            "language": e.get("language") or "",
            "is_hainan": is_hainan,
        })
    return docs


def _stratified_sample(items: list[dict], max_docs: int) -> list[dict]:
    """Sample by (year, outlet) to avoid single-source/single-event bias."""
    by_stratum: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in items:
        date = (d.get("publication_date") or "")[:4]
        outlet = (d.get("outlet") or d.get("issuing_body") or "unknown")[:40]
        by_stratum[(date, outlet)].append(d)
    out = []
    n_strata = len(by_stratum)
    if n_strata == 0:
        return out
    per_stratum = max(1, max_docs // n_strata)
    for stratum_items in by_stratum.values():
        for d in stratum_items[:per_stratum]:
            if len(out) >= max_docs:
                break
            out.append(d)
        if len(out) >= max_docs:
            break
    return out


def load_hainan_corpus(max_docs: int) -> list[dict]:
    """Load Hainan corpus from data/study0/hainan_manifest.json only."""
    docs = _load_manifest(HAINAN_MANIFEST, STUDY0_DIR, is_hainan=True)
    return _stratified_sample(docs, max_docs)


def load_non_hainan_corpus(max_docs: int) -> list[dict]:
    """Load non-Hainan corpus from data/study0/non_hainan_manifest.json only."""
    docs = _load_manifest(NON_HAINAN_MANIFEST, STUDY0_DIR, is_hainan=False)
    return _stratified_sample(docs, max_docs)


def _warn_sources(docs: list[dict], canonical: list[str], label: str) -> None:
    """Warn if any document source is not in the canonical list."""
    if not canonical:
        return
    seen = set(d.get("outlet") or d.get("issuing_body") or "" for d in docs)
    unknown = [s for s in seen if s and s not in canonical]
    if unknown:
        print(f"  [Warning] {label} documents with source not in sources.json: {unknown[:5]}{'...' if len(unknown) > 5 else ''}", flush=True)


def embed_documents(texts: list[str], model):
    """Encode list of texts to normalised vectors (row per doc)."""
    import numpy as np
    embs = model.encode(texts, convert_to_numpy=True, show_progress_bar=bool(len(texts) > 50))
    if embs.ndim == 1:
        embs = embs.reshape(1, -1)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-8, norms)
    return embs / norms


def cosine_similarity_matrix(emb):
    """Pairwise cosine similarity (emb is row-normalised)."""
    return emb @ emb.T


def mean_within_between(emb_h, emb_n):
    """Mean cosine: within Hainan, within NonHainan, between."""
    import numpy as np
    sim_h = cosine_similarity_matrix(emb_h)
    sim_n = cosine_similarity_matrix(emb_n)
    mask_h = np.triu(np.ones_like(sim_h, dtype=bool), k=1)
    mask_n = np.triu(np.ones_like(sim_n, dtype=bool), k=1)
    within_h = sim_h[mask_h].mean() if mask_h.any() else 0.0
    within_n = sim_n[mask_n].mean() if mask_n.any() else 0.0
    between = (emb_h @ emb_n.T).mean()
    return float(within_h), float(within_n), float(between)


def permutation_test(emb_h, emb_n, n_permutations: int, seed: int = 42):
    """Permutation test: H0 = labels random. Returns (observed_delta, p_value)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    combined = np.vstack([emb_h, emb_n])
    n_h = len(emb_h)
    n_total = len(combined)
    within_h, within_n, between = mean_within_between(emb_h, emb_n)
    observed_delta = (within_h + within_n) / 2 - between
    count_ge = 0
    for _ in range(n_permutations):
        idx = rng.permutation(n_total)
        perm_h = combined[idx[:n_h]]
        perm_n = combined[idx[n_h:]]
        wh, wn, bw = mean_within_between(perm_h, perm_n)
        delta = (wh + wn) / 2 - bw
        if delta >= observed_delta:
            count_ge += 1
    p_value = (count_ge + 1) / (n_permutations + 1)
    return observed_delta, p_value


def build_sampling_manifest(hainan_docs: list[dict], non_hainan_docs: list[dict]) -> list[dict]:
    """Sampling manifest for reproducibility."""
    manifest = []
    for d in hainan_docs:
        manifest.append({
            "doc_id": d["doc_id"],
            "source": d.get("outlet") or d.get("issuing_body", ""),
            "publication_date": d.get("publication_date", ""),
            "is_hainan": True,
            "topic_label": "Hainan policy reporting (Nanhai Net / Hainan Daily / Hainan Broadcasting Group / Xinhua Hainan / People.cn Hainan)",
            "included_in_study0": True,
        })
    for d in non_hainan_docs:
        manifest.append({
            "doc_id": d["doc_id"],
            "source": d.get("outlet") or d.get("issuing_body", ""),
            "publication_date": d.get("publication_date", ""),
            "is_hainan": False,
            "topic_label": "General news (Xinhua / People.cn / BBC / NYT / Reuters / AFP)",
            "included_in_study0": True,
        })
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Study 0: Domain distinctiveness (Hainan media vs general domestic/international media, isolated from main project corpus)"
    )
    parser.add_argument("--max-docs", type=int, default=300, help="Max docs per corpus (stratified)")
    parser.add_argument("--permutations", type=int, default=1000, help="Permutation test iterations")
    parser.add_argument("--out-dir", type=str, default="", help="Output directory (default: evaluation/study0)")
    parser.add_argument("--no-plot", action="store_true", help="Skip t-SNE plot")
    parser.add_argument("--dry-run", action="store_true", help="Only build manifest and draft results (no embedding)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Hainan corpus: only from data/study0/hainan_manifest.json
    if not HAINAN_MANIFEST.exists():
        print(
            f"Study 0 Hainan corpus not found: {HAINAN_MANIFEST}\n"
            "Prepare hainan_manifest.json as documented in data/study0/README.md; allowed sources are Nanhai Net, Hainan Daily, Hainan Broadcasting Group, Xinhua Hainan, and People.cn Hainan.",
            file=sys.stderr,
        )
        return 1

    # Non-Hainan corpus: only from data/study0/non_hainan_manifest.json
    if not NON_HAINAN_MANIFEST.exists():
        print(
            f"Study 0 non-Hainan corpus not found: {NON_HAINAN_MANIFEST}\n"
            "Prepare non_hainan_manifest.json as documented in data/study0/README.md; allowed sources are Xinhua, People.cn, BBC, New York Times, Reuters, and AFP.",
            file=sys.stderr,
        )
        return 1

    hainan_outlets, non_hainan_outlets = _load_sources_config()

    print("Study 0: Domain distinctiveness (Hainan media vs general domestic/international media, isolated from main project corpus)", flush=True)
    print("Loading Hainan corpus (data/study0/hainan_manifest.json)...", flush=True)
    hainan_docs = load_hainan_corpus(max_docs=args.max_docs)
    if not hainan_docs:
        print(
            f"Hainan corpus is empty or invalid. Ensure {HAINAN_MANIFEST} contains documents, each with text or file_path, and content length >= {MIN_CHARS} characters.",
            file=sys.stderr,
        )
        return 1
    _warn_sources(hainan_docs, hainan_outlets, "Hainan")
    print(f"  Hainan: {len(hainan_docs)} documents", flush=True)

    print("Loading non-Hainan corpus (data/study0/non_hainan_manifest.json)...", flush=True)
    non_hainan_docs = load_non_hainan_corpus(max_docs=args.max_docs)
    if not non_hainan_docs:
        print(
            f"Non-Hainan corpus is empty or invalid. Ensure {NON_HAINAN_MANIFEST} contains documents, each with text or file_path, and content length >= {MIN_CHARS} characters.",
            file=sys.stderr,
        )
        return 1
    _warn_sources(non_hainan_docs, non_hainan_outlets, "Non-Hainan")
    print(f"  Non-Hainan: {len(non_hainan_docs)} documents", flush=True)

    n = min(len(hainan_docs), len(non_hainan_docs))
    hainan_docs = hainan_docs[:n]
    non_hainan_docs = non_hainan_docs[:n]

    if args.dry_run:
        results = {
            "study": "Study 0",
            "purpose": "Justify a Hainan-specific assistant",
            "method": "Matched corpora comparison (Hainan media vs general media); cosine similarity divergence",
            "data_source": "data/study0/ only (separate from project main corpus)",
            "hainan_outlets": ["南海网", "海南日报", "海南广播电视总台", "新华网海南频道", "人民网海南频道"],
            "non_hainan_outlets": ["新华社", "人民日报", "BBC", "The New York Times", "Reuters", "AFP"],
            "config": {
                "embedding_model": DEFAULT_EMBEDDING_MODEL,
                "max_docs_per_corpus": n,
                "permutations": args.permutations,
                "dry_run": True,
            },
            "metrics": None,
            "conclusion": "Dry run: add real data to data/study0/ and run without --dry-run to compute metrics.",
        }
        print("Dry run: manifest and draft results only (no embedding).", flush=True)
    else:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("sentence_transformers required: pip install sentence-transformers", file=sys.stderr)
            return 1
        import numpy as np
        model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
        texts_h = [d["text"] for d in hainan_docs]
        texts_n = [d["text"] for d in non_hainan_docs]
        print("Encoding Hainan...", flush=True)
        emb_h = embed_documents(texts_h, model)
        print("Encoding non-Hainan...", flush=True)
        emb_n = embed_documents(texts_n, model)
        within_h, within_n, between = mean_within_between(emb_h, emb_n)
        delta, p_value = permutation_test(emb_h, emb_n, n_permutations=args.permutations)
        centroid_h = emb_h.mean(axis=0)
        centroid_n = emb_n.mean(axis=0)
        centroid_h = centroid_h / (np.linalg.norm(centroid_h) or 1e-8)
        centroid_n = centroid_n / (np.linalg.norm(centroid_n) or 1e-8)
        centroid_sim = float(centroid_h @ centroid_n)
        results = {
            "study": "Study 0",
            "purpose": "Justify a Hainan-specific assistant",
            "method": "Matched corpora comparison (Hainan media vs general media); cosine similarity divergence",
            "data_source": "data/study0/ only (separate from project main corpus)",
            "hainan_outlets": ["南海网", "海南日报", "海南广播电视总台", "新华网海南频道", "人民网海南频道"],
            "non_hainan_outlets": ["新华社", "人民日报", "BBC", "The New York Times", "Reuters", "AFP"],
            "config": {
                "embedding_model": DEFAULT_EMBEDDING_MODEL,
                "max_docs_per_corpus": n,
                "permutations": args.permutations,
            },
            "metrics": {
                "within_hainan_mean_cosine": round(within_h, 4),
                "within_non_hainan_mean_cosine": round(within_n, 4),
                "between_mean_cosine": round(between, 4),
                "distinctiveness_delta": round(delta, 4),
                "centroid_cosine": round(centroid_sim, 4),
                "permutation_p_value": round(p_value, 4),
            },
            "conclusion": (
                "Domain distinctiveness is statistically significant (p < 0.05); "
                "Hainan-focused media corpus is semantically divergent from general news corpus. "
                "A Hainan-specific retrieval-augmented assistant is warranted."
                if p_value < 0.05
                else "Distinctiveness delta positive but p >= 0.05; consider larger or more balanced sample."
            ),
        }
        if results.get("metrics"):
            m = results["metrics"]
            print("\n--- Distinctiveness result ---", flush=True)
            print(f"  Within Hainan (mean cosine):     {m['within_hainan_mean_cosine']:.4f}", flush=True)
            print(f"  Within non-Hainan (mean cosine): {m['within_non_hainan_mean_cosine']:.4f}", flush=True)
            print(f"  Between (mean cosine):           {m['between_mean_cosine']:.4f}", flush=True)
            print(f"  Distinctiveness delta:           {m['distinctiveness_delta']:.4f}", flush=True)
            print(f"  Permutation p-value:             {m['permutation_p_value']:.4f}", flush=True)
            print(f"  Conclusion: {results['conclusion'][:100]}...", flush=True)

    manifest = build_sampling_manifest(hainan_docs, non_hainan_docs)
    manifest_path = out_dir / "study0_sampling_manifest.json"
    manifest_path.write_text(
        json.dumps({"description": "Study 0 sampling manifest (Hainan media vs general media)", "documents": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote manifest: {manifest_path}", flush=True)

    results_path = out_dir / "study0_results.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote results: {results_path}", flush=True)

    if not args.no_plot and not args.dry_run and results.get("metrics"):
        try:
            from sklearn.manifold import TSNE
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
            combined = np.vstack([emb_h, emb_n])
            tsne = TSNE(n_components=2, random_state=42, perplexity=min(30, len(combined) - 1))
            xy = tsne.fit_transform(combined)
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.scatter(xy[: len(emb_h), 0], xy[: len(emb_h), 1], c="C0", label="Hainan media", alpha=0.6, s=20)
            ax.scatter(xy[len(emb_h) :, 0], xy[len(emb_h) :, 1], c="C1", label="General media", alpha=0.6, s=20)
            ax.legend()
            plot_path = out_dir / "study0_tsne.png"
            fig.savefig(plot_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"Wrote plot: {plot_path}", flush=True)
        except ImportError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
