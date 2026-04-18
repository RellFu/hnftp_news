"""
Policy document data models

Per design doc sections 2.3 and 3.1:
- Document metadata: issuing body, publication date, jurisdiction, document type,
  language, stable source identifier
- Corpus from Hainan Free Trade Port official policies, laws, and authoritative interpretations
"""

from datetime import date
from typing import Optional, Union

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Document metadata"""

    issuing_body: str = Field(..., description="Issuing body")
    publication_date: Union[date, str] = Field(..., description="Publication date")
    source_identifier: str = Field(..., description="Stable source identifier")
    jurisdiction: Optional[str] = Field(None, description="Jurisdiction")
    document_type: Optional[str] = Field(
        None,
        description="Document type, e.g. law/regulation/official_release",
    )
    language: Optional[str] = Field(None, description="Language")


class PolicyDocument(BaseModel):
    """Policy document"""

    id: str = Field(..., description="Unique document ID")
    title: Optional[str] = Field(None, description="Document title")
    content: str = Field(..., description="Full document content")
    metadata: DocumentMetadata = Field(..., description="Metadata")
    chunk_index: Optional[int] = Field(
        None,
        description="Chunk index if this is a chunked span",
    )


class EvidenceSpan(BaseModel):
    """Retrievable evidence span (chunked)"""

    span_id: str = Field(..., description="Unique span identifier")
    text: str = Field(..., description="Span text")
    document_id: str = Field(..., description="Parent document ID")
    metadata: DocumentMetadata = Field(..., description="Metadata inherited from document")
    reranker_score: Optional[float] = Field(None, description="Reranker score")


class RetrievalResult(BaseModel):
    """Retrieval result"""

    spans: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Retrieved evidence spans, sorted by score",
    )
    evidence_sufficient: bool = Field(
        ...,
        description="Whether evidence is sufficient (max rerank score >= 0.35)",
    )
    downgrade_reason: Optional[str] = Field(
        None,
        description="When insufficient: low_relevance / no_authoritative_source_found / missing_provenance_metadata",
    )
