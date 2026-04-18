"""Active retrieval API: multi-topic web search + LLM to produce diverse pitch suggestions (same format as passive)."""

import logging
import time
from datetime import date

from fastapi import APIRouter

logger = logging.getLogger(__name__)

from app.schemas.pitch import ActiveSearchResponse, PitchSuggestionOut, RagExcerptOut, WebSourceOut
from app.services.serper_client import serper_search
from app.services.retrieval import hybrid_retrieve
from app.services.active_pitch import run_active_pitch
from app.services.audit import log_audit, AuditEntry
from app.core.config import serper_available, llm_available, TOP_K, HARD_TIMEOUT_SEC, LLM_MODEL
from app.services.retrieval.retrieval import is_retrieval_warm

router = APIRouter(prefix="/api/active-search", tags=["active-search"])

# Broad coverage: policy, tourism, culture, ecology, sports, livelihood (Hainan / FTP context). Year + recency for timeliness.
RECENCY_SUFFIX = " past 3 days"

# Theme-aligned RAG queries so active retrieval gets diverse knowledge-base coverage (policy, tourism, culture, ecology/sports/livelihood).
RAG_THEME_QUERIES = [
    "Hainan Free Trade Port policy regulations",
    "Hainan tourism travel policy",
    "Hainan culture heritage",
    "Hainan ecology sports livelihood",
]

def _default_hot_queries() -> list[str]:
    y = date.today().year
    base = [
        f"Hainan Free Trade Port policy {y}",
        f"Hainan tourism resort travel {y}",
        f"Hainan culture heritage ecology {y}",
        f"Hainan sports events livelihood {y}",
    ]
    return [q + RECENCY_SUFFIX for q in base]


def _merge_web_results(queries_results: list[tuple[str, list[dict], str | None]]) -> tuple[list[dict], str | None]:
    """Merge results from multiple queries; dedupe by link. Return (merged list, first error if any)."""
    seen_links = set()
    merged = []
    first_error = None
    for _query, raw_list, err in queries_results:
        if err and first_error is None:
            first_error = err
        for r in raw_list:
            link = (r.get("link") or "").strip()
            if link and link not in seen_links:
                seen_links.add(link)
                merged.append({"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")})
    return merged, first_error


def _active_partial_response(
    query_used: str,
    results: list[dict],
    rag_out: list[RagExcerptOut],
    rag_used: bool,
    rag_error: str | None,
    evidence_status: str,
    downgrade_message: str | None,
    error: str | None,
    timeout: bool,
) -> ActiveSearchResponse:
    """Build response (full or partial) for active_search."""
    return ActiveSearchResponse(
        query_used=query_used,
        results=[WebSourceOut(title=r.get("title"), link=r.get("link"), snippet=r.get("snippet")) for r in results],
        pitches=[] if timeout else [],  # partial: no pitches on timeout
        rag_used=rag_used,
        rag_excerpts=rag_out,
        rag_error=rag_error,
        evidence_status=evidence_status,
        downgrade_message=downgrade_message,
        error=error,
        timeout=timeout,
    )


