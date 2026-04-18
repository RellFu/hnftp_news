# Evaluation Package

Technical implementation and evaluation for the news pitch assistant: gold task set, baseline, threshold tuning, and reproducibility.

## Structure

- **gold_tasks/**: Gold task set (aim for 30–50 tasks), multiple themes and publication years. Each task has `id`, `query`, optional `theme`, `expected_angle`.
- **gold_tasks/dev_tasks.json**: Small dev set for threshold tuning (do not use for final metrics).
- **codebook/**: Annotation rules and consistency checks (evidence categories, downgrade).
- **harness/**: Scripts to run evaluation and tune thresholds.

## 1. Run evaluation (gold task set)

```bash
# From project root (news/)
python evaluation/harness/run.py              # With retrieval (default)
python evaluation/harness/run.py --baseline  # No-retrieval baseline only
python evaluation/harness/run.py --both      # Both; compare citation rate and latency
```

Output: `evaluation_results.json` with per-task results, citation support rate, average latency, and **run config** (timestamp, git sha, model) for reproducibility.

## 2. No-retrieval baseline

The baseline proves the gain from retrieval. It runs the same LLM pipeline with **no web search and no RAG**; the model receives only the user criteria (topic/beat). Compare `with_retrieval_citation_rate` vs `no_retrieval_citation_rate` (and latency) when using `--both`.

## 3. Threshold tuning (dev set)

Do not guess `TOP_K` or `RERANKER_THRESHOLD` blindly. Use a dev set of at least 15 tasks and multiple metrics to pick a balance:

```bash
python evaluation/harness/tune_thresholds.py
```

**Method:**
- **Dev set**: `evaluation/gold_tasks/dev_tasks.json` only (no fallback to gold; dev and gold stay independent). Same schema as tasks.json. For rigorous tuning, use 25–30 tasks (see `evaluation/gold_tasks/README.md`).
- For each (top_k, reranker_threshold): **citation_support_rate**, **mean_max_reranker_score** (average over queries of the top span’s reranker score; higher = more confident retrieval), **mean_latency_ms**, **std_latency_ms**.
- **Recommendation rule**: Among configs with citation_support_rate ≥ 90%, pick the one with **highest mean_max_reranker_score** (quality); if tied, lower latency. If none reach 90%, recommend the best citation_rate + quality.

Output: table printed and saved to `evaluation/threshold_tuning_output.txt`; full results and recommended (top_k, threshold) to `evaluation/threshold_tuning_results.json`. Set the chosen values in `backend/app/core/config.py`.

## 4. Reproducibility

To reproduce results under the same conditions:

1. **Same code**: Use the `git_sha` stored in `evaluation_results.json` to checkout that commit.
2. **Same data**: Keep `data/chunks/` and `data/metadata.json` unchanged (or document the corpus version).
3. **Same config**: Use the same `LLM_MODEL`, plus tuned `TOP_K` and `RERANKER_THRESHOLD`; if you change the embedding model, also pin `RAG_EMBEDDING_MODEL` (see `backend/app/core/config.py` and retrieval docs).
4. **Same env**: Set `LLM_API_KEY`, `SERPER_API_KEY` (for with-retrieval), and optionally `LLM_MODEL`. For deterministic LLM output, use a low temperature (e.g. 0) if your API supports it.

Re-run:

```bash
python evaluation/harness/run.py --both
```

and compare the new `evaluation_results.json` with the previous run.

## 5. Embedding model A/B (multilingual embedding evaluation)

To evaluate whether a multilingual embedding model outperforms the default `all-MiniLM-L6-v2`, run the practical A/B flow below and then set the default model based on results.

### 5.1 Run A (current default)

From the **project root** (the directory containing `evaluation/`, `backend/`, and `knowledge_base/`, for example `~/news` or `/Users/a1-6/news`):

```bash
cd /Users/a1-6/news        # replace with your project root path
source .venv/bin/activate   # if using conda: conda activate <env>

# Use current default (unset means all-MiniLM-L6-v2)
unset RAG_EMBEDDING_MODEL
python knowledge_base/scripts/precompute_embeddings.py
python evaluation/harness/run.py --both

# Save results to avoid overwrite by the next run
cp evaluation_results.json evaluation_results_baseline.json
```

### 5.2 Run B (candidate model, e.g. multilingual)

```bash
export RAG_EMBEDDING_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
python knowledge_base/scripts/precompute_embeddings.py
python evaluation/harness/run.py --both

cp evaluation_results.json evaluation_results_multilingual.json
```

(Optional) If you want to retune thresholds for the new model, run this once after B precompute:

```bash
python evaluation/harness/tune_thresholds.py
```

Then update `TOP_K` / `RERANKER_THRESHOLD` in `backend/app/core/config.py` as recommended, and run `run.py --both` above.

### 5.3 Compare both runs and choose default

```bash
python evaluation/harness/compare_embedding_runs.py evaluation_results_baseline.json evaluation_results_multilingual.json --label-a "MiniLM-L6" --label-b "multilingual"
```

The script prints citation_rate, mean_angle_overlap, Recall@12, Mean MRR, latency, and angle_lift for both runs. If B is better on quality with acceptable latency, make B the default:

- Change the default `EMBEDDING_MODEL_NAME` in `backend/app/core/config.py` to model B, **or**
- Pin `RAG_EMBEDDING_MODEL=<model name for B>` in your deployment environment.

Also update the embedding-model note and selection rationale in `docs/RAG_OPTIMIZATION_CHECKLIST.md` under "Current RAG configuration".

## Metrics (harness output)

- **Citation support rate**: Proportion of tasks where retrieval provided evidence and the pipeline produced output (with-retrieval) or produced output (baseline). Finer per-claim support can be added via codebook rules.
- **Factual consistency**: Pass/fail vs retrieved evidence (baseline implementation in harness; can be extended with NLI or human annotation).
- **Coverage**: Policy basis, stakeholders, local relevance (codebook; extend with checklist scoring).
- **Latency**: Per-task and average response time (ms).
