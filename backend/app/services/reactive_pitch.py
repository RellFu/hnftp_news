"""
Reactive workflow: web search (Serper) + RAG knowledge base + LLM for news value assessment and pitch plan.
Design: RECENT EVENTS (web) + POLICY/BACKGROUND (RAG) -> news pitch.
- Content query: built from beat only (or legacy topic) for precise retrieval.
- Web search: Hainan-scoped query from beat; optional date_restrict from user timeframe.
- RAG: same content query + metadata filters (date range, issuing_body preference).
- LLM: receives structured context (beat, timeframe, issuing body, target audience).
"""

import logging
import re
import time
from typing import Any, Optional

from app.core.config import llm_available, serper_available, TOP_K

logger = logging.getLogger(__name__)
from app.services.retrieval import hybrid_retrieve
from app.services.serper_client import serper_search
from app.services.llm_client import call_chat, extract_json_from_response

# Scope all web and RAG retrieval to Hainan Free Trade Port so results are not generic (e.g. US Treasury).
HAINAN_SCOPE_PREFIX = "Hainan Free Trade Port "

# Terms that indicate Hainan/FTP domain; user topic terms that are only these get treated as in-domain (no extra relevance check).
HAINAN_DOMAIN_TERMS = frozenset(
    {"hainan", "海南", "ftp", "free", "trade", "port", "policy", "china", "中国", "customs", "tax", "tourism", "travel", "investment", "自贸", "ling", "sanya", "haikou"}
)


def _topic_relevant_to_retrieval(topic: str, web_sources: list[dict], rag_excerpts: list[dict]) -> bool:
    """
    Return True if we should run the LLM: either we have RAG content (retrieval already returned
    something), or at least one user topic term appears in web + RAG. Avoids skipping LLM when
    RAG returns Chinese content that doesn't contain the query's English words (e.g. task-045/046).
    """
    # If we have any RAG excerpt, retrieval already matched the query → run LLM
    if rag_excerpts and any((e.get("text") or "").strip() for e in rag_excerpts):
        return True
    raw = (topic or "").strip().lower()
    if not raw:
        return True
    tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", raw))
    if not tokens:
        return True
    user_terms = tokens - HAINAN_DOMAIN_TERMS
    if not user_terms:
        return True
    combined = " ".join(
        [str(s.get("title") or "") + " " + str(s.get("snippet") or "") for s in (web_sources or [])]
        + [str(e.get("text") or "") for e in (rag_excerpts or [])]
    ).lower()
    for term in user_terms:
        if term in combined:
            return True
    return False


def _hainan_scoped_query(topic: str) -> str:
    """Return a query string scoped to Hainan/FTP so Serper and RAG return Hainan-relevant results."""
    t = (topic or "").strip()[:300]
    if not t:
        return HAINAN_SCOPE_PREFIX.strip()
    lower = t.lower()
    if "hainan" in lower or "海南" in t or "free trade port" in lower or "ftp" in lower:
        return t
    return HAINAN_SCOPE_PREFIX + t


def _ascii_safe(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"[^\x00-\x7F]+", "?", s)


def _timeframe_to_serper_date_restrict(timeframe_start: Optional[str], timeframe_end: Optional[str]) -> Optional[str]:
    """Map user date range to Serper dateRestrict (d1, d7, w1, m1). Returns None if no range or custom range."""
    start = (timeframe_start or "").strip()[:10]
    end = (timeframe_end or "").strip()[:10]
    if not start or not end or start[4] != "-" or end[4] != "-":
        return None
    try:
        from datetime import datetime
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(end, "%Y-%m-%d")
        days = (d1 - d0).days
        if days <= 1:
            return "d1"
        if days <= 7:
            return "d7"
        if days <= 30:
            return "d30"
        return "m1"
    except (ValueError, TypeError):
        return None


