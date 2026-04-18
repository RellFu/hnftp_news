"""Reactive validation API routes."""

import re
import time

from fastapi import APIRouter

from app.schemas.pitch import ValidateRequest, ValidateResponse, ValidatedSegment, EvidenceSpanOut
from app.services.retrieval import hybrid_retrieve
from app.services.audit import log_audit, AuditEntry

router = APIRouter(prefix="/api/validate", tags=["validate"])


def _rewrite_non_assertive(text: str) -> str:
    """Rewrite claim to non-assertive form when evidence is insufficient."""
    text = text.strip().rstrip(".")
    if not text:
        return "[Content omitted — no authoritative source found]"
    # Add hedging: "may", "possibly", "reported but unverified"
    if text[0].isupper():
        return f"There may be {text[0].lower()}{text[1:]} (further verification from authoritative sources needed)."
    return f"Possibly {text} (authoritative sources not yet confirmed)."


def _split_sentences(text: str) -> list[str]:
    """Split into sentences; preserve trailing punctuation."""
    text = text.replace("。", ".")
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            if not p.endswith((".", "!", "?")):
                p += "."
            out.append(p)
    if not out and text.strip():
        out.append(text.strip() + ("." if not text.strip().endswith(".") else ""))
    return out


@router.post("", response_model=ValidateResponse)
async def validate_draft(req: ValidateRequest):
    """Validate draft pitch: highlight claims, retrieve evidence, rewrite unsupported as non-assertive."""
    start = time.perf_counter()
    sentences = _split_sentences(req.draft_text)
    segments = []
    for i, sent in enumerate(sentences[:8]):
        result = hybrid_retrieve(sent[:120], top_k=2, original_topic=sent)
        if result.evidence_sufficient and result.spans:
            s0 = result.spans[0]
            segments.append(
                ValidatedSegment(
                    type="anchored",
                    text=sent,
                    evidence_span=EvidenceSpanOut(
                        span_id=s0.span_id,
                        text=s0.text,
                        document_id=s0.document_id,
                        issuing_body=s0.metadata.issuing_body,
                        publication_date=str(s0.metadata.publication_date),
                        source_identifier=s0.metadata.source_identifier,
                        reranker_score=s0.reranker_score,
                    ),
                )
            )
        else:
            rewritten = _rewrite_non_assertive(sent)
            segments.append(
                ValidatedSegment(
                    type="downgraded",
                    text=rewritten,
                    downgrade_reason=result.downgrade_reason or "lack of authoritative sources",
                )
            )
    for sent in sentences[8:]:
        segments.append(ValidatedSegment(type="plain", text=sent))
    latency_ms = (time.perf_counter() - start) * 1000

    entry = AuditEntry(
        endpoint="validate",
        latency_ms=latency_ms,
        downgrade_labels=[s.downgrade_reason for s in segments if s.downgrade_reason],
    )
    log_audit(entry)

    return ValidateResponse(segments=segments, request_id=entry.request_id)
