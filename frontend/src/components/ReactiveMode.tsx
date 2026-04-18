"use client";

import { useState } from "react";
import { fetchReactivePitch } from "@/lib/api";
import styles from "./ReactiveMode.module.css";

export type RagExcerpt = {
  span_id?: string;
  issuing_body: string;
  publication_date: string;
  source_identifier: string;
  text: string;
};

export type CitedSource = {
  issuing_body: string;
  publication_date: string;
  snippet: string;
  span_id?: string | null;
};

export type ReactivePitchResult = {
  news_value_assessment: string;
  proposed_angle: string;
  pitch_plan: string;
  cited_sources?: CitedSource[];
  cited_span_ids?: string[];
  web_sources: Array<{ title?: string; link?: string; snippet?: string }>;
  rag_excerpts?: RagExcerpt[];
  rag_used: boolean;
  rag_error?: string | null;
  evidence_status?: string | null;
  downgrade_message?: string | null;
  error: string | null;
  web_search_error?: string | null;
  request_id?: string;
  timeout?: boolean | null;
  issuing_body_preference?: string[];
  issuing_body_preference_matched_spans?: number;
  issuing_body_preference_fallback?: boolean | null;
};

export function ReactiveMode() {
  const [topic, setTopic] = useState("");
  const [result, setResult] = useState<ReactivePitchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetchReactivePitch(topic);
      setResult(res as ReactivePitchResult);
      if (res.error) setError(res.error);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed; check backend and network";
      setError(msg);
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <section>
        <h2 className={styles.sectionTitle}>Web + RAG pitch</h2>
        <p style={{ margin: "0 0 1rem", fontSize: "0.875rem", color: "#6b7280" }}>
          Enter a topic or seed; the system will run web search, combine with RAG, then use the LLM for news value assessment, angle, and pitch plan.
        </p>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            className={styles.input}
            placeholder="Enter topic or seed; click Generate to search and create a pitch"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <div style={{ marginTop: "1rem" }}>
            <button
              type="submit"
              className={styles.submitBtn}
              disabled={isLoading || !topic.trim()}
            >
              {isLoading ? "Searching & generating…" : "Search and generate pitch"}
            </button>
          </div>
        </form>
      </section>

      {error && (
        <section>
          <div style={{ color: "#dc2626", padding: "0.75rem", background: "#fef2f2", borderRadius: 8 }}>
            {error}
          </div>
        </section>
      )}

      {result && (
        <section>
          <h2 className={styles.resultTitle}>Pitch</h2>
          {result.error && (
            <div style={{ color: "#b45309", padding: "0.5rem 0", fontSize: "0.875rem" }}>
              {result.error}
            </div>
          )}
          <div className={styles.resultBox}>
            <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>News value assessment</h3>
            <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{result.news_value_assessment || "—"}</p>
            <h3 style={{ margin: "1.25rem 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>Proposed angle</h3>
            <p style={{ margin: 0 }}>{result.proposed_angle || "—"}</p>
            <h3 style={{ margin: "1.25rem 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>Pitch plan</h3>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "0.9375rem" }}>
              {result.pitch_plan || "—"}
            </pre>
          </div>
          <div style={{ marginTop: "0.75rem", fontSize: "0.8125rem", color: "#6b7280" }}>
            {result.rag_used ? "RAG knowledge base used" : "No knowledge base used"} · Web sources: {result.web_sources?.length ?? 0}
            {result.web_search_error && (
              <span style={{ display: "block", marginTop: "0.25rem", color: "#dc2626" }}>
                {result.web_search_error}
              </span>
            )}
          </div>

          <section className={styles.traceSection}>
            <h3 className={styles.traceTitle}>Evidence details</h3>

            <div className={styles.traceBlock}>
              <h4 className={styles.traceSubtitle}>Web search</h4>
              {result.web_sources && result.web_sources.length > 0 ? (
                <ul className={styles.traceList}>
                  {result.web_sources.map((s, i) => (
                    <li key={i} className={styles.traceItem}>
                      {s.link ? (
                        <a href={s.link} target="_blank" rel="noopener noreferrer" className={styles.traceLink}>
                          {s.title || "No title"}
                        </a>
                      ) : (
                        <span>{s.title || "No title"}</span>
                      )}
                      {s.snippet && <p className={styles.traceSnippet}>{s.snippet}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.traceEmpty}>No web results available</p>
              )}
            </div>

            {result.cited_sources && result.cited_sources.length > 0 && (
              <div className={styles.traceBlock}>
                <h4 className={styles.traceSubtitle}>Cited in pitch</h4>
                <ul className={styles.traceList}>
                  {result.cited_sources.map((s, i) => (
                    <li key={i} className={styles.traceItem}>
                      <div className={styles.traceMeta}>
                        {s.issuing_body}
                        {s.publication_date && ` · ${s.publication_date}`}
                        {s.span_id && (
                          <button
                            type="button"
                            className={styles.spanIdLink}
                            onClick={() => {
                              const el = document.getElementById(`rag-${s.span_id}`);
                              el?.scrollIntoView({ behavior: "smooth", block: "center" });
                            }}
                            title="Scroll to this excerpt in Knowledge base RAG"
                          >
                            {s.span_id}
                          </button>
                        )}
                      </div>
                      {s.snippet && <p className={styles.traceSnippet}>{s.snippet}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className={styles.traceBlock}>
              <h4 className={styles.traceSubtitle}>Knowledge base RAG</h4>
              {result.rag_excerpts && result.rag_excerpts.length > 0 ? (
                <ul className={styles.traceList}>
                  {result.rag_excerpts.map((e, i) => {
                    const isCited = e.span_id && result.cited_span_ids?.includes(e.span_id);
                    return (
                      <li
                        key={e.span_id || i}
                        id={e.span_id ? `rag-${e.span_id}` : undefined}
                        className={styles.traceItem + (isCited ? ` ${styles.traceItemCited}` : "")}
                      >
                        <div className={styles.traceMeta}>
                          {isCited && <span className={styles.citedBadge}>Cited</span>}
                          {e.issuing_body}
                          {e.publication_date && ` · ${e.publication_date}`}
                          {e.source_identifier && ` · ${e.source_identifier}`}
                        </div>
                        <p className={styles.traceText}>{e.text}</p>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={styles.traceEmpty}>No knowledge-base evidence available</p>
              )}
            </div>
          </section>
        </section>
      )}
    </div>
  );
}
