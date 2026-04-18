"""Pitch API schemas.

Evidence status values (see evaluation/codebook/evidence_categories_and_downgrade.md):
- sufficient: retrieval met threshold; claims can be supported.
- insufficient: retrieval below threshold or no spans; do not assert.
- unsupported: no span entails this claim (per-claim).
- contradictory: a span contradicts this claim (per-claim).
- error: retrieval failed (exception); graceful degradation.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Evidence status for API responses; used for downgrade mechanism.
EvidenceStatus = Literal["sufficient", "insufficient", "unsupported", "contradictory", "error"]


class RetrievalRequest(BaseModel):
    """Retrieval request."""

    query: str
    top_k: Optional[int] = None
    timeframe: Optional[str] = None
    issuing_body: Optional[str] = None


class EvidenceSpanOut(BaseModel):
    """Evidence span for API response."""

    span_id: str
    text: str
    document_id: str
    issuing_body: str
    publication_date: str
    source_identifier: str
    reranker_score: Optional[float] = None


class RetrievalResponse(BaseModel):
    """Retrieval response. Uses evidence_status for downgrade mechanism."""

    spans: list[EvidenceSpanOut]
    evidence_sufficient: bool
    evidence_status: EvidenceStatus = "sufficient"
    downgrade_reason: Optional[str] = None
    downgrade_message: Optional[str] = None
    request_id: Optional[str] = None


class GenerateRequest(BaseModel):
    """Generate pitch request."""

    query: str
    beat: Optional[str] = None
    timeframe: Optional[str] = None
    issuing_body: Optional[str] = None


class ClaimFieldOut(BaseModel):
    """Claim field for API response. evidence_status: supported | unsupported | contradictory | insufficient."""

    field_name: str
    claim: str
    evidence_span_ids: list[str] = Field(default_factory=list)
    is_downgraded: bool = False
    evidence_status: Optional[EvidenceStatus] = None
    downgrade_reason: Optional[str] = None


class PitchDraftOut(BaseModel):
    """Pitch draft for API response."""

    proposed_angle: str
    why_it_matters_now: str
    key_questions: list[str]
    key_stakeholders: list[str]
    claim_fields: list[ClaimFieldOut] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    """Generate pitch response."""

    pitch: PitchDraftOut
    evidence_spans: list[EvidenceSpanOut]
    evidence_sufficient: bool
    evidence_status: Optional[EvidenceStatus] = None
    downgrade_message: Optional[str] = None
    request_id: Optional[str] = None


class ValidateRequest(BaseModel):
    """Reactive validation request."""

    draft_text: str
    constraints: Optional[dict] = None


class ValidatedSegment(BaseModel):
    """Validated segment (anchored or downgraded)."""

    type: str  # anchored | downgraded | plain
    text: str
    evidence_span: Optional[EvidenceSpanOut] = None
    downgrade_reason: Optional[str] = None


class ValidateResponse(BaseModel):
    """Validate draft response."""

    segments: list[ValidatedSegment]
    request_id: Optional[str] = None


class ReactivePitchRequest(BaseModel):
    """Reactive workflow: structured params for precise retrieval; topic kept for backward compat."""

    topic: Optional[str] = None
    beat: Optional[str] = None
    timeframe_start: Optional[str] = None
    timeframe_end: Optional[str] = None
    issuing_body_preference: Optional[list[str]] = None
    target_audience: Optional[str] = None


class WebSourceOut(BaseModel):
    title: Optional[str] = None
    link: Optional[str] = None
    snippet: Optional[str] = None


class PitchSuggestionOut(BaseModel):
    """Single pitch suggestion (same shape as passive; title and theme are LLM-generated)."""

    theme: Optional[str] = None
    title: Optional[str] = None
    news_value_assessment: str = ""
    proposed_angle: str = ""
    pitch_plan: str = ""


class RagExcerptOut(BaseModel):
    """Single RAG knowledge-base excerpt for trace (with span_id for claim–span binding)."""

    span_id: str = ""
    issuing_body: str = ""
    publication_date: str = ""
    source_identifier: str = ""
    text: str = ""


class ActiveSearchResponse(BaseModel):
    """Active retrieval: web search + RAG + LLM yields multiple pitch suggestions."""

    query_used: str = ""
    results: list[WebSourceOut] = Field(default_factory=list)
    pitches: list[PitchSuggestionOut] = Field(default_factory=list)
    rag_used: bool = False
    rag_excerpts: list[RagExcerptOut] = Field(default_factory=list)
    rag_error: Optional[str] = None
    evidence_status: Optional[EvidenceStatus] = None
    downgrade_message: Optional[str] = None
    error: Optional[str] = None
    timeout: Optional[bool] = None


class CitedSourceOut(BaseModel):
    """One policy source cited by the LLM (issuing body + date + snippet); span_id links to RAG excerpt when provided and validated)."""

    issuing_body: str = ""
    publication_date: str = ""
    snippet: str = ""
    span_id: Optional[str] = None


class ReactivePitchResponse(BaseModel):
    """Reactive workflow output: news value assessment, angle, pitch plan."""

    news_value_assessment: str = ""
    proposed_angle: str = ""
    pitch_plan: str = ""
    cited_sources: list[CitedSourceOut] = Field(default_factory=list, description="Policy sources cited by the LLM (issuing body, date, snippet, optional span_id)")
    cited_span_ids: list[str] = Field(default_factory=list, description="Validated span_ids from cited_sources (subset of retrieval_span_ids)")
    web_sources: list[WebSourceOut] = Field(default_factory=list)
    rag_excerpts: list[RagExcerptOut] = Field(default_factory=list)
    rag_used: bool = False
    rag_error: Optional[str] = None
    evidence_status: Optional[EvidenceStatus] = None
    downgrade_message: Optional[str] = None
    error: Optional[str] = None
    web_search_error: Optional[str] = None
    request_id: Optional[str] = None
    timeout: Optional[bool] = None
    issuing_body_preference: list[str] = Field(default_factory=list)
    issuing_body_preference_matched_spans: int = 0
    issuing_body_preference_fallback: Optional[bool] = None