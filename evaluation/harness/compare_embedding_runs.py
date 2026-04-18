#!/usr/bin/env python3
"""
Compare two evaluation_results*.json from different embedding model runs (A/B).

Usage (from project root):
  # After running run.py --both for model A, save: cp evaluation_results.json evaluation_results_minilm.json
  # After running run.py --both for model B, save: cp evaluation_results.json evaluation_results_multilingual.json
  python evaluation/harness/compare_embedding_runs.py evaluation_results_minilm.json evaluation_results_multilingual.json
  # With custom labels:
  python evaluation/harness/compare_embedding_runs.py --label-a "MiniLM-L6" --label-b "multilingual" evaluation_results_minilm.json evaluation_results_multilingual.json
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_metrics(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "citation_rate": data.get("with_retrieval_citation_rate"),
        "mean_angle_overlap": data.get("with_retrieval_mean_angle_overlap"),
        "recall_at_12": data.get("with_retrieval_mean_recall_at_12"),
        "mean_mrr": data.get("with_retrieval_mean_mrr"),
        "avg_latency_ms": data.get("with_retrieval_avg_latency_ms"),
        "angle_lift": data.get("angle_lift"),
        "task_count": data.get("task_count"),
        "timestamp": data.get("timestamp", "")[:19],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two evaluation_results JSON files (embedding A/B)."
    )
    parser.add_argument("file_a", type=Path, help="First run JSON (e.g. baseline model)")
    parser.add_argument("file_b", type=Path, help="Second run JSON (e.g. candidate model)")
    parser.add_argument("--label-a", default=None, help="Label for first run (default: file name stem)")
    parser.add_argument("--label-b", default=None, help="Label for second run (default: file name stem)")
    args = parser.parse_args()

    for p in (args.file_a, args.file_b):
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not (p.exists() and p.is_file()):
            print(f"Error: not found or not file: {p}", file=sys.stderr)
            sys.exit(1)

    label_a = args.label_a or args.file_a.stem
    label_b = args.label_b or args.file_b.stem

    path_a = args.file_a if args.file_a.is_absolute() else PROJECT_ROOT / args.file_a
    path_b = args.file_b if args.file_b.is_absolute() else PROJECT_ROOT / args.file_b

    ma = load_metrics(path_a)
    mb = load_metrics(path_b)

    def fmt(v, is_pct=False):
        if v is None:
            return "—"
        if is_pct:
            return f"{v:.2%}"
        if isinstance(v, float):
            return f"{v:.4f}" if v < 10 else f"{v:.2f}"
        return str(v)

    print("Embedding A/B comparison")
    print("=" * 60)
    print(f"  A: {label_a}  ({path_a.name})")
    print(f"  B: {label_b}  ({path_b.name})")
    print()
    print(f"{'Metric':<28} {'A':<14} {'B':<14} {'Diff (B-A)'}")
    print("-" * 70)
    for key, name, pct in [
        ("citation_rate", "Citation rate (with_ret)", True),
        ("mean_angle_overlap", "Mean angle_overlap", False),
        ("recall_at_12", "Recall@12", True),
        ("mean_mrr", "Mean MRR", False),
        ("avg_latency_ms", "Avg latency (ms)", False),
        ("angle_lift", "Angle lift", False),
    ]:
        va, vb = ma.get(key), mb.get(key)
        diff = ""
        if va is not None and vb is not None and isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d = vb - va
            diff = f"{d:+.4f}" if isinstance(va, float) and abs(va) < 10 else f"{d:+.2f}"
        print(f"{name:<28} {fmt(va, pct):<14} {fmt(vb, pct):<14} {diff}")
    print("-" * 70)
    print(f"Tasks: A={ma.get('task_count')}  B={mb.get('task_count')}  |  Timestamps: A={ma.get('timestamp')}  B={mb.get('timestamp')}")
    print()
    print("If B has higher citation_rate, angle_overlap, recall@12, MRR and similar or lower latency, consider switching default to B.")


if __name__ == "__main__":
    main()
