"use client";

import { useState } from "react";
import type { EvidenceSpan, PitchDraft } from "@/types/pitch";
import { PitchCard } from "./PitchCard";
import { EvidencePanel } from "./EvidencePanel";
import { fetchGenerate } from "@/lib/api";
import styles from "./ProactiveMode.module.css";

function mapApiToPitch(api: { pitch: Record<string, unknown>; evidence_spans: Array<Record<string, unknown>> }): PitchDraft {
  const p = api.pitch;
  const spanMap = Object.fromEntries(
    (api.evidence_spans || []).map((s) => [
      s.span_id,
      {
        spanId: s.span_id,
        text: s.text,
        metadata: {
          issuingBody: s.issuing_body,
          publicationDate: s.publication_date,
          documentType: "document",
          sourceId: s.source_identifier,
        },
      },
    ])
  );
  const claimFields = ((p.claim_fields as Array<Record<string, unknown>>) || []).map((cf) => ({
    fieldName: cf.field_name as string,
    claim: cf.claim as string,
    evidenceSpans: ((cf.evidence_span_ids as string[]) || []).map((id) => spanMap[id]).filter(Boolean),
    isDowngraded: cf.is_downgraded as boolean,
    downgradeReason: cf.downgrade_reason as string | undefined,
  }));
  return {
    proposedAngle: (p.proposed_angle as string) || "",
    whyItMattersNow: (p.why_it_matters_now as string) || "",
    keyQuestions: (p.key_questions as string[]) || [],
    keyStakeholders: (p.key_stakeholders as string[]) || [],
    claimFields,
  };
}

export function ProactiveMode() {
  const [beat, setBeat] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [issuingBody, setIssuingBody] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [pitches, setPitches] = useState<PitchDraft[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceSpan | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setPitches([]);
    setError(null);
    try {
      const query = beat || "Hainan Free Trade Port policy";
      const res = await fetchGenerate(query, { beat, timeframe, issuing_body: issuingBody });
      setPitches([mapApiToPitch(res)]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      const isNetworkErr = msg.includes("fetch") || msg.includes("Failed") || msg.includes("Network");
      setError(
        isNetworkErr
          ? "Cannot reach backend. Start it with: cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
          : `API error: ${msg}`
      );
      setPitches([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEvidenceClick = (span: EvidenceSpan) => {
    setSelectedEvidence(span);
    setPanelOpen(true);
  };

  const handleClosePanel = () => {
    setPanelOpen(false);
    setSelectedEvidence(null);
  };

  return (
    <div className={styles.container}>
      <section>
        <h2 className={styles.sectionTitle}>RAG pitch</h2>
        <p style={{ margin: "0 0 1rem", fontSize: "0.875rem", color: "#6b7280" }}>
          Specify beat, constraints (timeframe, issuing body), and target audience.
        </p>
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.formRow}>
            <label>
              <span>Topic</span>
              <input
                type="text"
                placeholder="Type your coverage topic"
                value={beat}
                onChange={(e) => setBeat(e.target.value)}
              />
            </label>
            <label>
              <span>Timeframe</span>
              <input
                type="text"
                placeholder="Type date range or period"
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
              />
            </label>
            <label>
              <span>Issuing body preference</span>
              <input
                type="text"
                placeholder="Type preferred source (optional)"
                value={issuingBody}
                onChange={(e) => setIssuingBody(e.target.value)}
              />
            </label>
            <label>
              <span>Target audience</span>
              <input
                type="text"
                placeholder="Type target audience (optional)"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
              />
            </label>
          </div>
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={isLoading}
          >
            {isLoading ? "Generating…" : "Generate pitch options"}
          </button>
        </form>
      </section>

      {error && (
        <div style={{ padding: "1rem", background: "#fef2f2", color: "#b91c1c", borderRadius: 8, marginBottom: "1rem" }}>
          {error}
        </div>
      )}
      <section>
        <h2 className={styles.pitchStreamTitle}>
          Pitch options {pitches.length > 0 && `(${pitches.length})`}
        </h2>
        <div className={styles.pitchStream}>
          {pitches.map((pitch, i) => (
            <PitchCard
              key={i}
              pitch={pitch}
              onEvidenceClick={handleEvidenceClick}
            />
          ))}
        </div>
      </section>

      <EvidencePanel
        isOpen={panelOpen}
        onClose={handleClosePanel}
        evidence={selectedEvidence}
      />
    </div>
  );
}
