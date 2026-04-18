"""
Downgrade handling module

Evidence insufficient when:
- After hybrid retrieval + reranking (top k=5)
- No allowlisted authoritative issuer achieves reranker score >= 0.35

Downgrade behaviour:
- Rewrite affected fields in non-assertive form
- Label reason: low_relevance | no_authoritative_source_found | missing_provenance_metadata
"""
