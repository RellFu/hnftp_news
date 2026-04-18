"""Reactive workflow API: web search (Serper) + RAG + LLM -> news value + angle + pitch plan."""

import time

from fastapi import APIRouter

from app.core.config import HARD_TIMEOUT_SEC, LLM_MODEL
from app.schemas.pitch import (
    ReactivePitchRequest,
    ReactivePitchResponse,
    RagExcerptOut,
    WebSourceOut,
)
from app.services.reactive_pitch import run_reactive_pitch
from app.services.retrieval.retrieval import is_retrieval_warm
from app.services.audit import log_audit, AuditEntry

router = APIRouter(prefix="/api/reactive-pitch", tags=["reactive-pitch"])


@router.post("", response_model=ReactivePitchResponse)
async def reactive_pitch(req: ReactivePitchRequest):
    """Run Reactive workflow: Serper search -> RAG retrieval -> LLM. Cold start: no timeout; warm: 60s limit."""
    start = time.perf_counter()
    params = req.model_dump(exclude_none=True)
    if "topic" not in params and req.topic is None:
        params["topic"] = ""
    # Cold start (model + chunk encoding): no timeout; once warm, cap at 60s
    timeout_sec = None if not is_retrieval_warm() else float(HARD_TIMEOUT_SEC)
    result = run_reactive_pitch(params, timeout_sec=timeout_sec, start_time=start)
    latency_ms = (time.perf_counter() - start) * 1000

    web_sources = [WebSourceOut(title=s.get("title"), link=s.get("link"), snippet=s.get("snippet")) for s in result.get("web_sources", [])]
    rag_excerpts = [
        RagExcerptOut(
            span_id=e.get("span_id", ""),
            issuing_body=e.get("issuing_body", ""),
            publication_date=e.get("publication_date", ""),
            source_identifier=e.get("source_identifier", ""),
            text=e.get("text", ""),
        )
        for e in result.get("rag_excerpts", [])
    ]
    rag_used = result.get("rag_used", False)
    rag_error = result.get("rag_error")
    topic_relevant = result.get("topic_relevant", True)
    if result.get("timeout"):
        evidence_status = "insufficient"
        downgrade_message = "Request timed out after 60 seconds. Partial result below (if any); verify before use."
    elif rag_error:
        evidence_status = "error"
        downgrade_message = "Evidence from the knowledge base could not be retrieved. The pitch below is based on web search only; verify with additional sources."
    elif not topic_relevant:
        evidence_status = "insufficient"
        downgrade_message = "No evidence relevant to your topic was found. This system is designed for Hainan Free Trade Port reporting; your query may be outside this scope."
    elif not rag_used and not rag_excerpts:
        evidence_status = "insufficient"
        downgrade_message = "No knowledge base excerpts were found for this topic. The pitch is based on web search only."
    else:
        evidence_status = "sufficient"
        downgrade_message = None

    downgrade_labels = []
    if result.get("timeout"):
        downgrade_labels.append("request_timeout")
    if evidence_status not in ("sufficient", None):
        downgrade_labels.append(evidence_status)
    filter_settings = {
        "beat": params.get("beat") or params.get("topic") or "",
        "timeframe_start": params.get("timeframe_start") or "",
        "timeframe_end": params.get("timeframe_end") or "",
        "issuing_body_preference": params.get("issuing_body_preference"),
        "target_audience": params.get("target_audience") or "",
    }
    entry = AuditEntry(
        endpoint="reactive-pitch",
        latency_ms=latency_ms,
        retrieval_doc_ids=result.get("retrieval_doc_ids") or [],
        retrieval_span_ids=result.get("retrieval_span_ids") or [],
        filter_settings=filter_settings,
        prompt_version="v1",
        llm_version=LLM_MODEL,
        downgrade_labels=downgrade_labels,
        evidence_sufficient=(evidence_status == "sufficient"),
        timeout=result.get("timeout") or False,
    )
    log_audit(entry)

    cited_sources = result.get("cited_sources") or []
    if not isinstance(cited_sources, list):
        cited_sources = []

    return ReactivePitchResponse(
        news_value_assessment=result.get("news_value_assessment", ""),
        proposed_angle=result.get("proposed_angle", ""),
        pitch_plan=result.get("pitch_plan", ""),
        cited_sources=[
            {
                "issuing_body": s.get("issuing_body", ""),
                "publication_date": s.get("publication_date", ""),
                "snippet": s.get("snippet", ""),
                "span_id": s.get("span_id"),
            }
            for s in cited_sources if isinstance(s, dict)
        ],
        cited_span_ids=result.get("cited_span_ids") or [],
        web_sources=web_sources,
        rag_excerpts=rag_excerpts,
        rag_used=rag_used,
        rag_error=rag_error,
        evidence_status=evidence_status,
        downgrade_message=downgrade_message,
        error=result.get("error"),
        web_search_error=result.get("web_search_error"),
        request_id=entry.request_id,
        timeout=result.get("timeout"),
        issuing_body_preference=result.get("issuing_body_preference") or [],
        issuing_body_preference_matched_spans=result.get("issuing_body_preference_matched_spans") or 0,
        issuing_body_preference_fallback=result.get("issuing_body_preference_fallback") or False,
    )