SYSTEM_PROMPT = """You are a news editor for Hainan and the Hainan Free Trade Port (FTP). Your job is to turn RECENT EVENTS into a news pitch by combining:
- RECENT EVENTS (from web search): What happened in the time window the user cares about—e.g. tourist numbers, flight surges, new data, social posts about Hainan, policy announcements, incidents. This is the NEWS HOOK. Only refer to dates or timeframes that appear in the web results or that the user has indicated; do not invent future or arbitrary dates.
- POLICY/BACKGROUND (from knowledge base): Official Hainan/FTP policies, regulations, or context. Use this to explain why the event matters, not as the main news.

You will receive:
1) Web search results: scoped to Hainan/FTP. These are your primary source for WHAT IS NEW. Base the news value and angle on these developments; respect the user's topic and timeframe.
2) Knowledge base excerpts: Hainan FTP policies/official sources. Use these as background to frame the story, not as the lead.

CITATION RULE: When you cite policy or knowledge base content, always state the source: the issuing body and date. For example: "According to Hainan Free Trade Port Authority (2024-03), ..." or "As the Department of Ecology and Environment (2024-02) states, ...". Do not mention policy without attributing to a source (issuing body and date).

Each knowledge base excerpt is labeled with a span_id (e.g. [span_id=doc-span-abc123]). When you list a policy source in the "sources" array, you MUST include the exact "span_id" of that excerpt so the system can link your citation to the evidence. Copy the span_id from the excerpt line; do not invent one.

Output language: English only for all fields below. If knowledge base excerpts or web titles are in Chinese, you may keep Chinese in citations or source titles, but the news_value_assessment, proposed_angle, and pitch_plan must be written in English.

Your tasks:
1) NEWS VALUE ASSESSMENT: What happened (from web)? Why does it matter for Hainan/FTP (using policy context from RAG)? 2-4 sentences. The lead should be a concrete development, not evergreen policy alone. When referring to policy, cite issuing body and date.
2) PROPOSED ANGLE: One sentence that ties an event (from web) to policy/context (from RAG).
3) PITCH PLAN: 3-5 bullet points: how to report this story using the event as the hook and policy as context.

Respond with a single JSON object only, no markdown or code fence. Use exactly these keys:
{
  "news_value_assessment": "your assessment text (cite policy with issuing body and date)",
  "proposed_angle": "one sentence angle",
  "pitch_plan": "bullet 1\\nbullet 2\\nbullet 3",
  "sources": [{"issuing_body": "Name", "publication_date": "YYYY-MM-DD", "snippet": "short quote or summary", "span_id": "exact span_id from the excerpt line"}]
}

The "sources" array is optional but recommended: list each policy/source you cited. For each knowledge base source you MUST include "span_id" (copy the value from the excerpt's [span_id=...]). Omit "sources" if you did not cite any knowledge base excerpt.

Example (format only): sources: [{"issuing_body": "Hainan Department of Tourism, Culture, Radio, Television and Sports", "publication_date": "2024-02-01", "snippet": "short quote", "span_id": "doc-span-abc123"}].
"""


