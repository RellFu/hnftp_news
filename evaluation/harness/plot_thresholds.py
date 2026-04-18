#!/usr/bin/env python3
"""
Visualize threshold tuning results from evaluation/threshold_tuning_results.json.

Outputs (default: evaluation/figures/):
- threshold_line_latency_by_threshold.png
- threshold_line_latency_by_topk.png
- threshold_line_quality_by_threshold.png
- threshold_recommended_highlight.png
- threshold_all_in_one.png
- threshold_decision_line.png

Usage:
  python evaluation/harness/plot_thresholds.py
  python evaluation/harness/plot_thresholds.py --input evaluation/threshold_tuning_results.json --outdir evaluation/figures
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "evaluation" / "threshold_tuning_results.json"
DEFAULT_OUTDIR = PROJECT_ROOT / "evaluation" / "figures"


def _load_results(path: Path) -> tuple[list[dict], dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No results found in: {path}")
    recommended = data.get("recommended", {}) if isinstance(data, dict) else {}
    return rows, recommended


def _sorted_unique(values: list) -> list:
    return sorted(set(values))


def _make_grid(rows: list[dict], value_key: str) -> tuple[list[int], list[float], list[list[float]]]:
    top_ks = _sorted_unique([int(r["top_k"]) for r in rows])
    thresholds = _sorted_unique([float(r["reranker_threshold"]) for r in rows])
    lookup = {(int(r["top_k"]), float(r["reranker_threshold"])): float(r[value_key]) for r in rows}
    grid = []
    for k in top_ks:
        row_vals = []
        for t in thresholds:
            row_vals.append(lookup.get((k, t), 0.0))
        grid.append(row_vals)
    return top_ks, thresholds, grid


def _plot_heatmap(
    rows: list[dict],
    value_key: str,
    title: str,
    cbar_label: str,
    out_path: Path,
    cmap: str = "viridis",
) -> None:
    top_ks, thresholds, grid = _make_grid(rows, value_key)
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(grid, aspect="auto", cmap=cmap)

    ax.set_xticks(range(len(thresholds)))
    ax.set_xticklabels([f"{x:.2f}" for x in thresholds], rotation=45)
    ax.set_yticks(range(len(top_ks)))
    ax.set_yticklabels([str(x) for x in top_ks])
    ax.set_xlabel("reranker_threshold")
    ax.set_ylabel("top_k")
    ax.set_title(title)
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label(cbar_label)

    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_line_latency_by_threshold(rows: list[dict], out_path: Path) -> None:
    top_ks = _sorted_unique([int(r["top_k"]) for r in rows])
    thresholds = _sorted_unique([float(r["reranker_threshold"]) for r in rows])
    latency_lookup = {(int(r["top_k"]), float(r["reranker_threshold"])): float(r["mean_latency_ms"]) for r in rows}

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for t in thresholds:
        ys = [latency_lookup.get((k, t), 0.0) for k in top_ks]
        ax.plot(top_ks, ys, marker="o", linewidth=1.8, label=f"threshold={t:.2f}")

    ax.set_xlabel("top_k")
    ax.set_ylabel("mean_latency_ms")
    ax.set_title("Latency vs top_k (grouped by threshold)")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_line_latency_by_topk(rows: list[dict], out_path: Path) -> None:
    top_ks = _sorted_unique([int(r["top_k"]) for r in rows])
    thresholds = _sorted_unique([float(r["reranker_threshold"]) for r in rows])
    latency_lookup = {(int(r["top_k"]), float(r["reranker_threshold"])): float(r["mean_latency_ms"]) for r in rows}

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for k in top_ks:
        ys = [latency_lookup.get((k, t), 0.0) for t in thresholds]
        ax.plot(thresholds, ys, marker="o", linewidth=1.8, label=f"top_k={k}")

    ax.set_xlabel("reranker_threshold")
    ax.set_ylabel("mean_latency_ms")
    ax.set_title("Latency vs threshold (grouped by top_k)")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_line_quality_by_threshold(rows: list[dict], out_path: Path) -> None:
    top_ks = _sorted_unique([int(r["top_k"]) for r in rows])
    thresholds = _sorted_unique([float(r["reranker_threshold"]) for r in rows])
    quality_lookup = {
        (int(r["top_k"]), float(r["reranker_threshold"])): float(r["citation_support_rate"]) for r in rows
    }

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for k in top_ks:
        ys = [quality_lookup.get((k, t), 0.0) for t in thresholds]
        ax.plot(thresholds, ys, marker="o", linewidth=1.8, label=f"top_k={k}")

    ax.set_xlabel("reranker_threshold")
    ax.set_ylabel("citation_support_rate")
    ax.set_ylim(0.0, 1.05)
    ax.set_title("Citation support rate vs threshold (grouped by top_k)")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_recommended_highlight(rows: list[dict], recommended: dict, out_path: Path) -> None:
    top_ks = [int(r["top_k"]) for r in rows]
    thresholds = [float(r["reranker_threshold"]) for r in rows]
    x = [float(r["mean_latency_ms"]) for r in rows]
    y = [float(r["mean_max_reranker_score"]) for r in rows]

    rec_k = int(recommended.get("top_k", -1))
    rec_t = float(recommended.get("reranker_threshold", -1.0))

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(x, y, c="lightgray", s=70, alpha=0.8, label="all configs")

    highlighted = False
    for i, (k, t) in enumerate(zip(top_ks, thresholds)):
        if k == rec_k and abs(t - rec_t) < 1e-9:
            ax.scatter([x[i]], [y[i]], c="red", s=180, marker="*", label="recommended")
            ax.annotate(
                f"recommended: k={k}, t={t:.2f}",
                (x[i], y[i]),
                xytext=(8, 8),
                textcoords="offset points",
                fontsize=9,
                color="red",
            )
            highlighted = True
            break

    if not highlighted:
        ax.text(
            0.02,
            0.02,
            "No valid recommended config found in JSON",
            transform=ax.transAxes,
            color="red",
            fontsize=9,
        )

    ax.set_xlabel("mean_latency_ms")
    ax.set_ylabel("mean_max_reranker_score")
    ax.set_title("Recommended Config Highlight")
    ax.legend(loc="best")
    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_all_in_one(rows: list[dict], recommended: dict, out_path: Path) -> None:
    """
    One-chart overview:
    - x: mean_latency_ms
    - y: mean_max_reranker_score
    - color: reranker_threshold
    - marker size: top_k
    - annotation: citation_support_rate
    - highlight: recommended config
    """
    x = [float(r["mean_latency_ms"]) for r in rows]
    y = [float(r["mean_max_reranker_score"]) for r in rows]
    thresholds = [float(r["reranker_threshold"]) for r in rows]
    top_ks = [int(r["top_k"]) for r in rows]
    citations = [float(r["citation_support_rate"]) for r in rows]

    # Make top_k visually distinguishable while avoiding oversized markers.
    sizes = [40 + k * 18 for k in top_ks]

    fig, ax = plt.subplots(figsize=(11, 6.5))
    sc = ax.scatter(
        x,
        y,
        c=thresholds,
        s=sizes,
        cmap="viridis",
        alpha=0.85,
        edgecolors="black",
        linewidths=0.4,
    )

    # Keep labels compact; annotate only citation as a percentage.
    for xi, yi, c in zip(x, y, citations):
        ax.text(xi, yi, f"{c:.0%}", fontsize=7, ha="center", va="center", color="white")

    rec_k = int(recommended.get("top_k", -1))
    rec_t = float(recommended.get("reranker_threshold", -1.0))
    for r in rows:
        if int(r["top_k"]) == rec_k and abs(float(r["reranker_threshold"]) - rec_t) < 1e-9:
            rx = float(r["mean_latency_ms"])
            ry = float(r["mean_max_reranker_score"])
            ax.scatter([rx], [ry], c="red", s=260, marker="*", edgecolors="black", linewidths=0.7, zorder=5)
            ax.annotate(
                f"recommended: k={rec_k}, t={rec_t:.2f}",
                (rx, ry),
                xytext=(10, 10),
                textcoords="offset points",
                fontsize=9,
                color="red",
            )
            break

    ax.set_xlabel("mean_latency_ms")
    ax.set_ylabel("mean_max_reranker_score")
    ax.set_title("All-in-One Threshold Tuning Overview")
    ax.grid(alpha=0.2)

    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label("reranker_threshold (color)")

    # Size legend for top_k
    legend_topks = sorted(set(top_ks))
    handles = [
        plt.scatter([], [], s=40 + k * 18, c="gray", alpha=0.6, edgecolors="black", linewidths=0.4)
        for k in legend_topks
    ]
    labels = [f"top_k={k} (size)" for k in legend_topks]
    ax.legend(handles, labels, loc="lower right", fontsize=8, frameon=True)

    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_decision_line(rows: list[dict], recommended: dict, out_path: Path) -> None:
    """
    Decision-focused line chart explaining why (top_k, threshold) is selected.

    Panel A (left):
      mean_max_reranker_score vs top_k for each threshold
      -> shows quality tie / near tie across thresholds.
    Panel B (right):
      latency vs threshold at selected top_k
      -> pick the minimum-latency threshold under the selected top_k.
    """
    top_ks = _sorted_unique([int(r["top_k"]) for r in rows])
    thresholds = _sorted_unique([float(r["reranker_threshold"]) for r in rows])
    rec_k = int(recommended.get("top_k", -1))
    rec_t = float(recommended.get("reranker_threshold", -1.0))

    quality_lookup = {
        (int(r["top_k"]), float(r["reranker_threshold"])): float(r["mean_max_reranker_score"])
        for r in rows
    }
    latency_lookup = {
        (int(r["top_k"]), float(r["reranker_threshold"])): float(r["mean_latency_ms"])
        for r in rows
    }

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Panel A: quality lines by threshold across top_k
    for t in thresholds:
        ys = [quality_lookup.get((k, t), 0.0) for k in top_ks]
        lw = 2.2 if abs(t - rec_t) < 1e-9 else 1.2
        alpha = 1.0 if abs(t - rec_t) < 1e-9 else 0.45
        ax1.plot(top_ks, ys, marker="o", linewidth=lw, alpha=alpha, label=f"t={t:.2f}")

    if rec_k in top_ks and rec_t in thresholds:
        ax1.scatter(
            [rec_k],
            [quality_lookup.get((rec_k, rec_t), 0.0)],
            c="red",
            marker="*",
            s=180,
            zorder=5,
        )
    ax1.set_title("Step 1: quality-first selection")
    ax1.set_xlabel("top_k")
    ax1.set_ylabel("mean_max_reranker_score")
    ax1.grid(alpha=0.25)
    ax1.legend(ncol=2, fontsize=8)

    # Panel B: at selected top_k, choose threshold by lower latency
    y2 = [latency_lookup.get((rec_k, t), 0.0) for t in thresholds]
    ax2.plot(thresholds, y2, marker="o", linewidth=2.0, color="#2C7FB8")
    if rec_k in top_ks and rec_t in thresholds:
        rec_latency = latency_lookup.get((rec_k, rec_t), 0.0)
        ax2.scatter([rec_t], [rec_latency], c="red", marker="*", s=200, zorder=6)
        ax2.annotate(
            f"selected: k={rec_k}, t={rec_t:.2f}",
            (rec_t, rec_latency),
            xytext=(10, 8),
            textcoords="offset points",
            fontsize=9,
            color="red",
        )
    ax2.set_title(f"Step 2: latency tie-break at top_k={rec_k}")
    ax2.set_xlabel("reranker_threshold")
    ax2.set_ylabel("mean_latency_ms")
    ax2.grid(alpha=0.25)

    fig.suptitle("Why final (top_k, threshold) was chosen", fontsize=12)
    plt.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot threshold tuning results.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to threshold_tuning_results.json")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR, help="Output directory for PNG files")
    args = parser.parse_args()

    rows, recommended = _load_results(args.input)
    args.outdir.mkdir(parents=True, exist_ok=True)

    out1 = args.outdir / "threshold_line_latency_by_threshold.png"
    out2 = args.outdir / "threshold_line_latency_by_topk.png"
    out3 = args.outdir / "threshold_line_quality_by_threshold.png"
    out4 = args.outdir / "threshold_recommended_highlight.png"
    out5 = args.outdir / "threshold_all_in_one.png"
    out6 = args.outdir / "threshold_decision_line.png"

    _plot_line_latency_by_threshold(rows=rows, out_path=out1)
    _plot_line_latency_by_topk(rows=rows, out_path=out2)
    _plot_line_quality_by_threshold(rows=rows, out_path=out3)
    _plot_recommended_highlight(rows=rows, recommended=recommended, out_path=out4)
    _plot_all_in_one(rows=rows, recommended=recommended, out_path=out5)
    _plot_decision_line(rows=rows, recommended=recommended, out_path=out6)

    print("Saved figures:")
    print(f"- {out1}")
    print(f"- {out2}")
    print(f"- {out3}")
    print(f"- {out4}")
    print(f"- {out5}")
    print(f"- {out6}")


if __name__ == "__main__":
    main()
