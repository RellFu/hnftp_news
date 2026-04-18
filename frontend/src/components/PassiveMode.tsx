"use client";

import { useState, useRef, useEffect } from "react";
import { fetchReactivePitch } from "@/lib/api";
import type { RagExcerpt, ReactivePitchResult } from "./ReactiveMode";
import formStyles from "./ProactiveMode.module.css";
import resultStyles from "./ReactiveMode.module.css";

function formatTimeframeDisplay(start: string, end: string): string {
  if (start && end) return `${start} to ${end}`;
  if (start) return start;
  if (end) return end;
  return "";
}

const BEAT_SUGGESTIONS = [
  "Tax policy",
  "Trade",
  "Tourism",
  "Customs",
  "Travel",
  "Culture",
  "Ecology",
  "Sports",
  "Livelihood",
];

// Keep this aligned with issuing_body values present in the knowledge base:
// left = display label in dropdown, right = canonical value sent to backend.
const ISSUING_BODY_SUGGESTIONS = [
  "Hainan FTP Authority",
  "Hainan Provincial Government",
  "Hainan Development and Reform Commission",
  "Hainan Dept. of Business Environment",
  "Hainan Dept. of Tourism, Culture & Sports",
  "Hainan Dept. of Ecology and Environment",
  "Hainan Dept. of Human Resources and Social Security",
  "Hainan Dept. of Civil Affairs",
  "Hainan SASAC",
  "Hainan Health Commission",
];

const ISSUING_BODY_CANONICAL: Record<string, string> = {
  "Hainan FTP Authority": "Hainan Free Trade Port Authority",
  "Hainan Provincial Government": "Hainan Provincial Government",
  "Hainan Development and Reform Commission": "Hainan Development and Reform Commission",
  "Hainan Dept. of Business Environment": "Hainan Department of Business Environment",
  "Hainan Dept. of Tourism, Culture & Sports": "Hainan Department of Tourism, Culture, Radio, Television and Sports",
  "Hainan Dept. of Ecology and Environment": "Hainan Department of Ecology and Environment",
  "Hainan Dept. of Human Resources and Social Security": "Hainan Department of Human Resources and Social Security",
  "Hainan Dept. of Civil Affairs": "Hainan Department of Civil Affairs",
  "Hainan SASAC": "Hainan SASAC",
  "Hainan Health Commission": "Hainan Health Commission",
};

function toCanonicalIssuingBody(label: string): string {
  return ISSUING_BODY_CANONICAL[label] ?? label;
}

const TARGET_AUDIENCE_SUGGESTIONS = [
  "Investors",
  "Policy analysts",
  "International businesses",
  "Journalists",
  "Academics",
  "General public",
];

