"""
Active retrieval: web search + RAG knowledge base + LLM -> multiple pitch suggestions (same idea as passive: web + RAG).
Output language: English. When citing a source, keep the source title as-is (e.g. Chinese title if original is Chinese).
"""

import logging
from typing import Any

from app.core.config import llm_available
from app.services.llm_client import call_chat, extract_json_from_response

logger = logging.getLogger(__name__)

ACTIVE_SYSTEM = """You are a news editor covering Hainan and the Free Trade Port. You will receive:
1) Recent web search results (titles and snippets) spanning policy, tourism, culture, ecology, sports, livelihood, etc.
2) Excerpts from our curated knowledge base (Hainan Free Trade Port policies, official sources). Use these to ground your pitches in policy and facts where relevant.

Output language: English only for all fields below. Exception: when you quote or cite a source, keep the source's original title (e.g. if the source title is in Chinese, keep it in Chinese in the citation).

Your task: From the combined web and knowledge-base evidence, identify 3 to 5 DISTINCT news topics that together reflect DIVERSITY. Do not pick only policy; include a mix where possible (e.g. policy, tourism, culture, ecology, sports, or livelihood). For EACH topic output:
1) theme: Exactly ONE of: policy, tourism, culture, ecology, sports, livelihood, other. Use lowercase. This labels the topic for a colored tag.
2) title: A SHORT, concise card title in English (one phrase, under 30 characters). Examples: "Resort opening in Sanya", "FTP tax policy update", "Coastal ecology initiative", "Marathon 2025", "Local livelihood survey". Do NOT use a long sentence.
3) news_value_assessment: 2-4 sentences in English on timeliness and relevance.
4) proposed_angle: One clear sentence in English for the story angle.
5) pitch_plan: 3-5 bullet points in English (key questions, stakeholders to contact, suggested structure).

Respond with a single JSON object only, no markdown:
{
  "pitches": [
    {
      "theme": "policy",
      "title": "short title here",
      "news_value_assessment": "...",
      "proposed_angle": "...",
      "pitch_plan": "bullet1\\nbullet2\\n..."
    }
  ]
}
"""


def _str_clean(s: Any) -> str:
    if s is None:
        return ""
    if isinstance(s, str):
        return s.strip()
    if isinstance(s, list):
        return "\n".join(_str_clean(x) for x in s if _str_clean(x))
    return str(s).strip()


def _get_field(p: dict, *keys: str) -> str:
    """Get first non-empty string from pitch dict using any of the given keys (handles LLM key variation)."""
    for k in keys:
        v = p.get(k)
        if v is None:
            continue
        cleaned = _str_clean(v)
        if cleaned:
            return cleaned
    return ""


def run_active_pitch(
    web_results: list[dict],
    rag_excerpts: list[dict] | None = None,
    timeout_sec: int | None = None,
) -> list[dict[str, Any]]:
    """Call LLM on web results + optional RAG excerpts; return list of pitch dicts. Preserve UTF-8 (no ASCII-only stripping). timeout_sec caps the LLM call (e.g. for request-level 60s hard timeout)."""
    if not web_results:
        return []
    if not llm_available():
        logger.warning("Active pitch: LLM not configured, skipping.")
        return []

    web_block = "\n".join(
        f"- [{r.get('title', '')}] {r.get('snippet', '')} (Source: {r.get('link', '')})"
        for r in web_results[:24]
    )
    RAG_EXCERPT_CHARS = 550
    rag_block = "No knowledge base excerpts provided."
    if rag_excerpts:
        rag_block = "\n".join(
            f"- [{e.get('issuing_body', '')}, {e.get('publication_date', '')}] {(e.get('text') or '')[:RAG_EXCERPT_CHARS]}{'...' if len(e.get('text') or '') > RAG_EXCERPT_CHARS else ''}"
            for e in rag_excerpts
        )
    user_prompt = f"""Recent web search results (Hainan / FTP, multiple themes: policy, tourism, culture, ecology, sports, livelihood, etc.):

{web_block}

## Knowledge base excerpts (Hainan FTP policies, official sources)

{rag_block}

Produce the JSON object with key "pitches" containing 3 to 5 pitch objects. Each object MUST include: theme (one of: policy, tourism, culture, ecology, sports, livelihood, other), title, news_value_assessment, proposed_angle, pitch_plan. Use both web and knowledge-base evidence where relevant. Prefer a diverse mix of themes."""

    try:
        raw = call_chat(ACTIVE_SYSTEM, user_prompt, timeout_sec=timeout_sec if timeout_sec is not None else 90, ascii_safe_user=False)
        data = extract_json_from_response(raw)
        pitches = data.get("pitches") or data.get("pitch_suggestions") or []
        if not isinstance(pitches, list):
            return []
        out = []
        allowed_themes = {"policy", "tourism", "culture", "ecology", "sports", "livelihood", "other"}
        for i, p in enumerate(pitches[:10]):
            if not isinstance(p, dict):
                continue
            raw_theme = _str_clean(p.get("theme")).lower()
            theme = raw_theme if raw_theme in allowed_themes else "other"
            raw_title = _str_clean(p.get("title"))[:80]
            out.append({
                "theme": theme,
                "title": raw_title if raw_title else None,
                "news_value_assessment": _get_field(p, "news_value_assessment", "newsValueAssessment", "news value assessment"),
                "proposed_angle": _get_field(p, "proposed_angle", "proposedAngle", "proposed angle"),
                "pitch_plan": _get_field(p, "pitch_plan", "pitchPlan", "pitch plan"),
            })
        logger.info("Active pitch: LLM returned %s suggestions", len(out))
        return out
    except Exception as e:
        logger.warning("Active pitch LLM failed: %s", e, exc_info=True)
        return []
