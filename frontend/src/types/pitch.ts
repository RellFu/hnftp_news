/**
 * Core type definitions for the pitch assistant
 * Proactive / reactive workflow, evidence binding, downgrade handling
 */

/** Evidence metadata: issuing body, date, document type, source ID */
export interface EvidenceMetadata {
  issuingBody: string;
  publicationDate: string;
  documentType: string;
  sourceId: string;
}

/** Evidence span (evidence anchor) */
export interface EvidenceSpan {
  spanId: string;
  text: string;
  metadata: EvidenceMetadata;
  rerankerScore?: number;
}

/** Claim-bearing field with evidence binding */
export interface ClaimField {
  fieldName: string;
  claim: string;
  evidenceSpans: EvidenceSpan[];
  /** Whether rewritten in non-assertive form when downgraded */
  isDowngraded?: boolean;
  /** Downgrade reason */
  downgradeReason?: "low_relevance" | "no_authoritative_source" | "missing_provenance";
}

/** Pitch draft structure */
export interface PitchDraft {
  proposedAngle: string;
  whyItMattersNow: string;
  keyQuestions: string[];
  keyStakeholders: string[];
  claimFields: ClaimField[];
}

/** Validation segment for reactive mode: anchored or downgraded */
export type ValidationSegment =
  | { type: "anchored"; text: string; evidenceSpan: EvidenceSpan }
  | { type: "downgraded"; text: string; reason: string }
  | { type: "plain"; text: string };