@router.post("", response_model=ActiveSearchResponse)
async def active_search(body: dict | None = None):
    """Run multi-topic hot-topic web searches, then LLM for 3–5 pitch suggestions. Hard timeout 60s; returns partial result + notice on timeout."""
    custom_query = (body or {}).get("query")
    if custom_query and (custom_query := (custom_query or "").strip()[:200]):
        queries_to_run = [custom_query]
        query_used = custom_query
    else:
        queries_to_run = _default_hot_queries()
        query_used = "; ".join(queries_to_run)

    start = time.perf_counter()
    # Cold start: no request timeout; warm: 60s
    timeout_sec = None if not is_retrieval_warm() else float(HARD_TIMEOUT_SEC)
    results: list[dict] = []
    error: str | None = None
    if serper_available():
        queries_results = []
        for q in queries_to_run:
            raw, err = serper_search(q, num=8, date_restrict="d3")
            queries_results.append((q, raw, err))
        results, error = _merge_web_results(queries_results)
    else:
        error = "SERPER_API_KEY not configured; cannot run active search"

    if timeout_sec is not None and (time.perf_counter() - start) >= timeout_sec:
        latency_ms = (time.perf_counter() - start) * 1000
        log_audit(AuditEntry(
            endpoint="active-search",
            latency_ms=latency_ms,
            retrieval_doc_ids=[],
            retrieval_span_ids=[],
            filter_settings={"query_used": query_used, "top_k": TOP_K},
            prompt_version="v1",
            llm_version=LLM_MODEL,
            downgrade_labels=["request_timeout"],
            evidence_sufficient=False,
            timeout=True,
        ))
        return _active_partial_response(
            query_used, results, [], False, None,
            "insufficient", "Request timed out after 60 seconds. Partial result below (web only); verify before use.",
            error, timeout=True,
        )

    rag_used = False
    rag_excerpts = []
    rag_out = []
    rag_error = None
    rag_spans_list: list = []
    try:
        seen_rids: set[str] = set()
        for q in RAG_THEME_QUERIES:
            res = hybrid_retrieve(q, top_k=TOP_K)
            for s in res.spans:
                if s.span_id not in seen_rids:
                    seen_rids.add(s.span_id)
                    rag_spans_list.append(s)
        rag_spans_list = rag_spans_list[:TOP_K]
        rag_used = len(rag_spans_list) > 0
        rag_excerpts = [
            {
                "span_id": s.span_id or "",
                "issuing_body": getattr(s.metadata, "issuing_body", "Unknown"),
                "publication_date": str(getattr(s.metadata, "publication_date", "")),
                "source_identifier": getattr(s.metadata, "source_identifier", "") or "",
                "text": (s.text or "")[:1500],
            }
            for s in rag_spans_list[:TOP_K]
        ]
        rag_out = [
            RagExcerptOut(span_id=e["span_id"], issuing_body=e["issuing_body"], publication_date=e["publication_date"], source_identifier=e["source_identifier"], text=e["text"])
            for e in rag_excerpts
        ]
    except Exception as e:
        rag_error = "Knowledge base temporarily unavailable. Results are based on web search only."
        logger.warning("Active RAG failed: %s", e)

    if timeout_sec is not None and (time.perf_counter() - start) >= timeout_sec:
        latency_ms = (time.perf_counter() - start) * 1000
        retrieval_doc_ids = [s.document_id for s in rag_spans_list[:TOP_K]]
        retrieval_span_ids = [s.span_id for s in rag_spans_list[:TOP_K]]
        log_audit(AuditEntry(
            endpoint="active-search",
            latency_ms=latency_ms,
            retrieval_doc_ids=retrieval_doc_ids,
            retrieval_span_ids=retrieval_span_ids,
            filter_settings={"query_used": query_used, "top_k": TOP_K},
            prompt_version="v1",
            llm_version=LLM_MODEL,
            downgrade_labels=["request_timeout"],
            evidence_sufficient=False,
            timeout=True,
        ))
        if rag_error:
            es, dm = "error", "Knowledge base could not be retrieved. Pitches are based on web search only; verify with additional sources."
        elif not rag_used and not rag_out:
            es, dm = "insufficient", "No knowledge base excerpts were used. Pitches are based on web search only."
        else:
            es, dm = "insufficient", "Request timed out after 60 seconds. Partial result below (web + RAG, no pitch text); verify before use."
        return _active_partial_response(query_used, results, rag_out, rag_used, rag_error, es, dm, error, timeout=True)

    pitches = []
    if (results or rag_excerpts) and llm_available():
        # When cold (timeout_sec=None), still cap LLM at 60s; when warm, use remaining time
        if timeout_sec is None:
            remaining = float(HARD_TIMEOUT_SEC)
        else:
            remaining = timeout_sec - (time.perf_counter() - start)
        llm_timeout = max(1, int(remaining)) if remaining > 0 else 1
        pitches = run_active_pitch(
            results if results else [{"title": "N/A", "link": "", "snippet": "No web results."}],
            rag_excerpts=rag_excerpts if rag_excerpts else None,
            timeout_sec=llm_timeout,
        )
        if not pitches and not error:
            error = "LLM returned no pitch suggestions; try again"
    elif (results or rag_excerpts) and not llm_available():
        error = "LLM not configured; cannot generate pitches (web/RAG results retrieved but model not called)"

    if timeout_sec is not None and (time.perf_counter() - start) >= timeout_sec and not pitches:
        latency_ms = (time.perf_counter() - start) * 1000
        retrieval_doc_ids = [s.document_id for s in rag_spans_list[:TOP_K]]
        retrieval_span_ids = [s.span_id for s in rag_spans_list[:TOP_K]]
        log_audit(AuditEntry(
            endpoint="active-search",
            latency_ms=latency_ms,
            retrieval_doc_ids=retrieval_doc_ids,
            retrieval_span_ids=retrieval_span_ids,
            filter_settings={"query_used": query_used, "top_k": TOP_K},
            prompt_version="v1",
            llm_version=LLM_MODEL,
            downgrade_labels=["request_timeout"],
            evidence_sufficient=False,
            timeout=True,
        ))
        dm = "Request timed out after 60 seconds. Partial result below (if any); verify before use."
        return _active_partial_response(query_used, results, rag_out, rag_used, rag_error, "insufficient", dm, error, timeout=True)

    if rag_error:
        evidence_status = "error"
        downgrade_message = "Knowledge base could not be retrieved. Pitches are based on web search only; verify with additional sources."
    elif not rag_used and not rag_out:
        evidence_status = "insufficient"
        downgrade_message = "No knowledge base excerpts were used. Pitches are based on web search only."
    else:
        evidence_status = "sufficient"
        downgrade_message = None

    latency_ms = (time.perf_counter() - start) * 1000
    retrieval_doc_ids = [s.document_id for s in rag_spans_list[:TOP_K]]
    retrieval_span_ids = [s.span_id for s in rag_spans_list[:TOP_K]]
    downgrade_labels = [] if evidence_status == "sufficient" else [evidence_status]
    log_audit(AuditEntry(
        endpoint="active-search",
        latency_ms=latency_ms,
        retrieval_doc_ids=retrieval_doc_ids,
        retrieval_span_ids=retrieval_span_ids,
        filter_settings={"query_used": query_used, "top_k": TOP_K},
        prompt_version="v1",
        llm_version=LLM_MODEL,
        downgrade_labels=downgrade_labels,
        evidence_sufficient=(evidence_status == "sufficient"),
        timeout=False,
    ))
    return ActiveSearchResponse(
        query_used=query_used,
        results=[WebSourceOut(title=r.get("title"), link=r.get("link"), snippet=r.get("snippet")) for r in results],
        pitches=[PitchSuggestionOut(
            theme=p.get("theme"),
            title=p.get("title"),
            news_value_assessment=p.get("news_value_assessment", ""),
            proposed_angle=p.get("proposed_angle", ""),
            pitch_plan=p.get("pitch_plan", ""),
        ) for p in pitches],
        rag_used=rag_used,
        rag_excerpts=rag_out,
        rag_error=rag_error,
        evidence_status=evidence_status,
        downgrade_message=downgrade_message,
        error=error,
        timeout=False,
    )
