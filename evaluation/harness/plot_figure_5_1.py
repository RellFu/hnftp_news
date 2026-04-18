#!/usr/bin/env python3
"""
Create dissertation Figure 5.1 from threshold tuning results.

Figure objective:
- x-axis: reranker threshold
- y-axis: mean latency (ms)
- representative lines: top_k in {2, 5, 8, 12}
- explicit highlight: top_k=12, threshold=0.45
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUT_JSON = PROJECT_ROOT / "evaluation" / "threshold_tuning_results.json"
OUTDIR = PROJECT_ROOT / "evaluation" / "figures"
OUTFIG = OUTDIR / "figure_5_1_latency_threshold_tradeoff.png"

REPRESENTATIVE_TOP_K = [2, 5, 8, 12]
FINAL_TOP_K = 12
FINAL_THRESHOLD = 0.45

CAPTION = (
    "Figure 5.1. Mean latency across reranker-threshold settings under representative "
    "top-k configurations."
)


def _load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No tuning rows found in: {path}")
    return rows


def _collect_series(rows: list[dict]) -> dict[int, list[tuple[float, float]]]:
    series: dict[int, list[tuple[float, float]]] = {k: [] for k in REPRESENTATIVE_TOP_K}
    for row in rows:
        k = int(row["top_k"])
        if k not in series:
            continue
        threshold = float(row["reranker_threshold"])
        latency = float(row["mean_latency_ms"])
        series[k].append((threshold, latency))

    for k in series:
        series[k].sort(key=lambda x: x[0])
        if not series[k]:
            raise ValueError(f"No points found for top_k={k} in input JSON")
    return series


def _find_final_latency(series: dict[int, list[tuple[float, float]]]) -> float:
    for threshold, latency in series[FINAL_TOP_K]:
        if abs(threshold - FINAL_THRESHOLD) < 1e-12:
            return latency
    raise ValueError(
        f"Final configuration point (top_k={FINAL_TOP_K}, threshold={FINAL_THRESHOLD}) "
        "not found in input JSON."
    )


def _plot(series: dict[int, list[tuple[float, float]]], outfig: Path) -> float:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#333333",
            "axes.labelcolor": "#111111",
            "xtick.color": "#111111",
            "ytick.color": "#111111",
            "grid.color": "#CFCFCF",
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "legend.fontsize": 10,
        }
    )

    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    colours = {
        2: "#1F77B4",
        5: "#2CA02C",
        8: "#9467BD",
        12: "#D62728",
    }

    for k in REPRESENTATIVE_TOP_K:
        points = series[k]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        width = 2.4 if k == FINAL_TOP_K else 1.9
        marker_size = 5.2 if k == FINAL_TOP_K else 4.4
        ax.plot(
            xs,
            ys,
            label=f"top_k={k}",
            color=colours[k],
            linewidth=width,
            marker="o",
            markersize=marker_size,
        )

    final_latency = _find_final_latency(series)
    ax.scatter(
        [FINAL_THRESHOLD],
        [final_latency],
        color="#D62728",
        edgecolors="black",
        linewidths=0.8,
        s=120,
        marker="*",
        zorder=8,
        label="Final default (12, 0.45)",
    )
    ax.annotate(
        f"Final default\n(top_k=12, threshold=0.45)\nmean latency={final_latency:.2f} ms",
        xy=(FINAL_THRESHOLD, final_latency),
        xytext=(12, 15),
        textcoords="offset points",
        fontsize=9.5,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#777777", "alpha": 0.95},
    )

    ax.set_xlabel("Reranker threshold")
    ax.set_ylabel("Mean latency (ms)")
    ax.grid(True, linestyle="-", linewidth=0.6, alpha=0.55)
    ax.set_xlim(0.14, 0.51)
    ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#777777")

    fig.tight_layout()
    fig.savefig(outfig, dpi=400)
    plt.close(fig)
    return final_latency


def main() -> None:
    rows = _load_rows(INPUT_JSON)
    series = _collect_series(rows)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    final_latency = _plot(series=series, outfig=OUTFIG)

    interpretation = (
        "Across the representative settings, mean latency generally exhibits greater "
        "variation with changes in top_k than with incremental threshold adjustments, "
        "although local spikes indicate workload-sensitive behaviour at specific operating "
        "points. The selected default configuration (top_k=12, reranker_threshold=0.45) "
        f"records a mean latency of {final_latency:.2f} ms, which is not the global minimum, "
        "but remains within a practical runtime range for deployment. Given that citation "
        "support is saturated across the tuning grid, this selection is appropriately "
        "interpreted as a quality-first decision that preserves broad evidence coverage "
        "while maintaining acceptable system responsiveness."
    )

    print(f"Saved Figure 5.1 PNG: {OUTFIG}")
    print(f"Saved plotting script: {Path(__file__).resolve()}")
    print()
    print(f'Caption: "{CAPTION}"')
    print()
    print("Interpretation (Chapter 5):")
    print(interpretation)


if __name__ == "__main__":
    main()
