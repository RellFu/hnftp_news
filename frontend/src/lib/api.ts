const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchCorpus() {
  const r = await fetch(`${API_BASE}/api/corpus`);
  if (!r.ok) throw new Error("Failed to fetch corpus");
  return r.json();
}

export async function fetchRetrieval(query: string, opts?: { timeframe?: string; issuing_body?: string }) {
  const r = await fetch(`${API_BASE}/api/retrieval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, ...opts }),
  });
  if (!r.ok) throw new Error("Retrieval failed");
  return r.json();
}

export async function fetchGenerate(query: string, opts?: { beat?: string; timeframe?: string; issuing_body?: string }) {
  const r = await fetch(`${API_BASE}/api/generation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, ...opts }),
  });
  if (!r.ok) throw new Error("Generation failed");
  return r.json();
}

export async function fetchValidate(draftText: string) {
  const r = await fetch(`${API_BASE}/api/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ draft_text: draftText }),
  });
  if (!r.ok) throw new Error("Validation failed");
  return r.json();
}

/** Reactive workflow: web search + RAG + LLM -> news value, angle, pitch plan. Pass a topic string (legacy) or structured params. */
export type ReactivePitchParams = {
  topic?: string;
  beat?: string;
  timeframe_start?: string;
  timeframe_end?: string;
  issuing_body_preference?: string[];
  target_audience?: string;
};

export async function fetchReactivePitch(params: string | ReactivePitchParams) {
  const body = typeof params === "string" ? { topic: params } : params;
  const r = await fetch(`${API_BASE}/api/reactive-pitch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("Reactive pitch failed");
  return r.json();
}

/** Active retrieval: run one hot-topic web search (Serper) */
export async function fetchActiveSearch(query?: string) {
  const r = await fetch(`${API_BASE}/api/active-search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query != null ? { query } : {}),
  });
  if (!r.ok) throw new Error("Active search failed");
  return r.json();
}

export async function fetchAuditLog(limit = 100) {
  const r = await fetch(`${API_BASE}/api/audit?limit=${limit}`);
  if (!r.ok) throw new Error("Failed to fetch audit log");
  return r.json();
}
