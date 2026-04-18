"use client";

import { useState, useEffect } from "react";
import { fetchActiveSearch } from "@/lib/api";
import styles from "./ActiveMode.module.css";

const THEME_TAGS: Record<string, { label: string; className: string }> = {
  policy:   { label: "Policy",   className: "tagPolicy" },
  tourism:  { label: "Tourism",  className: "tagTourism" },
  culture:  { label: "Culture",  className: "tagCulture" },
  ecology:  { label: "Ecology",  className: "tagEcology" },
  sports:   { label: "Sports",   className: "tagSports" },
  livelihood: { label: "Livelihood", className: "tagLivelihood" },
  other:    { label: "Other",    className: "tagOther" },
};

type PitchSuggestion = {
  theme?: string | null;
  title?: string | null;
  news_value_assessment: string;
  proposed_angle: string;
  pitch_plan: string;
};

type RagExcerpt = {
  span_id?: string;
  issuing_body?: string;
  publication_date?: string;
  source_identifier?: string;
  text?: string;
};

type ActiveSearchResult = {
  query_used: string;
  results: Array<{ title?: string; link?: string; snippet?: string }>;
  pitches: PitchSuggestion[];
  rag_used?: boolean;
  rag_excerpts?: RagExcerpt[];
  rag_error?: string | null;
  evidence_status?: string | null;
  downgrade_message?: string | null;
  error: string | null;
  timeout?: boolean | null;
};

export function ActiveMode() {
  const [result, setResult] = useState<ActiveSearchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading) return;
    setElapsedSec(0);
    const t = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [isLoading]);

  const handleRun = async () => {
    setIsLoading(true);
    setElapsedSec(0);
    setResult(null);
    setError(null);
    try {
      const res = await fetchActiveSearch();
      setResult(res as ActiveSearchResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <section>
        <p className={styles.desc}>
          Run a hot-topic search now to get pitch suggestions from recent trends on the web.
        </p>
        <div style={{ marginTop: "1rem" }}>
          <button
            type="button"
            className={styles.submitBtn}
            onClick={handleRun}
            disabled={isLoading}
          >
            {isLoading ? "Searching & generating…" : "Run hot-topic search now"}
          </button>
        </div>
        {isLoading && (
          <div className={styles.loadingWrap}>
            <div className={styles.loadingStatus} role="status" aria-live="polite">
              <span className={styles.loadingSpinner} aria-hidden="true" />
              <span className={styles.loadingMessage}>
                Searching the web and generating pitch suggestions. This usually takes 15–60 seconds.
              </span>
              <span className={styles.loadingElapsed}>
                {Math.floor(elapsedSec / 60)}:{String(elapsedSec % 60).padStart(2, "0")}
              </span>
            </div>
          </div>
        )}
      </section>

      {error && (
        <div className={styles.errorBox}>{error}</div>
      )}

      {result && (
        <section className={styles.resultSection}>
          <h3 className={styles.resultTitle}>Pitch suggestions</h3>
          {result.timeout && (
            <div className={styles.downgradeMessage} style={{ marginBottom: "0.75rem", background: "#fef2f2", color: "#b91c1c" }}>
              Request timed out (60s). Partial result below; verify before use.
            </div>
          )}
          {result.error && <div className={styles.warnText}>{result.error}</div>}

          {result.pitches && result.pitches.length > 0 ? (
            <div className={styles.pitchList}>
              {result.pitches.map((p, i) => {
                const cardTitle = (p.title || "").trim() || (p.proposed_angle || "").trim() || `Pitch ${i + 1}`;
                const themeKey = (p.theme || "other").toLowerCase();
                const tag = THEME_TAGS[themeKey] ?? THEME_TAGS.other;
                return (
                <div key={i} className={styles.pitchCard}>
                  <div className={styles.pitchCardHeader}>
                    <h4 className={styles.pitchCardTitle}>{cardTitle}</h4>
                    <span className={`${styles.themeTag} ${(styles as Record<string, string>)[tag.className] || styles.tagOther}`}>{tag.label}</span>
                  </div>
                  <div className={styles.pitchCardBody}>
                    <p className={styles.pitchLabel}>News value assessment</p>
                    <p className={styles.pitchText}>{p.news_value_assessment || "—"}</p>
                    <p className={styles.pitchLabel}>Proposed angle</p>
                    <p className={styles.pitchText}>{p.proposed_angle || "—"}</p>
                    <p className={styles.pitchLabel}>Pitch plan</p>
                    <pre className={styles.pitchPlan}>{p.pitch_plan || "—"}</pre>
                  </div>
                </div>
              );
              })}
            </div>
          ) : (
            <p className={styles.empty}>
              {result.results?.length
                ? "No pitch suggestions (check LLM_API_KEY or try again)"
                : "No web results (check SERPER_API_KEY)"}
            </p>
          )}

          {result.results && result.results.length > 0 && (
            <details className={styles.webSourcesDetail}>
              <summary className={styles.webSourcesSummary}>Web search sources ({result.results.length})</summary>
              <ul className={styles.list}>
                {result.results.map((r, i) => (
                  <li key={i} className={styles.item}>
                    {r.link ? (
                      <a href={r.link} target="_blank" rel="noopener noreferrer" className={styles.link}>
                        {r.title || "No title"}
                      </a>
                    ) : (
                      <span>{r.title || "No title"}</span>
                    )}
                    {r.snippet && <p className={styles.snippet}>{r.snippet}</p>}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className={styles.ragStatus}>
            {result.rag_used ? "RAG knowledge base used." : "No knowledge base used."}
            {result.evidence_status && (
              <span className={styles.evidenceStatus}> · Evidence: {result.evidence_status}</span>
            )}
            {result.rag_error && (
              <span className={styles.ragError}> {result.rag_error}</span>
            )}
          </p>
          {result.downgrade_message && (
            <p className={styles.downgradeMessage}>{result.downgrade_message}</p>
          )}
          {result.rag_excerpts && result.rag_excerpts.length > 0 && (
            <details className={styles.webSourcesDetail}>
              <summary className={styles.webSourcesSummary}>Knowledge base RAG ({result.rag_excerpts.length})</summary>
              <ul className={styles.list}>
                {result.rag_excerpts.map((e, i) => (
                  <li key={e.span_id ?? i} className={styles.item} id={e.span_id ? `rag-${e.span_id}` : undefined}>
                    <span className={styles.ragMeta}>
                      {e.issuing_body ?? ""}
                      {e.publication_date && ` · ${e.publication_date}`}
                      {e.source_identifier && ` · ${e.source_identifier}`}
                    </span>
                    <p className={styles.snippet}>{e.text ?? ""}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
