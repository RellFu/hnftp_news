"use client";

import type { EvidenceSpan, PitchDraft } from "@/types/pitch";
import styles from "./PitchCard.module.css";

interface PitchCardProps {
  pitch: PitchDraft;
  onEvidenceClick: (span: EvidenceSpan) => void;
}

function EvidenceAnchor({
  span,
  onClick,
}: {
  span: EvidenceSpan;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.evidenceAnchor}
      onClick={onClick}
      title={`View evidence: ${span.metadata.sourceId}`}
      aria-label={`View evidence from ${span.metadata.issuingBody}`}
    >
      [↗]
    </button>
  );
}

export function PitchCard({ pitch, onEvidenceClick }: PitchCardProps) {
  return (
    <article className={styles.card}>
      <h3 className={styles.angle}>{pitch.proposedAngle}</h3>
      <p className={styles.timeliness}>{pitch.whyItMattersNow}</p>
      <section>
        <h4 className={styles.fieldLabel}>Key questions</h4>
        <ul>
          {pitch.keyQuestions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      </section>
      <section>
        <h4 className={styles.fieldLabel}>Key stakeholders</h4>
        <ul>
          {pitch.keyStakeholders.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </section>
      {pitch.claimFields.length > 0 && (
        <section>
          <h4 className={styles.fieldLabel}>Claim fields</h4>
          {pitch.claimFields.map((cf, i) => (
            <div key={i} className={styles.claimField}>
              <span className={styles.claimFieldName}>{cf.fieldName}:</span>{" "}
              {cf.claim}
              {cf.evidenceSpans.map((span) => (
                <EvidenceAnchor
                  key={span.spanId}
                  span={span}
                  onClick={() => onEvidenceClick(span)}
                />
              ))}
              {cf.isDowngraded && cf.downgradeReason && (
                <span className={styles.downgradeBadge}>
                  Downgraded: {cf.downgradeReason}
                </span>
              )}
            </div>
          ))}
        </section>
      )}
    </article>
  );
}
