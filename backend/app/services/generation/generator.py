"""
Pitch draft generator

- System prompt: require LLM to produce structured pitch with evidence ID citations
- Downgrade logic: when evidence insufficient, rewrite fields in non-assertive form and note lack of authoritative sources
- Optional LLM: when LLM_API_KEY is set, calls OpenAI-compatible API; otherwise use deterministic fallback.
"""

import json
import re
from typing import Optional

from app.models import EvidenceSpan, RetrievalResult

# Replace non-ASCII with ? so no .encode() is needed (avoids ascii codec errors in some envs)
def _ascii_safe(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"[^\x00-\x7F]+", "?", s)


SYSTEM_PROMPT = """You are a news pitch assistant for policy reporting on the Hainan Free Trade Port. Your task is to generate structured pitch drafts that journalists can use as a starting point for story development.

## Output structure

Generate a pitch with the following fields. Each **claim-bearing field** (fields that make factual assertions) MUST cite at least one evidence span ID from the provided evidence. Use the format [EVIDENCE_ID: span_id] inline where the claim is supported.

Claim-bearing fields:
- **proposed_angle**: The story angle. Cite evidence IDs for any factual claims about policies, dates, or official positions.
- **why_it_matters_now**: Why this story is timely. Cite evidence IDs for timeliness claims.
- **key_questions**: 2–4 questions to guide reporting. For questions that imply a factual premise, cite the supporting evidence ID.
- **key_stakeholders**: Parties affected or involved. Cite evidence IDs for claims about who is affected.

Output format (JSON):
```json
{
  "proposed_angle": "Your angle text [EVIDENCE_ID: span_id_example_1]",
  "why_it_matters_now": "Your timeliness text [EVIDENCE_ID: span_id_example_2]",
  "key_questions": ["Question 1 [EVIDENCE_ID: span_id_example_3]", "Question 2"],
  "key_stakeholders": ["Stakeholder 1 [EVIDENCE_ID: span_id_example_4]"],
  "claim_field_references": {
    "proposed_angle": ["span_id_1", "span_id_2"],
    "why_it_matters_now": ["span_id_3"],
    "key_questions": ["span_id_4"],
    "key_stakeholders": ["span_id_5"]
  }
}
```

The `claim_field_references` object must list, for each claim-bearing field, all evidence span IDs that support that field. Every cited span_id must appear in the provided evidence.

## Downgrade logic (EVIDENCE INSUFFICIENT)

If the evidence is marked as **INSUFFICIENT** (evidence_sufficient=false), you MUST:

1. **Rewrite all claim-bearing fields in non-assertive form.** Use hedging language such as:
   - "may", "might", "possibly", "could"
   - "is reported to", "appears to", "suggests"
   - "yet to be observed", "remains to be confirmed"
   - "according to some accounts" (when no authoritative source is available)

2. **Do NOT make definitive factual claims** without authoritative evidence. Avoid phrases like "the policy states", "it is certain", "has been confirmed".

3. **Add an explicit note** at the end of the pitch: `[Downgrade reason: lack of authoritative sources]`

4. **Do NOT invent or fabricate** policy details, dates, or stakeholder roles. If evidence is insufficient, frame everything as tentative or speculative.

5. You may still use the provided evidence spans as context, but clearly signal that they do not meet the threshold for authoritative attribution. Do not cite them as [EVIDENCE_ID] in claim-bearing fields when evidence is insufficient—instead, note in the field that "further verification from authoritative sources is needed".

## When evidence IS sufficient

When evidence_sufficient=true, write in assertive form and cite evidence IDs as specified above. All claims must be grounded in the provided evidence spans.
"""


DOWNGRADE_USER_ADDENDUM = """

---

**IMPORTANT: Evidence has been marked as INSUFFICIENT.**

You MUST apply the downgrade logic: rewrite all claim-bearing fields in non-assertive form and add [Downgrade reason: lack of authoritative sources]. Do not make definitive factual claims.
"""


def _format_evidence_for_prompt(spans: list[EvidenceSpan]) -> str:
    """Format evidence spans for inclusion in the prompt."""
    lines = []
    for s in spans:
        lines.append(
            f"- [span_id={s.span_id}] (issuing_body={s.metadata.issuing_body}, date={s.metadata.publication_date})"
        )
        lines.append(f"  {s.text[:500]}{'...' if len(s.text) > 500 else ''}")
    return "\n".join(lines) if lines else "(No evidence spans provided)"


