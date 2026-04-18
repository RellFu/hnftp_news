#!/usr/bin/env python3
"""
Evaluation harness: run gold task set with and/or without retrieval.

Usage:
  python evaluation/harness/run.py                    # run with retrieval only
  python evaluation/harness/run.py --baseline         # run no-retrieval baseline only
  python evaluation/harness/run.py --both            # run both, compare metrics

Outputs: evaluation_results.json with citation support rate, latency, mean_angle_overlap
(expected_angle vs proposed_angle), Recall@k (proxy by keyword overlap), and run config.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLD_TASKS = PROJECT_ROOT / "evaluation" / "gold_tasks" / "tasks.json"
BACKEND_DIR = PROJECT_ROOT / "backend"
OUT_FILE = PROJECT_ROOT / "evaluation_results.json"

# 评估时跳过的 task id（留空则跑全部）；曾因 45/46 触发 LLM 400 而排除，已改为修改题目表述后保留
TASK_IDS_SKIP = set()

# Recall@k: use these k values (proxy relevance = word overlap span vs expected_angle+query)
RECALL_AT_K_LIST = [1, 5, 12]
# Span is "relevant" if overlap(ref_words, span_text_words) >= this (proxy, no gold labels)
RECALL_PROXY_OVERLAP_THRESHOLD = 0.10


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.strip()[:12]
    except Exception:
        pass
    return ""


def _angle_overlap(expected: str, proposed: str) -> float:
    """Word overlap: proportion of expected (lowercased) words that appear in proposed. Comparable across both arms."""
    if not (expected or "").strip():
        return 0.0
    a = set((expected or "").lower().split())
    b = set((proposed or "").lower().split())
    if not a:
        return 0.0
    return len(a & b) / len(a)


def _word_overlap(ref: str, text: str) -> float:
    """Proportion of ref words (lowercased) that appear in text. Used for recall proxy (no gold span labels)."""
    if not (ref or "").strip():
        return 0.0
    ref_w = set((ref or "").lower().split())
    text_w = set((text or "").lower().split())
    if not ref_w:
        return 0.0
    return len(ref_w & text_w) / len(ref_w)


def _recall_at_k_and_mrr(spans: list, ref: str, k_list: list) -> tuple[dict[int, int], float]:
    """
    Given ordered spans (each has .text), compute recall@k (proxy) and MRR.
    ref = expected_angle + " " + query for proxy relevance.
    Returns (recall_at_k dict: k -> 1 if hit else 0, mrr float).
    """
    recall = {k: 0 for k in k_list}
    first_rank = None
    ref = (ref or "").strip()
    if not ref:
        return recall, 0.0
    for i, span in enumerate(spans):
        text = getattr(span, "text", None) or ""
        ov = _word_overlap(ref, text)
        if ov >= RECALL_PROXY_OVERLAP_THRESHOLD:
            rank = i + 1
            if first_rank is None:
                first_rank = rank
            for k in k_list:
                if rank <= k:
                    recall[k] = 1
    mrr = (1.0 / first_rank) if first_rank is not None else 0.0
    return recall, mrr


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run gold task set (with/without retrieval).")
    parser.add_argument("--baseline", action="store_true", help="Run no-retrieval baseline only.")
    parser.add_argument("--both", action="store_true", help="Run both with-retrieval and baseline; compare.")
    args = parser.parse_args()

    run_baseline_only = args.baseline
    run_both = args.both
    run_with_retrieval = not run_baseline_only or run_both

    if not GOLD_TASKS.exists():
        print("No gold tasks. Add tasks to evaluation/gold_tasks/tasks.json")
        sys.exit(1)

    tasks = json.loads(GOLD_TASKS.read_text(encoding="utf-8"))
    if not tasks:
        print("Gold tasks file is empty.")
        sys.exit(1)
    if TASK_IDS_SKIP:
        tasks = [t for t in tasks if t.get("id") not in TASK_IDS_SKIP]
        print(f"Skipping {len(TASK_IDS_SKIP)} tasks: {sorted(TASK_IDS_SKIP)}. Running {len(tasks)} tasks.")

    sys.path.insert(0, str(BACKEND_DIR))
    from app.services.reactive_pitch import run_reactive_pitch
    from app.services.retrieval.retrieval import hybrid_retrieve

    run_config = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": _git_sha(),
        "LLM_MODEL": os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_API_MODEL") or "gpt-4o-mini",
        "task_count": len(tasks),
        "skipped_task_ids": sorted(TASK_IDS_SKIP) if TASK_IDS_SKIP else [],
        "modes": [],
    }
    if run_with_retrieval:
        run_config["modes"].append("with_retrieval")
    if run_baseline_only or run_both:
        run_config["modes"].append("no_retrieval")

    all_results = []

    for mode_name, skip_retrieval in [
        ("with_retrieval", False),
        ("no_retrieval", True),
    ]:
        if mode_name == "with_retrieval" and not run_with_retrieval:
            continue
        if mode_name == "no_retrieval" and not (run_baseline_only or run_both):
            continue

        print(f"\n=== Running {mode_name} ({len(tasks)} tasks) ===")
        mode_results = []
        for t in tasks:
            task_id = t.get("id", "")
            query = (t.get("query") or "").strip()
            if not query:
                continue
            params = {"beat": query, "skip_retrieval": skip_retrieval}
            start = time.perf_counter()
            out = run_reactive_pitch(params)
            latency_ms = (time.perf_counter() - start) * 1000

            # Citation support = "output backed by retrieval evidence". With retrieval: count 1 only when we had evidence (web or RAG) and produced output. No-retrieval baseline has no evidence by definition, so citation_support is always 0 for baseline (so that citation_lift proves retrieval adds value).
            had_evidence = out.get("topic_relevant", False) and (out.get("rag_used") or len(out.get("web_sources") or []) > 0)
            has_output = bool(
                (out.get("news_value_assessment") or "").strip()
                or (out.get("proposed_angle") or "").strip()
                or (out.get("pitch_plan") or "").strip()
            )
            # Baseline: no retrieval -> no citations; with_retrieval: citation = had evidence and has output
            citation_support = 1 if (has_output and (had_evidence if not skip_retrieval else False)) else 0

            # expected_angle vs proposed_angle (gold vs model output)
            expected_angle = (t.get("expected_angle") or "").strip()
            proposed_angle = (out.get("proposed_angle") or "").strip()
            angle_overlap = _angle_overlap(expected_angle, proposed_angle) if expected_angle else None

            row = {
                "task_id": task_id,
                "query": query[:80],
                "mode": mode_name,
                "latency_ms": round(latency_ms, 2),
                "citation_support": citation_support,
                "has_output": has_output,
                "topic_relevant": out.get("topic_relevant"),  # 无输出时便于排查：是否因 topic_relevant=False 跳过 LLM
                "angle_overlap": round(angle_overlap, 4) if angle_overlap is not None else None,
                "expected_angle": expected_angle[:120] if expected_angle else None,
                "proposed_angle": proposed_angle[:120] if proposed_angle else None,
                "error": out.get("error"),
            }

            # Recall@k (proxy) and MRR: only when with_retrieval, run retrieval to get span texts
            if mode_name == "with_retrieval":
                try:
                    retrieval_result = hybrid_retrieve(query, original_topic=query)
                    spans = getattr(retrieval_result, "spans", []) or []
                    ref = f"{expected_angle} {query}".strip()
                    recall_at_k, mrr = _recall_at_k_and_mrr(spans, ref, RECALL_AT_K_LIST)
                    row["recall_at_1"] = recall_at_k.get(1, 0)
                    row["recall_at_5"] = recall_at_k.get(5, 0)
                    row["recall_at_12"] = recall_at_k.get(12, 0)
                    row["mrr"] = round(mrr, 4)
                except Exception as e:
                    row["recall_at_1"] = row["recall_at_5"] = row["recall_at_12"] = None
                    row["mrr"] = None
                    row["recall_error"] = str(e)[:200]

            mode_results.append(row)
            ao_str = f", angle_overlap={angle_overlap:.2f}" if angle_overlap is not None else ""
            recall_str = ""
            if mode_name == "with_retrieval" and row.get("recall_at_12") is not None:
                recall_str = f", R@12={row['recall_at_12']}, MRR={row.get('mrr') or 0:.2f}"
            print(f"  {task_id}: {latency_ms:.0f} ms, output={has_output}, citation_support={citation_support}{ao_str}{recall_str}")

        n = len(mode_results)
        citation_rate = sum(r["citation_support"] for r in mode_results) / n if n else 0
        avg_latency = sum(r["latency_ms"] for r in mode_results) / n if n else 0
        angle_overlaps = [r["angle_overlap"] for r in mode_results if r.get("angle_overlap") is not None]
        mean_angle = sum(angle_overlaps) / len(angle_overlaps) if angle_overlaps else None
        print(f"  Citation support rate: {citation_rate:.2%}, Avg latency: {avg_latency:.0f} ms", end="")
        if mean_angle is not None:
            print(f", Mean angle_overlap (expected vs proposed): {mean_angle:.2f}", end="")
        print()
        run_config[f"{mode_name}_citation_rate"] = citation_rate
        run_config[f"{mode_name}_avg_latency_ms"] = round(avg_latency, 2)
        if mean_angle is not None:
            run_config[f"{mode_name}_mean_angle_overlap"] = round(mean_angle, 4)

        # Recall@k and MRR (with_retrieval only)
        if mode_name == "with_retrieval":
            r1 = [r["recall_at_1"] for r in mode_results if r.get("recall_at_1") is not None]
            r5 = [r["recall_at_5"] for r in mode_results if r.get("recall_at_5") is not None]
            r12 = [r["recall_at_12"] for r in mode_results if r.get("recall_at_12") is not None]
            mrr_list = [r["mrr"] for r in mode_results if r.get("mrr") is not None]
            if r12:
                run_config["with_retrieval_mean_recall_at_1"] = round(sum(r1) / len(r1), 4) if r1 else None
                run_config["with_retrieval_mean_recall_at_5"] = round(sum(r5) / len(r5), 4) if r5 else None
                run_config["with_retrieval_mean_recall_at_12"] = round(sum(r12) / len(r12), 4)
                run_config["with_retrieval_mean_mrr"] = round(sum(mrr_list) / len(mrr_list), 4) if mrr_list else None
                rr1 = run_config.get("with_retrieval_mean_recall_at_1") or 0
                rr5 = run_config.get("with_retrieval_mean_recall_at_5") or 0
                rr12 = run_config.get("with_retrieval_mean_recall_at_12") or 0
                mmrr = run_config.get("with_retrieval_mean_mrr") or 0
                print(f"  Recall@1: {rr1:.2%}, Recall@5: {rr5:.2%}, Recall@12: {rr12:.2%}, Mean MRR: {mmrr:.2f}")

        all_results.extend(mode_results)

    run_config["results"] = all_results
    if run_both and run_config.get("with_retrieval_citation_rate") is not None and run_config.get("no_retrieval_citation_rate") is not None:
        run_config["citation_lift"] = run_config["with_retrieval_citation_rate"] - run_config["no_retrieval_citation_rate"]
    if run_both and run_config.get("with_retrieval_mean_angle_overlap") is not None and run_config.get("no_retrieval_mean_angle_overlap") is not None:
        run_config["angle_lift"] = run_config["with_retrieval_mean_angle_overlap"] - run_config["no_retrieval_mean_angle_overlap"]

    OUT_FILE.write_text(json.dumps(run_config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOutput: {OUT_FILE}")


if __name__ == "__main__":
    main()
