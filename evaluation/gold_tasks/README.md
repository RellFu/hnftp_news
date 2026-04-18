# Gold Task Set

## Dev set vs gold set (keep independent)

- **Dev set** (`dev_tasks.json`): Used **only for threshold tuning** (top_k, reranker_threshold). Must be **independent** from gold: no overlapping tasks. For rigorous tuning, use **25–30 tasks**. The script loads only from this file (no fallback to gold).
- **Gold set** (`tasks.json`): Used **only for final evaluation** (`run.py --both`). Do not use the same tasks as in dev; keep the two sets disjoint so reported metrics are not overfitted to the tuning set.

## Current status

- **Dev set** (`dev_tasks.json`): **30 tasks** (dev-001 … dev-030), used for threshold tuning.
- **Gold set** (`tasks.json`): **50 tasks** (task-001 … task-050), including 5 with `retrieval_critical: true` for final evaluation.
- **task-045/046**: with_retrieval previously tended to trigger LLM 400 for the original queries ("State Council implementation plan" / "2025 work plan and key tasks"). They were rewritten to shorter queries ("master plan and phased rollout" / "2025 key priorities and deliverables"), and still remain policy tasks, with `retrieval_critical` retained on 046.

## Harness metrics (run.py)

- **Citation support rate**: % of tasks with evidence (web or RAG) and non-empty output.
- **Mean angle_overlap**: Gold `expected_angle` vs model `proposed_angle` (word overlap). **angle_lift** = with_retrieval − no_retrieval.
- **Recall@1 / @5 / @12**: Proxy recall (no gold span labels): for each task, retrieval is run and each top-k span is counted “relevant” if word overlap(span.text, expected_angle + query) ≥ 10%. Recall@k = 1 if any of top-k spans is relevant else 0. Mean over tasks is reported.
- **Mean MRR**: Mean reciprocal rank of the first “relevant” span (same proxy).

## Remaining issues (why evaluation may not fully "prove" retrieval)

1. **Expected angle not used**  
   (Previously: "Too small" — now 30 dev / 50 gold.)

   **Resolved:** The harness now compares `proposed_angle` (model output) to `expected_angle` (gold) via word overlap and reports **mean_angle_overlap** and **angle_lift** (with_retrieval − no_retrieval). Each result row includes `expected_angle` and `proposed_angle` for inspection.

2. **Possible ceiling effect**  
   All queries are in-domain (Hainan FTP). The LLM often produces plausible output even without retrieval. To show retrieval’s value, include some tasks where retrieval is necessary (e.g. very specific policy name, recent doc, or niche angle) so that no_retrieval is more likely to fail or produce generic/wrong content.

## Task schema (same for dev_tasks.json and tasks.json)

Use the same structure in both files so tasks are interchangeable and tooling stays simple:

| Field | Required | Description |
|-------|----------|-------------|
| **id** | Yes | Unique id, e.g. `dev-001` (dev) or `task-001` (gold). |
| **query** | Yes | User topic/beat, used as input to retrieval and pipeline. |
| **theme** | No | e.g. tax_policy, customs, trade — for stratification. |
| **publication_year** | No | e.g. 2023, 2024 — for filtering or analysis. |
| **expected_angle** | No | Gold one-sentence angle; used by eval harness for angle_overlap. Optional in dev. |
| **retrieval_critical** | No | If true, mark as task where retrieval is essential (gold only, optional). |

Example (one task):

```json
{"id": "dev-001", "theme": "tax_policy", "publication_year": "2024", "query": "Hainan Free Trade Port corporate income tax incentives", "expected_angle": "Tax reduction for eligible enterprises"}
```

## What to do

1. **Expand dev_tasks.json to 25–30 tasks**  
   Keep dev and gold disjoint (different ids/queries). Use the same schema as above. Then run `tune_thresholds.py` for rigorous threshold choice.

2. **Expand tasks.json (gold) to 30–50 tasks**  
   Add more tasks across themes and years; keep a few that are "retrieval-critical" (specific or recent).

3. **Use expected_angle in the harness**  
   Compare model `proposed_angle` (or full output) to `expected_angle` (e.g. keyword overlap, embedding similarity, or NLI) and report a "match" or "relevance" rate for both with_retrieval and no_retrieval. Then citation/quality lift is measured, not defined by design.

4. **Optional: mark discriminative tasks**  
   Add a field like `"retrieval_critical": true` for tasks where retrieval is expected to matter; report metrics on this subset separately.
