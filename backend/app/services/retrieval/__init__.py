"""
Retrieval module: hybrid (lexical + vector) retrieval and reranking
top k = 5

Core: when max rerank score < 0.35, mark as evidence insufficient
"""

from .retrieval import (
    hybrid_retrieve,
    lexical_search,
    rerank,
    vector_search,
)

__all__ = [
    "hybrid_retrieve",
    "lexical_search",
    "vector_search",
    "rerank",
]