def run_reactive_pitch(
    params: dict[str, Any],
    timeout_sec: Optional[float] = None,
    start_time: Optional[float] = None,
) -> dict[str, Any]:
    """
    Run the full Reactive workflow: Serper search -> RAG retrieval -> LLM (value + angle + plan).
    params: topic (legacy), beat, timeframe_start, timeframe_end, issuing_body_preference (list or str), target_audience.
    Optional: skip_retrieval=True to run a no-retrieval baseline (no web, no RAG; LLM gets only user criteria).
    If timeout_sec and start_time are set, returns partial result with timeout=True when elapsed >= timeout_sec.
    Returns dict with keys: news_value_assessment, proposed_angle, pitch_plan, web_sources, rag_excerpts, rag_used,
    retrieval_span_ids, retrieval_doc_ids, error, timeout.
    """
    t0 = start_time if start_time is not None else time.perf_counter()
    skip_retrieval = params.get("skip_retrieval") is True
    topic_legacy = (params.get("topic") or "").strip()[:300]
    beat = (params.get("beat") or "").strip()[:300]
    timeframe_start = (params.get("timeframe_start") or "").strip() or None
    timeframe_end = (params.get("timeframe_end") or "").strip() or None
    issuing_pref = params.get("issuing_body_preference")
    if isinstance(issuing_pref, str):
        issuing_bodies = [issuing_pref.strip()] if issuing_pref.strip() else None
    elif isinstance(issuing_pref, list):
        issuing_bodies = [str(x).strip() for x in issuing_pref if str(x).strip()] or None
    else:
        issuing_bodies = None
    target_audience = (params.get("target_audience") or "").strip() or None

    content_query_terms = beat or topic_legacy
    out = {
        "news_value_assessment": "",
        "proposed_angle": "",
        "pitch_plan": "",
        "cited_sources": [],
        "web_sources": [],
        "rag_excerpts": [],
        "rag_used": False,
        "rag_error": None,
        "topic_relevant": True,
        "error": None,
        "web_search_error": None,
        "retrieval_span_ids": [],
        "retrieval_doc_ids": [],
        "cited_span_ids": [],
        "timeout": False,
        "issuing_body_preference": issuing_bodies or [],
        "issuing_body_preference_matched_spans": 0,
        "issuing_body_preference_fallback": False,
    }
    if not content_query_terms:
        out["error"] = "Topic or beat is required"
        return out

    search_query = _hainan_scoped_query(content_query_terms)

    # 1) Web search: skip when running no-retrieval baseline
    date_restrict = _timeframe_to_serper_date_restrict(timeframe_start, timeframe_end)
    web_results = []
    web_search_error = None
    if not skip_retrieval and serper_available():
        web_results, web_search_error = serper_search(search_query, num=8, date_restrict=date_restrict)
        logger.info("Reactive Serper: query=%r, date_restrict=%s, results=%s, error=%s", search_query[:60], date_restrict, len(web_results), web_search_error)
    elif not skip_retrieval:
        web_search_error = "SERPER_API_KEY not set or not loaded. Set it in project root .env (e.g. news/.env) and restart the backend."
        out["web_search_error"] = web_search_error
        logger.warning("Reactive: Serper skipped (SERPER_API_KEY not set).")
    out["web_sources"] = [{"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")} for r in web_results]
    if web_search_error and not out.get("web_search_error"):
        out["web_search_error"] = _ascii_safe(web_search_error)

    if timeout_sec is not None and (time.perf_counter() - t0) >= timeout_sec:
        out["timeout"] = True
        return out

    # 2) RAG retrieval: skip when running no-retrieval baseline
    rag_spans = []
    if not skip_retrieval:
        try:
            rag_result = hybrid_retrieve(
                search_query,
                top_k=TOP_K,
                date_start=timeframe_start,
                date_end=timeframe_end,
                issuing_bodies=issuing_bodies,
                original_topic=content_query_terms,
            )
            rag_spans = rag_result.spans
            out["rag_used"] = len(rag_spans) > 0
            out["retrieval_evidence_sufficient"] = bool(
                getattr(rag_result, "evidence_sufficient", False)
            )
            out["rag_excerpts"] = [
                {
                    "span_id": s.span_id or "",
                    "issuing_body": getattr(s.metadata, "issuing_body", "Unknown"),
                    "publication_date": str(getattr(s.metadata, "publication_date", "")),
                    "source_identifier": getattr(s.metadata, "source_identifier", "") or "",
                    "text": (s.text or "")[:1500],
                }
                for s in rag_spans[:TOP_K]
            ]
            out["retrieval_span_ids"] = [s.span_id for s in rag_spans[:TOP_K]]
            out["retrieval_doc_ids"] = [s.document_id for s in rag_spans[:TOP_K]]
            pref_set = (
                frozenset((b or "").strip() for b in (issuing_bodies or []) if (b or "").strip())
            )
            if pref_set:
                matched = 0
                for s in rag_spans[:TOP_K]:
                    ib = (getattr(s.metadata, "issuing_body", "") or "").strip()
                    if ib in pref_set:
                        matched += 1
                out["issuing_body_preference_matched_spans"] = matched
                out["issuing_body_preference_fallback"] = bool(matched == 0 and out["rag_used"])
        except Exception as e:
            logger.warning("Reactive RAG failed: %s", e)
            out["rag_used"] = False
            out["rag_excerpts"] = []
            out["rag_error"] = "Knowledge base temporarily unavailable. Results are based on web search only."

    if timeout_sec is not None and (time.perf_counter() - t0) >= timeout_sec:
        out["timeout"] = True
        return out

    # Topic relevance: require both (a) retrieval evidence sufficient when RAG is used,
    # and (b) overlap between user topic terms and web/RAG content. When retrieval
    # evidence is insufficient (e.g. out-of-domain topic like "bachuan"), we skip LLM
    # generation and surface this as evidence_status=insufficient at the API layer.
    retrieval_sufficient = bool(out.get("retrieval_evidence_sufficient"))
    if skip_retrieval or out.get("rag_error"):
        out["topic_relevant"] = _topic_relevant_to_retrieval(
            content_query_terms, out["web_sources"], out["rag_excerpts"]
        )
    else:
        out["topic_relevant"] = retrieval_sufficient and _topic_relevant_to_retrieval(
            content_query_terms, out["web_sources"], out["rag_excerpts"]
        )
    if not out["topic_relevant"]:
        logger.info("Reactive: content query %r has no overlap with retrieval -> evidence insufficient, skip LLM", content_query_terms[:50])
        return out

    # 3) Build context for LLM (structured + web + RAG)
    timeframe_str = ""
    if timeframe_start and timeframe_end:
        timeframe_str = f"{timeframe_start} to {timeframe_end}"
    elif timeframe_start:
        timeframe_str = timeframe_start
    elif timeframe_end:
        timeframe_str = timeframe_end
    structured = [
        f"Beat / topic: {content_query_terms}",
        f"Timeframe: {timeframe_str or '(not specified)'}",
        f"Issuing body preference: {', '.join(issuing_bodies) if issuing_bodies else '(any)'}",
        f"Target audience: {target_audience or '(not specified)'}",
    ]
    web_block = "No web results (Serper not configured or search failed)."
    if web_results:
        web_block = "\n".join(
            f"- [{r.get('title', '')}] {r.get('snippet', '')} (Source: {r.get('link', '')})"
            for r in web_results[:8]
        )
    # Limit each excerpt to 550 chars; keep span_id so the LLM can cite it in sources and support claim-span checks
    RAG_EXCERPT_CHARS = 550
    rag_block = "No knowledge base excerpts."
    if rag_spans:
        rag_block = "\n".join(
            f"- [span_id={s.span_id or ''}] [{s.metadata.issuing_body}, {s.metadata.publication_date}] {(s.text or '')[:RAG_EXCERPT_CHARS]}{'...' if len(s.text or '') > RAG_EXCERPT_CHARS else ''}"
            for s in rag_spans[:TOP_K]
        )
        # Log first excerpt length to verify prompt injection size (should be <= RAG_EXCERPT_CHARS)
        first_len = len((rag_spans[0].text or "")[:RAG_EXCERPT_CHARS])
        logger.info("Reactive pitch: rag_excerpt_chars=%s first_excerpt_len=%s num_excerpts=%s", RAG_EXCERPT_CHARS, first_len, min(len(rag_spans), TOP_K))

    user_prompt = f"""User criteria (use these when assessing news value and angle):
{chr(10).join(structured)}

## Web search results (use these for the news hook: events, data, social posts)
{web_block}

## Knowledge base excerpts (policy/background — use to frame the story, not as the lead)
{rag_block}

Produce the JSON. The pitch should be driven by events from the web results; use knowledge base only as context. Respect the user's timeframe and target audience. Do not invent dates; use only dates that appear in the web results or the user's timeframe."""

    if not llm_available():
        out["error"] = "LLM not configured (set LLM_API_KEY)."
        return out

    llm_timeout = 60
    if timeout_sec is not None:
        remaining = timeout_sec - (time.perf_counter() - t0)
        if remaining <= 0:
            out["timeout"] = True
            return out
        llm_timeout = min(60, int(remaining))

    def _parse_llm_output(raw: str) -> None:
        data = extract_json_from_response(raw)
        out["news_value_assessment"] = _ascii_safe(str(data.get("news_value_assessment", "")))
        out["proposed_angle"] = _ascii_safe(str(data.get("proposed_angle", "")))
        out["pitch_plan"] = _ascii_safe(str(data.get("pitch_plan", "")))
        allowed_span_ids = frozenset(s.span_id for s in rag_spans[:TOP_K]) if rag_spans else frozenset()
        out["cited_sources"] = []
        out["cited_span_ids"] = []
        if isinstance(data.get("sources"), list):
            for s in data["sources"][:20]:
                if not isinstance(s, dict):
                    continue
                span_id_raw = (s.get("span_id") or "").strip()
                span_id = span_id_raw if span_id_raw in allowed_span_ids else None
                out["cited_sources"].append({
                    "issuing_body": str(s.get("issuing_body", "")),
                    "publication_date": str(s.get("publication_date", "")),
                    "snippet": str(s.get("snippet", ""))[:500],
                    "span_id": span_id,
                })
                if span_id:
                    out["cited_span_ids"].append(span_id)

    try:
        raw = call_chat(_ascii_safe(SYSTEM_PROMPT), _ascii_safe(user_prompt), timeout_sec=llm_timeout)
        _parse_llm_output(raw)
    except Exception as e:
        err_str = str(e)
        # 400 Bad Request is often caused by overlong request/context; retry once with fewer RAG excerpts
        if ("400" in err_str or "Bad Request" in err_str) and rag_spans and len(rag_spans) > 6:
            rag_block_short = "\n".join(
                f"- [span_id={s.span_id or ''}] [{s.metadata.issuing_body}, {s.metadata.publication_date}] {(s.text or '')[:RAG_EXCERPT_CHARS]}{'...' if len(s.text or '') > RAG_EXCERPT_CHARS else ''}"
                for s in rag_spans[:6]
            )
            user_prompt_short = f"""User criteria (use these when assessing news value and angle):
{chr(10).join(structured)}

## Web search results (use these for the news hook: events, data, social posts)
{web_block}

## Knowledge base excerpts (policy/background — first 6 only; use to frame the story)
{rag_block_short}

Produce the JSON. The pitch should be driven by events from the web results; use knowledge base only as context. Respect the user's timeframe and target audience. Do not invent dates."""
            try:
                logger.info("Reactive pitch: retrying LLM with shorter context (6 excerpts) after 400")
                raw = call_chat(_ascii_safe(SYSTEM_PROMPT), _ascii_safe(user_prompt_short), timeout_sec=llm_timeout)
                _parse_llm_output(raw)
            except Exception as e2:
                out["error"] = _ascii_safe(str(e))
        else:
            out["error"] = _ascii_safe(str(e))
    return out
