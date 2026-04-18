"use client";

import { useState, useEffect } from "react";

export default function AuditPage() {
  const [data, setData] = useState<{ entries: Array<Record<string, unknown>>; total: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${api}/api/audit?limit=50`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading audit log…</p>;
  if (error) return <p>Error: {error}</p>;
  if (!data) return null;

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <nav style={{ marginBottom: "1rem" }}>
        <a href="/" style={{ marginRight: "1rem" }}>Pitch</a>
        <a href="/corpus" style={{ marginRight: "1rem" }}>Corpus</a>
      </nav>
      <h1>Audit Log</h1>
      <p style={{ color: "#6b7280", marginBottom: "1.5rem" }}>
        Per-request trail: retrieval IDs, filters, latency, downgrade labels
      </p>

      {data.entries.length === 0 ? (
        <p>No audit entries yet. Perform retrieval or generation to see logs.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {data.entries.map((e, i) => (
            <li
              key={(e.request_id as string) || i}
              style={{
                padding: "1rem",
                marginBottom: "0.5rem",
                background: "#f9fafb",
                borderRadius: 8,
                fontSize: "0.875rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                <strong>{e.endpoint}</strong>
                <span>{(e.latency_ms as number)?.toFixed(0)} ms</span>
              </div>
              <div style={{ color: "#6b7280" }}>
                {e.evidence_sufficient !== undefined && (
                  <span>Evidence sufficient: {String(e.evidence_sufficient)}</span>
                )}
                {Array.isArray(e.downgrade_labels) && e.downgrade_labels.length > 0 && (
                  <span> · Downgrade: {e.downgrade_labels.join(", ")}</span>
                )}
              </div>
              {Array.isArray(e.retrieval_span_ids) && e.retrieval_span_ids.length > 0 && (
                <div style={{ marginTop: "0.25rem", fontFamily: "monospace", fontSize: "0.75rem" }}>
                  Spans: {e.retrieval_span_ids.slice(0, 5).join(", ")}
                  {e.retrieval_span_ids.length > 5 && "…"}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
