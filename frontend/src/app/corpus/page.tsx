"use client";

import { useState, useEffect } from "react";

export default function CorpusPage() {
  const [data, setData] = useState<{
    documents: Array<{
      source_identifier: string;
      issuing_body: string;
      publication_date: string;
      title: string;
      source_url: string;
    }>;
    total: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${api}/api/corpus`)
      .then((r) => r.json())
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading corpus…</p>;
  if (error) return <p>Error: {error}</p>;
  if (!data) return null;

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem" }}>
      <nav style={{ marginBottom: "1rem" }}>
        <a href="/" style={{ marginRight: "1rem" }}>Pitch</a>
        <a href="/audit" style={{ marginRight: "1rem" }}>Audit Log</a>
      </nav>
      <h1>Corpus Overview</h1>

      <section>
        <h2 style={{ fontSize: "1rem" }}>Documents ({data.total})</h2>
        <ul style={{ listStyle: "none", padding: 0 }}>
          {data.documents.map((d) => (
            <li
              key={d.source_identifier}
              style={{
                padding: "0.75rem",
                borderBottom: "1px solid #e5e7eb",
                display: "flex",
                flexDirection: "column",
                gap: "0.25rem",
              }}
            >
              <strong>{d.title || d.source_identifier}</strong>
              <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>
                {d.issuing_body} · {d.publication_date}
              </span>
              {d.source_url && (
                <a href={d.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: "0.8125rem" }}>
                  {d.source_url}
                </a>
              )}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