export function PassiveMode() {
  const [beat, setBeat] = useState("");
  const [timeframeStart, setTimeframeStart] = useState("");
  const [timeframeEnd, setTimeframeEnd] = useState("");
  const [timeframePickerOpen, setTimeframePickerOpen] = useState(false);
  const [beatDropdownOpen, setBeatDropdownOpen] = useState(false);
  const [issuingBodyDropdownOpen, setIssuingBodyDropdownOpen] = useState(false);
  const [targetAudienceDropdownOpen, setTargetAudienceDropdownOpen] = useState(false);
  const timeframeRef = useRef<HTMLDivElement>(null);
  const beatRef = useRef<HTMLDivElement>(null);
  const issuingBodyRef = useRef<HTMLDivElement>(null);
  const targetAudienceRef = useRef<HTMLDivElement>(null);
  const [issuingBody, setIssuingBody] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [result, setResult] = useState<ReactivePitchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const timeframeValue = formatTimeframeDisplay(timeframeStart, timeframeEnd);

  useEffect(() => {
    if (!isLoading) return;
    setElapsedSec(0);
    const t = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [isLoading]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (timeframeRef.current && !timeframeRef.current.contains(target)) setTimeframePickerOpen(false);
      if (beatRef.current && !beatRef.current.contains(target)) setBeatDropdownOpen(false);
      if (issuingBodyRef.current && !issuingBodyRef.current.contains(target)) setIssuingBodyDropdownOpen(false);
      if (targetAudienceRef.current && !targetAudienceRef.current.contains(target)) setTargetAudienceDropdownOpen(false);
    }
    if (timeframePickerOpen || beatDropdownOpen || issuingBodyDropdownOpen || targetAudienceDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [timeframePickerOpen, beatDropdownOpen, issuingBodyDropdownOpen, targetAudienceDropdownOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setElapsedSec(0);
    setResult(null);
    setError(null);
    try {
      const hasAny = beat.trim() || timeframeStart.trim() || timeframeEnd.trim() || issuingBody.trim() || targetAudience.trim();
      const issuingPref = issuingBody.trim()
        ? [toCanonicalIssuingBody(issuingBody.trim())]
        : undefined;
      const res = await fetchReactivePitch(
        hasAny
          ? {
              beat: beat.trim() || undefined,
              timeframe_start: timeframeStart.trim() || undefined,
              timeframe_end: timeframeEnd.trim() || undefined,
              issuing_body_preference: issuingPref,
              target_audience: targetAudience.trim() || undefined,
            }
          : { topic: "Hainan Free Trade Port policy" }
      );
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
    <div className={formStyles.container}>
      <section>
        <p style={{ margin: "0 0 1rem", fontSize: "0.875rem", color: "#6b7280" }}>
          Use topic, timeframe, preferred sources and audience to search recent events and policy context from the web and knowledge base.
        </p>
        <form className={formStyles.form} onSubmit={handleSubmit}>
          <div className={formStyles.formRowTwoRows}>
            <label ref={beatRef} style={{ position: "relative" }}>
              <span>Topic</span>
              <input
                type="text"
                placeholder="Click or type to select your topic"
                value={beat}
                onChange={(e) => setBeat(e.target.value)}
                onFocus={() => setBeatDropdownOpen(true)}
                onMouseDown={() => setBeatDropdownOpen(true)}
              />
              {beatDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    right: 0,
                    marginTop: 2,
                    padding: "0.25rem 0",
                    background: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 6,
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    zIndex: 10,
                    maxHeight: 220,
                    overflowY: "auto",
                  }}
                >
                  {BEAT_SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => { setBeat(s); setBeatDropdownOpen(false); }}
                      style={{
                        display: "block",
                        width: "100%",
                        padding: "0.4rem 0.75rem",
                        textAlign: "left",
                        fontSize: "0.875rem",
                        border: "none",
                        background: beat === s ? "#eff6ff" : "transparent",
                        color: beat === s ? "#1d4ed8" : "#374151",
                        cursor: "pointer",
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </label>
            <label ref={timeframeRef} style={{ position: "relative" }}>
              <span>Timeframe</span>
              <div
                role="button"
                tabIndex={0}
                onClick={() => setTimeframePickerOpen((o) => !o)}
                onKeyDown={(e) => e.key === "Enter" && setTimeframePickerOpen((o) => !o)}
                className={formStyles.timeframeTrigger}
                style={{ color: timeframeValue ? "#111" : "#9ca3af" }}
              >
                {timeframeValue || "Click to select date range"}
              </div>
              {timeframePickerOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    marginTop: 4,
                    padding: "0.75rem",
                    background: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 8,
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    zIndex: 10,
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.5rem",
                    minWidth: 260,
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                    <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#6b7280" }}>Start date</span>
                    <input
                      type="date" lang="en"
                      value={timeframeStart}
                      onChange={(e) => setTimeframeStart(e.target.value)}
                      style={{ padding: "0.4rem", border: "1px solid #d1d5db", borderRadius: 6, fontSize: "0.875rem" }}
                    />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                    <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#6b7280" }}>End date</span>
                    <input
                      type="date" lang="en"
                      value={timeframeEnd}
                      onChange={(e) => setTimeframeEnd(e.target.value)}
                      style={{ padding: "0.4rem", border: "1px solid #d1d5db", borderRadius: 6, fontSize: "0.875rem" }}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => { setTimeframeStart(""); setTimeframeEnd(""); setTimeframePickerOpen(false); }}
                    style={{ fontSize: "0.8125rem", color: "#6b7280", background: "none", border: "none", cursor: "pointer", alignSelf: "flex-start" }}
                  >
                    Clear
                  </button>
                </div>
              )}
            </label>
            <label ref={issuingBodyRef} style={{ position: "relative" }}>
              <span>Issuing body preference</span>
              <input
                type="text"
                placeholder="Click or type to select preferred source"
                value={issuingBody}
                onChange={(e) => setIssuingBody(e.target.value)}
                onFocus={() => setIssuingBodyDropdownOpen(true)}
                onMouseDown={() => setIssuingBodyDropdownOpen(true)}
              />
              {issuingBodyDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    right: 0,
                    marginTop: 2,
                    padding: "0.25rem 0",
                    background: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 6,
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    zIndex: 10,
                    maxHeight: 220,
                    overflowY: "auto",
                  }}
                >
                  {ISSUING_BODY_SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => { setIssuingBody(s); setIssuingBodyDropdownOpen(false); }}
                      style={{
                        display: "block",
                        width: "100%",
                        padding: "0.4rem 0.75rem",
                        textAlign: "left",
                        fontSize: "0.875rem",
                        border: "none",
                        background: issuingBody === s ? "#eff6ff" : "transparent",
                        color: issuingBody === s ? "#1d4ed8" : "#374151",
                        cursor: "pointer",
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </label>
            <label ref={targetAudienceRef} style={{ position: "relative" }}>
              <span>Target audience</span>
              <input
                type="text"
                placeholder="Click or type to select your target audience"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
                onFocus={() => setTargetAudienceDropdownOpen(true)}
                onMouseDown={() => setTargetAudienceDropdownOpen(true)}
              />
              {targetAudienceDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    right: 0,
                    marginTop: 2,
                    padding: "0.25rem 0",
                    background: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 6,
                    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    zIndex: 10,
                    maxHeight: 220,
                    overflowY: "auto",
                  }}
                >
                  {TARGET_AUDIENCE_SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => { setTargetAudience(s); setTargetAudienceDropdownOpen(false); }}
                      style={{
                        display: "block",
                        width: "100%",
                        padding: "0.4rem 0.75rem",
                        textAlign: "left",
                        fontSize: "0.875rem",
                        border: "none",
                        background: targetAudience === s ? "#eff6ff" : "transparent",
                        color: targetAudience === s ? "#1d4ed8" : "#374151",
                        cursor: "pointer",
                      }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </label>
          </div>
          <button type="submit" className={formStyles.submitBtn} disabled={isLoading}>
            {isLoading ? "Searching & generating…" : "Generate pitch options"}
          </button>
        </form>
      </section>

      {isLoading && (
        <div className={formStyles.loadingWrap}>
          <div className={formStyles.loadingStatus} role="status" aria-live="polite">
            <span className={formStyles.loadingSpinner} aria-hidden="true" />
            <span className={formStyles.loadingMessage}>
              Searching the web and knowledge base, then generating pitch options. This usually takes 15–60 seconds.
            </span>
            <span className={formStyles.loadingElapsed}>
              {Math.floor(elapsedSec / 60)}:{String(elapsedSec % 60).padStart(2, "0")}
            </span>
          </div>
        </div>
      )}

      {error && (
        <div style={{ padding: "1rem", background: "#fef2f2", color: "#b91c1c", borderRadius: 8, marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {result && (
        <section>
          <h2 className={resultStyles.resultTitle}>Pitch options</h2>
          {result.timeout && (
            <div style={{ marginBottom: "0.75rem", padding: "0.5rem 0.75rem", background: "#fef2f2", color: "#b91c1c", borderRadius: 8, fontSize: "0.875rem", fontWeight: 500 }}>
              Request timed out (60s). Partial result below; verify before use.
            </div>
          )}
          {result.error && (
            <div style={{ color: "#b45309", padding: "0.5rem 0", fontSize: "0.875rem" }}>{result.error}</div>
          )}
          {result.evidence_status === "insufficient" && result.downgrade_message && !result.news_value_assessment && !result.proposed_angle && !result.pitch_plan ? (
            <p style={{ margin: 0, padding: "0.75rem 1rem", background: "#fef3c7", color: "#92400e", borderRadius: 8, fontSize: "0.9375rem", lineHeight: 1.5 }}>
              {result.downgrade_message}
            </p>
          ) : (
            <div className={resultStyles.resultBox}>
              <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>News value assessment</h3>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{result.news_value_assessment || "—"}</p>
              <h3 style={{ margin: "1.25rem 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>Proposed angle</h3>
              <p style={{ margin: 0 }}>{result.proposed_angle || "—"}</p>
              <h3 style={{ margin: "1.25rem 0 0.5rem", fontSize: "0.9375rem", fontWeight: 600 }}>Pitch plan</h3>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "0.9375rem" }}>
                {result.pitch_plan || "—"}
              </pre>
            </div>
          )}
          <div style={{ marginTop: "0.75rem", fontSize: "0.8125rem", color: "#6b7280" }}>
            {result.rag_used ? "RAG knowledge base used" : "No knowledge base used"} · Web sources: {result.web_sources?.length ?? 0}
            {result.evidence_status && (
              <span style={{ display: "inline-block", marginLeft: "0.5rem", padding: "0.15rem 0.4rem", background: "#f3f4f6", borderRadius: 4 }}>
                Evidence: {result.evidence_status}
              </span>
            )}
            {result.issuing_body_preference && result.issuing_body_preference.length > 0 && (
              <p style={{ margin: "0.5rem 0 0", padding: "0.45rem 0.6rem", background: "#f3f4f6", color: "#374151", borderRadius: 6 }}>
                Preferred issuing body: {result.issuing_body_preference.join(", ")}.
                {typeof result.issuing_body_preference_matched_spans === "number" && result.issuing_body_preference_matched_spans > 0
                  ? ` ${result.issuing_body_preference_matched_spans} RAG excerpts match this preference; other authoritative sources are also shown when relevant.`
                  : result.issuing_body_preference_fallback
                  ? " No knowledge base excerpts from the preferred issuing body were found for this query; showing other authoritative sources instead."
                  : ""}
              </p>
            )}
            {result.downgrade_message && !(result.evidence_status === "insufficient" && !result.news_value_assessment && !result.proposed_angle && !result.pitch_plan) && (
              <p style={{ margin: "0.5rem 0 0", padding: "0.5rem", background: "#fef3c7", color: "#92400e", borderRadius: 6 }}>
                {result.downgrade_message}
              </p>
            )}
            {result.rag_error && (
              <span style={{ display: "block", marginTop: "0.25rem", color: "#b45309" }}>
                {result.rag_error}
              </span>
            )}
            {result.web_search_error && (
              <span style={{ display: "block", marginTop: "0.25rem", color: "#dc2626" }}>
                {result.web_search_error}
              </span>
            )}
          </div>

          <section className={resultStyles.traceSection}>
            <h3 className={resultStyles.traceTitle}>Evidence details</h3>
            <div className={resultStyles.traceBlock}>
              <h4 className={resultStyles.traceSubtitle}>Web search</h4>
              {result.web_sources && result.web_sources.length > 0 ? (
                <ul className={resultStyles.traceList}>
                  {result.web_sources.map((s, i) => (
                    <li key={i} className={resultStyles.traceItem}>
                      {s.link ? (
                        <a href={s.link} target="_blank" rel="noopener noreferrer" className={resultStyles.traceLink}>
                          {s.title || "No title"}
                        </a>
                      ) : (
                        <span>{s.title || "No title"}</span>
                      )}
                      {s.snippet && <p className={resultStyles.traceSnippet}>{s.snippet}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={resultStyles.traceEmpty}>No web results available</p>
              )}
            </div>
            {result.cited_sources && result.cited_sources.length > 0 && (
              <div className={resultStyles.traceBlock}>
                <h4 className={resultStyles.traceSubtitle}>Cited in pitch</h4>
                <ul className={resultStyles.traceList}>
                  {result.cited_sources.map((s, i) => (
                    <li key={i} className={resultStyles.traceItem}>
                      <div className={resultStyles.traceMeta}>
                        {s.issuing_body}
                        {s.publication_date && ` · ${s.publication_date}`}
                        {s.span_id && (
                          <button
                            type="button"
                            className={resultStyles.spanIdLink}
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
                      {s.snippet && <p className={resultStyles.traceSnippet}>{s.snippet}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className={resultStyles.traceBlock}>
              <h4 className={resultStyles.traceSubtitle}>Knowledge base RAG</h4>
              {result.rag_excerpts && result.rag_excerpts.length > 0 ? (
                <ul className={resultStyles.traceList}>
                  {result.rag_excerpts.map((e: RagExcerpt, i: number) => {
                    const isCited = e.span_id && result.cited_span_ids?.includes(e.span_id);
                    return (
                      <li
                        key={e.span_id || i}
                        id={e.span_id ? `rag-${e.span_id}` : undefined}
                        className={resultStyles.traceItem + (isCited ? ` ${resultStyles.traceItemCited}` : "")}
                      >
                        <div className={resultStyles.traceMeta}>
                          {isCited && <span className={resultStyles.citedBadge}>Cited</span>}
                          {e.issuing_body}
                          {e.publication_date && ` · ${e.publication_date}`}
                          {e.source_identifier && ` · ${e.source_identifier}`}
                        </div>
                        <p className={resultStyles.traceText}>{e.text}</p>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={resultStyles.traceEmpty}>No knowledge-base evidence available</p>
              )}
            </div>
          </section>
        </section>
      )}
    </div>
  );
}
