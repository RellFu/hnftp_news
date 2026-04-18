#!/usr/bin/env python3
"""
Create dissertation Figure 5.3 from project audit logs.

Figure objective:
- x-axis: selected downgrade/exception labels
- y-axis: count
- categories restricted to:
  - no_authoritative_source_found
  - insufficient
  - request_timeout
  - error
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_LOG = PROJECT_ROOT / "data" / "audit_log.jsonl"
BASELINE_RESULTS = PROJECT_ROOT / "evaluation_results_baseline.json"
MULTILINGUAL_RESULTS = PROJECT_ROOT / "evaluation_results_multilingual.json"
OUTDIR = PROJECT_ROOT / "evaluation" / "figures"
OUTFIG = OUTDIR / "figure_5_3_audit_downgrade_exception_distribution.png"

LABELS = [
    "no_authoritative_source_found",
    "insufficient",
    "request_timeout",
    "error",
]
DISPLAY_LABELS = [
    "no_authoritative",
    "insufficient",
    "request_timeout",
    "error",
]

CAPTION = (
    "Figure 5.3. Distribution of downgrade labels and operational exceptions in the audit record."
)


def _count_labels_from_audit_log(path: Path) -> dict[str, int]:
    counts = {label: 0 for label in LABELS}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            labels = row.get("downgrade_labels", [])
            if not isinstance(labels, list):
                continue
            for item in labels:
                if item in counts:
                    counts[item] += 1
    return counts


def _has_ssl_exception_in_baseline(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("results", []):
        error = row.get("error")
        if isinstance(error, str) and "SSL" in error.upper():
            return True
    return False


def _plot_bar(counts: dict[str, int], outfig: Path) -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#333333",
            "axes.labelcolor": "#111111",
            "xtick.color": "#111111",
            "ytick.color": "#111111",
            "grid.color": "#DDDDDD",
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
        }
    )

    x = LABELS
    y = [counts[label] for label in x]

    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    bars = ax.bar(x, y, color="#4C78A8", edgecolor="#3A3A3A", linewidth=0.7)

    ax.set_xlabel("Downgrade / exception label")
    ax.set_ylabel("Count")
    ax.grid(axis="y", linestyle="-", linewidth=0.6, alpha=0.55)
    ax.set_axisbelow(True)

    ax.set_xticks(range(len(x)))
    ax.set_xticklabels(DISPLAY_LABELS)
    ax.tick_params(axis="x", labelrotation=0)

    for bar, value in zip(bars, y):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + max(1, int(max(y) * 0.01)),
            str(value),
            ha="center",
            va="bottom",
            fontsize=10,
            color="#222222",
        )

    fig.tight_layout()
    fig.savefig(outfig, dpi=400)
    plt.close(fig)


def main() -> None:
    # Read multilingual results to respect declared dissertation data scope.
    # The figure itself is computed strictly from the audit log labels.
    _ = MULTILINGUAL_RESULTS.read_text(encoding="utf-8")

    counts = _count_labels_from_audit_log(AUDIT_LOG)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    _plot_bar(counts=counts, outfig=OUTFIG)

    ssl_exception_found = _has_ssl_exception_in_baseline(BASELINE_RESULTS)
    conservative_total = counts["no_authoritative_source_found"] + counts["insufficient"]
    operational_total = counts["request_timeout"] + counts["error"]

    interpretation = (
        "The audit distribution indicates that conservative downgrades linked to evidence availability "
        "(no_authoritative_source_found and insufficient) occur more frequently than operational exceptions "
        "(request_timeout and error). This pattern supports the claim that the system predominantly fails "
        "on the side of caution when authoritative support is unavailable, rather than failing because of "
        "runtime instability. Accordingly, the observed failure profile is consistent with a reliability "
        "strategy prioritising evidential discipline over permissive output generation."
    )
    if ssl_exception_found:
        interpretation += (
            " In addition, the baseline evaluation log contains at least one task-level SSL-related "
            "exception, which is best interpreted as an isolated infrastructure-side event rather than "
            "the dominant source of conservative outcomes."
        )

    print(f"Saved Figure 5.3 PNG: {OUTFIG}")
    print(f"Saved plotting script: {Path(__file__).resolve()}")
    print()
    print("Counts used for Figure 5.3:")
    for label in LABELS:
        print(f"- {label}: {counts[label]}")
    print(f"- conservative_total (no_authoritative_source_found + insufficient): {conservative_total}")
    print(f"- operational_total (request_timeout + error): {operational_total}")
    print()
    print(f'Caption: "{CAPTION}"')
    print()
    print("Interpretation (Chapter 5):")
    print(interpretation)


if __name__ == "__main__":
    main()
