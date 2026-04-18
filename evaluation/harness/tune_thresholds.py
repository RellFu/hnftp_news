#!/usr/bin/env python3
"""
Threshold tuning: sweep top_k and reranker_threshold on a dev set with
multiple metrics and a clear recommendation rule.

What is "dev" (development set)?
  A separate set of tasks used only for choosing hyperparameters (top_k, threshold).
  Loaded only from dev_tasks.json; no use of tasks.json (gold), so dev and gold
  stay independent and reported eval results are not overfitted. Use 25–30 tasks
  in dev_tasks.json; same schema as tasks.json (see evaluation/gold_tasks/README.md).

Method:
- Dev set size: at least MIN_DEV_TASKS (default 25) for stable citation_rate and
  mean_max_reranker_score.
- For each (top_k, threshold): citation_support_rate, mean_max_reranker_score,
  mean_latency_ms, std_latency_ms.
- Recommendation (quality-first, news business): only consider top_k >= MIN_TOP_K (default 5) so
  retrieval returns enough evidence for reporting. Among those with citation_rate >= 90%, pick
  highest mean_max_reranker_score, then higher top_k, then lower latency. Speed is not favored over quality.

Usage (must run from project root):
  cd /path/to/news
  python evaluation/harness/tune_thresholds.py

Output: table, recommended (top_k, threshold), and saved to evaluation/threshold_tuning_output.txt
        and evaluation/threshold_tuning_results.json.
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEV_TASKS = PROJECT_ROOT / "evaluation" / "gold_tasks" / "dev_tasks.json"
BACKEND_DIR = PROJECT_ROOT / "backend"
MIN_DEV_TASKS = 25
MIN_CITATION_RATE = 0.90
# Business constraint: news reporting needs sufficient evidence; top_k < 5 is not recommended.
MIN_TOP_K = 5


def _load_dev_tasks() -> list[dict]:
    """Load dev set only from dev_tasks.json. Dev and gold stay independent; no fallback to gold."""
    if not DEV_TASKS.exists():
        return []
    try:
        data = json.loads(DEV_TASKS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    tasks = [t for t in data if isinstance(t, dict) and (t.get("query") or "").strip()]
    return tasks


def _max_reranker_score(spans: list) -> float:
    if not spans:
        return 0.0
    return max((getattr(s, "reranker_score") or 0.0) for s in spans)


def main():
    print(f"Loading dev set from: {DEV_TASKS}", flush=True)
    tasks = _load_dev_tasks()
    if not tasks:
        print(f"No dev tasks found at {DEV_TASKS}. Run from project root (e.g. cd /path/to/news). Add dev_tasks.json (see evaluation/gold_tasks/README.md).", flush=True)
        sys.exit(1)
    print(f"Loaded {len(tasks)} dev tasks. Running threshold sweep...\n", flush=True)

    if len(tasks) < MIN_DEV_TASKS:
        print(f"Warning: dev set has only {len(tasks)} tasks. For more reliable tuning, expand to at least {MIN_DEV_TASKS} (recommended 30).\n")

    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.retrieval import hybrid_retrieve

    top_k_values = [2, 3, 5, 8, 10, 12]
    threshold_values = [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
    results = []

    for top_k in top_k_values:
        for reranker_threshold in threshold_values:
            support_count = 0
            latencies = []
            max_scores = []
            for t in tasks:
                query = (t.get("query") or "").strip()
                if not query:
                    continue
                start = time.perf_counter()
                r = hybrid_retrieve(query, top_k=top_k, reranker_threshold=reranker_threshold, original_topic=query)
                elapsed_ms = (time.perf_counter() - start) * 1000
                latencies.append(elapsed_ms)
                max_scores.append(_max_reranker_score(r.spans))
                if r.evidence_sufficient:
                    support_count += 1
            n = len(latencies)
            rate = support_count / n if n else 0
            avg_ms = sum(latencies) / n if n else 0
            std_ms = (sum((x - avg_ms) ** 2 for x in latencies) / n) ** 0.5 if n else 0
            mean_max = sum(max_scores) / n if n else 0
            results.append({
                "top_k": top_k,
                "reranker_threshold": reranker_threshold,
                "citation_support_rate": round(rate, 4),
                "mean_max_reranker_score": round(mean_max, 4),
                "mean_latency_ms": round(avg_ms, 2),
                "std_latency_ms": round(std_ms, 2),
                "tasks": n,
            })

    # Recommend: quality-first, with business constraint (top_k >= MIN_TOP_K for sufficient evidence in news).
    # Among configs with citation_rate >= bar and top_k >= MIN_TOP_K: max mean_max_reranker_score, then prefer higher top_k (more evidence), then lower latency.
    meets_bar = [r for r in results if r["citation_support_rate"] >= MIN_CITATION_RATE and r["top_k"] >= MIN_TOP_K]
    if meets_bar:
        best = max(meets_bar, key=lambda r: (r["mean_max_reranker_score"], r["top_k"], -r["mean_latency_ms"]))
        reason = f"quality-first: highest mean_max_reranker_score, top_k>={MIN_TOP_K} (sufficient evidence for news), among citation_rate>={MIN_CITATION_RATE:.0%}"
    else:
        # Fallback: relax top_k constraint, still prefer quality
        meets_cite = [r for r in results if r["citation_support_rate"] >= MIN_CITATION_RATE]
        if meets_cite:
            best = max(meets_cite, key=lambda r: (r["mean_max_reranker_score"], r["top_k"], -r["mean_latency_ms"]))
            reason = f"citation_rate>={MIN_CITATION_RATE:.0%}; no config with top_k>={MIN_TOP_K}; picked best quality (consider adding top_k>={MIN_TOP_K} to scan)"
        else:
            best = max(results, key=lambda r: (r["citation_support_rate"], r["mean_max_reranker_score"], r["top_k"], -r["mean_latency_ms"]))
            reason = f"no config reached citation_rate>={MIN_CITATION_RATE:.0%}; picked best citation_rate and quality"

    # Build output
    header = f"{'top_k':<6} {'threshold':<10} {'cite_rate':<10} {'mean_max':<10} {'latency_ms':<12} {'std_ms':<8}\n"
    sep = "-" * 60 + "\n"
    lines = [
        "Dev set threshold tuning (quality-first; news: sufficient evidence, top_k >= 5)\n",
        f"Dev tasks: {len(tasks)}  |  Min citation rate: {MIN_CITATION_RATE:.0%}  |  Min top_k (business): {MIN_TOP_K}\n\n",
        header,
        sep,
    ]
    for row in results:
        lines.append(
            f"{row['top_k']:<6} {row['reranker_threshold']:<10} "
            f"{row['citation_support_rate']:<10.2%} {row['mean_max_reranker_score']:<10.4f} "
            f"{row['mean_latency_ms']:<12.2f} {row['std_latency_ms']:<8.2f}\n"
        )
    lines.append("\n")
    lines.append(f"Recommended: top_k={best['top_k']}, reranker_threshold={best['reranker_threshold']}  ({reason})\n")
    lines.append(f"  -> citation_rate={best['citation_support_rate']:.2%}, mean_max_score={best['mean_max_reranker_score']:.4f}, latency={best['mean_latency_ms']:.2f} ms\n")
    lines.append("\nSet TOP_K and RERANKER_THRESHOLD in backend/app/core/config.py (or use the recommended values).\n")

    out_text = "".join(lines)
    print(out_text, end="", flush=True)

    out_file = PROJECT_ROOT / "evaluation" / "threshold_tuning_output.txt"
    out_file.write_text(out_text, encoding="utf-8")

    results_json = {
        "dev_task_count": len(tasks),
        "min_citation_rate_bar": MIN_CITATION_RATE,
        "results": results,
        "recommended": {
            "top_k": best["top_k"],
            "reranker_threshold": best["reranker_threshold"],
            "reason": reason,
        },
    }
    json_file = PROJECT_ROOT / "evaluation" / "threshold_tuning_results.json"
    json_file.write_text(json.dumps(results_json, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Output saved to: {out_file}", flush=True)
    print(f"JSON (for reproducibility): {json_file}", flush=True)


if __name__ == "__main__":
    main()
