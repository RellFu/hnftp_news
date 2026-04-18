"""Retrieval API routes. On failure returns structured response (evidence_status=error), no raise."""

import logging
import time

from fastapi import APIRouter

from app.schemas.pitch import RetrievalRequest, RetrievalResponse, EvidenceSpanOut
from app.services.retrieval import hybrid_retrieve
from app.services.audit import log_audit, AuditEntry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])

DOWNGRADE_MSG_INSUFFICIENT = "Evidence from the knowledge base was insufficient for this query. Use the results as preliminary only and verify with additional sources."
DOWNGRADE_MSG_ERROR = "Evidence could not be retrieved from the knowledge base. You can try again or proceed without evidence-backed suggestions."


@router.post("", response_model=RetrievalResponse)
async def retrieve(req: RetrievalRequest):
    """Retrieve evidence spans for a query. On exception returns 200 with evidence_status=error."""
    start = time.perf_counter()
    top_k = req.top_k or 5
    try:
        result = hybrid_retrieve(req.query, top_k=top_k, original_topic=req.query)
    except Exception as e:
        logger.warning("Retrieval failed: %s", e)
        latency_ms = (time.perf_counter() - start) * 1000
        log_audit(AuditEntry(endpoint="retrieval", latency_ms=latency_ms))
        return RetrievalResponse(
            spans=[],
            evidence_sufficient=False,
            evidence_status="error",
            downgrade_reason="retrieval_unavailable",
            downgrade_message=DOWNGRADE_MSG_ERROR,
        )

    latency_ms = (time.perf_counter() - start) * 1000
    evidence_status = "sufficient" if result.evidence_sufficient else "insufficient"
    downgrade_message = None if result.evidence_sufficient else DOWNGRADE_MSG_INSUFFICIENT

    entry = AuditEntry(
        endpoint="retrieval",
        retrieval_doc_ids=[s.document_id for s in result.spans],
        retrieval_span_ids=[s.span_id for s in result.spans],
        filter_settings={"top_k": top_k, "timeframe": req.timeframe, "issuing_body": req.issuing_body},
        latency_ms=latency_ms,
        downgrade_labels=[result.downgrade_reason] if result.downgrade_reason else [],
        evidence_sufficient=result.evidence_sufficient,
    )
    log_audit(entry)

    spans_out = [
        EvidenceSpanOut(
            span_id=s.span_id,
            text=s.text,
            document_id=s.document_id,
            issuing_body=s.metadata.issuing_body,
            publication_date=str(s.metadata.publication_date),
            source_identifier=s.metadata.source_identifier,
            reranker_score=s.reranker_score,
        )
        for s in result.spans
    ]
    return RetrievalResponse(
        spans=spans_out,
        evidence_sufficient=result.evidence_sufficient,
        evidence_status=evidence_status,
        downgrade_reason=result.downgrade_reason,
        downgrade_message=downgrade_message,
        request_id=entry.request_id,
    )
