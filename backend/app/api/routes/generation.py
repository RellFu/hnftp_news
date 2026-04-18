"""Generation API routes."""

import logging
import time
import traceback

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def _safe_err(err: str) -> str:
    """Avoid ascii codec when logging error messages that may contain non-ASCII."""
    return (err or "").encode("ascii", errors="replace").decode("ascii")

from app.schemas.pitch import (
    GenerateRequest,
    GenerateResponse,
    PitchDraftOut,
    ClaimFieldOut,
    EvidenceSpanOut,
)
from app.services.retrieval import hybrid_retrieve
from app.services.generation import build_generation_prompt, generate_pitch_with_llm
from app.services.audit import log_audit, AuditEntry
from app.core.config import llm_available

router = APIRouter(prefix="/api/generation", tags=["generation"])


def _topic_questions(query: str) -> list[str]:
    """Generate questions tailored to query topic."""
    q = query.lower()
    if any(w in q for w in ["tax", "税务", "税收"]):
        return [
            "Which sectors qualify for the 15% corporate income tax rate?",
            "What are the eligibility criteria for tax incentives?",
            "How does Hainan compare to other FTZs on tax treatment?",
        ]
    if any(w in q for w in ["customs", "海关", "tariff", "零关税"]):
        return [
            "What goods are eligible for zero-tariff import?",
            "How does the separate customs regime work?",
            "What documentation is required for customs clearance?",
        ]
    if any(w in q for w in ["investment", "投资", "lingshui", "陵水"]):
        return [
            "What sectors are prioritised for foreign investment?",
            "What local stakeholders are affected?",
            "What are the latest policy updates in the area?",
        ]
    return [
        "What is the policy basis for this development?",
        "Which stakeholders are most affected?",
        "What is the local relevance and next steps?",
    ]


def _topic_stakeholders(query: str, spans: list) -> list[str]:
    """Extract or infer stakeholders from query and retrieval."""
    issuers = list({s.metadata.issuing_body for s in spans[:5]} - {"Unknown"})
    q = query.lower()
    if "tax" in q or "税务" in q:
        return ["State Taxation Administration", "Hainan Commerce Bureau"] + issuers[:2]
    if "customs" in q or "海关" in q:
        return ["Haikou Customs", "General Administration of Customs"] + issuers[:2]
    return ["Hainan FTP Authority", "Relevant provincial departments"] + issuers[:2]


def _fallback_pitch_from_retrieval(query: str, spans: list, evidence_sufficient: bool):
    """Build a deterministic fallback pitch from retrieval result."""
    q_short = query.strip()[:80]
    angle = f"{q_short} — policy angle grounded in Hainan FTP sources" if evidence_sufficient else f"{q_short} — (preliminary; requires further verification)"
    timeliness = (
        "Policy developments align with investor and media interest; multiple authoritative sources available."
        if evidence_sufficient
        else "Timeliness may warrant further verification; limited authoritative evidence found."
    )
    key_questions = _topic_questions(query)
    key_stakeholders = _topic_stakeholders(query, spans)[:4]
    claim_fields = []
    for i, s in enumerate(spans[:3]):
        excerpt = s.text[:150] + "..." if len(s.text) > 150 else s.text
        cf = ClaimFieldOut(
            field_name=f"Evidence {i+1}",
            claim=excerpt,
            evidence_span_ids=[s.span_id],
            is_downgraded=not evidence_sufficient,
            downgrade_reason="lack of authoritative sources" if not evidence_sufficient else None,
        )
        claim_fields.append(cf)
    return PitchDraftOut(
        proposed_angle=angle,
        why_it_matters_now=timeliness,
        key_questions=key_questions,
        key_stakeholders=key_stakeholders,
        claim_fields=claim_fields,
    )


DOWNGRADE_MSG_INSUFFICIENT = "Evidence from the knowledge base was insufficient. Use the pitch as preliminary and verify with additional sources."
DOWNGRADE_MSG_ERROR = "Evidence could not be retrieved. The pitch below is a fallback draft; verify all claims with primary sources."


@router.post("", response_model=GenerateResponse)
async def generate_pitch(req: GenerateRequest):
    """Generate pitch draft from query. Uses LLM when configured, else deterministic fallback. On retrieval failure returns structured downgrade (no raise)."""
    start = time.perf_counter()
    try:
        result = hybrid_retrieve(req.query, top_k=5, original_topic=req.query)
    except Exception as e:
        logger.warning("Generation retrieval failed: %s", e)
        latency_ms = (time.perf_counter() - start) * 1000
        log_audit(AuditEntry(endpoint="generation", latency_ms=latency_ms))
        fallback_pitch = _fallback_pitch_from_retrieval(req.query, [], evidence_sufficient=False)
        return GenerateResponse(
            pitch=fallback_pitch,
            evidence_spans=[],
            evidence_sufficient=False,
            evidence_status="error",
            downgrade_message=DOWNGRADE_MSG_ERROR,
        )

    pitch = None
    if llm_available():
        pitch, err = generate_pitch_with_llm(
            req.query, result, beat=req.beat, timeframe=req.timeframe
        )
        if err:
            try:
                logger.warning(
                    "LLM generation failed, using fallback draft: %s",
                    _safe_err(err),
                )
            except Exception:
                pass
            pitch = None  # fall back to deterministic draft
    else:
        logger.debug("LLM not configured (no LLM_API_KEY), using deterministic fallback")
    if pitch is None:
        pitch = _fallback_pitch_from_retrieval(
            req.query, result.spans, result.evidence_sufficient
        )
    latency_ms = (time.perf_counter() - start) * 1000

    evidence_status = "sufficient" if result.evidence_sufficient else "insufficient"
    downgrade_message = None if result.evidence_sufficient else DOWNGRADE_MSG_INSUFFICIENT

    entry = AuditEntry(
        endpoint="generation",
        retrieval_doc_ids=[s.document_id for s in result.spans],
        retrieval_span_ids=[s.span_id for s in result.spans],
        filter_settings={"beat": req.beat, "timeframe": req.timeframe},
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
    return GenerateResponse(
        pitch=pitch,
        evidence_spans=spans_out,
        evidence_sufficient=result.evidence_sufficient,
        evidence_status=evidence_status,
        downgrade_message=downgrade_message,
        request_id=entry.request_id,
    )
