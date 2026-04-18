"use client";

import type { EvidenceSpan } from "@/types/pitch";
import styles from "./EvidencePanel.module.css";

interface EvidencePanelProps {
  isOpen: boolean;
  onClose: () => void;
  evidence: EvidenceSpan | null;
}

export function EvidencePanel({ isOpen, onClose, evidence }: EvidencePanelProps) {
  if (!isOpen) return null;

  return (
    <>
      <div
        className={styles.overlay}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className={styles.panel} role="dialog" aria-label="Evidence detail">
        <header className={styles.header}>
          <h3>Evidence</h3>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Close panel"
          >
            ×
          </button>
        </header>
        <div className={styles.body}>
          {evidence ? (
            <>
              <section className={styles.spanSection}>
                <h4 className={styles.sectionTitle}>Exact span</h4>
                <blockquote className={styles.spanBlockquote}>
                  {evidence.text}
                </blockquote>
              </section>
              <section className={styles.metadataSection}>
                <h4 className={styles.sectionTitle}>Source</h4>
                <dl>
                  <dt>Issuing body</dt>
                  <dd>{evidence.metadata.issuingBody}</dd>
                  <dt>Publication date</dt>
                  <dd>{evidence.metadata.publicationDate}</dd>
                  <dt>Document type</dt>
                  <dd>{evidence.metadata.documentType}</dd>
                  <dt>Source identifier</dt>
                  <dd className={styles.sourceId}>
                    {evidence.metadata.sourceId}
                  </dd>
                </dl>
              </section>
            </>
          ) : (
            <p className={styles.empty}>No evidence selected.</p>
          )}
        </div>
      </aside>
    </>
  );
}