def build_generation_prompt(
    user_query: str,
    retrieval_result: RetrievalResult,
    beat: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> tuple[str, str]:
    """
    Build system and user prompts for generation.

    Returns:
        (system_prompt, user_prompt)
    """
    system = SYSTEM_PROMPT

    evidence_block = _format_evidence_for_prompt(retrieval_result.spans)
    evidence_status = (
        "INSUFFICIENT" if not retrieval_result.evidence_sufficient else "SUFFICIENT"
    )
    downgrade_reason = retrieval_result.downgrade_reason or ""

    user_parts = [
        f"## User request\n{user_query}",
        "",
        "## Evidence spans",
        evidence_block,
        "",
        f"## Evidence status: {evidence_status}",
    ]
    if not retrieval_result.evidence_sufficient:
        user_parts.append(f"Downgrade reason (system): {downgrade_reason}")
        user_parts.append(DOWNGRADE_USER_ADDENDUM)
    else:
        user_parts.append(
            "Cite the span_ids above in your claim-bearing fields as [EVIDENCE_ID: span_id]."
        )

    if beat:
        user_parts.append(f"\n## Beat / theme: {beat}")
    if timeframe:
        user_parts.append(f"## Timeframe constraint: {timeframe}")

    user_parts.append("\nGenerate the structured pitch draft in JSON format.")
    user_prompt = "\n".join(user_parts)
    return system, user_prompt


def generate_pitch(
    user_query: str,
    retrieval_result: RetrievalResult,
    beat: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> str:
    """
    Generate pitch draft (prompt preview utility; actual LLM call via generate_pitch_with_llm).
    """
    system, user = build_generation_prompt(user_query, retrieval_result, beat, timeframe)
    return f"[System]\n{system}\n\n[User]\n{user}"


def generate_pitch_with_llm(
    user_query: str,
    retrieval_result: RetrievalResult,
    beat: Optional[str] = None,
    timeframe: Optional[str] = None,
):
    """
    Call LLM to generate structured pitch; parse JSON into PitchDraftOut.
    Returns (PitchDraftOut, None) on success, (None, error_message) on failure.
    """
    from app.core.config import llm_available
    from app.services.llm_client import call_chat, extract_json_from_response
    from app.schemas.pitch import PitchDraftOut, ClaimFieldOut

    if not llm_available():
        return None, "LLM not configured (set LLM_API_KEY or OPENAI_API_KEY)"

    system, user = build_generation_prompt(user_query, retrieval_result, beat, timeframe)
    # Strip non-ASCII via regex (no .encode() call) so no ascii codec error can occur
    system = _ascii_safe(system)
    user = _ascii_safe(user)
    try:
        raw = call_chat(system, user)
    except Exception as e:
        return None, _ascii_safe(str(e))

    try:
        data = extract_json_from_response(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return None, _ascii_safe(f"LLM output not valid JSON: {e}")

    def get_list(obj: dict, key: str, default=None):
        v = obj.get(key, default)
        return v if isinstance(v, list) else (default or [])

    def get_str(obj: dict, key: str, default: str = ""):
        v = obj.get(key, default)
        return str(v).strip() if v is not None else default

    proposed_angle = _ascii_safe(get_str(data, "proposed_angle", ""))
    why_it_matters_now = _ascii_safe(get_str(data, "why_it_matters_now", ""))
    key_questions = [_ascii_safe(str(q)) for q in get_list(data, "key_questions", [])]
    key_stakeholders = [_ascii_safe(str(s)) for s in get_list(data, "key_stakeholders", [])]
    refs = data.get("claim_field_references") or {}

    is_downgraded = not retrieval_result.evidence_sufficient
    reason = "lack of authoritative sources" if is_downgraded else None
    claim_evidence_status = "insufficient" if is_downgraded else "supported"

    claim_fields = [
        ClaimFieldOut(
            field_name="proposed_angle",
            claim=proposed_angle,
            evidence_span_ids=refs.get("proposed_angle", []),
            is_downgraded=is_downgraded,
            evidence_status=claim_evidence_status,
            downgrade_reason=reason,
        ),
        ClaimFieldOut(
            field_name="why_it_matters_now",
            claim=why_it_matters_now,
            evidence_span_ids=refs.get("why_it_matters_now", []),
            is_downgraded=is_downgraded,
            evidence_status=claim_evidence_status,
            downgrade_reason=reason,
        ),
        ClaimFieldOut(
            field_name="key_questions",
            claim="\n".join(key_questions) if key_questions else "",
            evidence_span_ids=refs.get("key_questions", []),
            is_downgraded=is_downgraded,
            evidence_status=claim_evidence_status,
            downgrade_reason=reason,
        ),
        ClaimFieldOut(
            field_name="key_stakeholders",
            claim=", ".join(key_stakeholders) if key_stakeholders else "",
            evidence_span_ids=refs.get("key_stakeholders", []),
            is_downgraded=is_downgraded,
            evidence_status=claim_evidence_status,
            downgrade_reason=reason,
        ),
    ]

    pitch = PitchDraftOut(
        proposed_angle=proposed_angle,
        why_it_matters_now=why_it_matters_now,
        key_questions=key_questions,
        key_stakeholders=key_stakeholders,
        claim_fields=claim_fields,
    )
    return pitch, None
