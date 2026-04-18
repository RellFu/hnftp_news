"""
Hybrid retrieval module: lexical + vector retrieval, reranking, reranker threshold check.

Design doc 2.3/3.1: hybrid retrieval + reranking (top k=5), evidence insufficient when max rerank
score < RERANKER_THRESHOLD.

This implementation wires:
- Lexical search via BM25 (rank-bm25)
- Vector search via sentence-transformers (all-MiniLM-L6-v2 by default)
- Rerank as a simple sort on per-span reranker_score (already normalized to [0, 1])

If optional dependencies (rank-bm25, sentence-transformers) are missing or chunks index is
empty, the module gracefully falls back to the internal keyword-based fallback retrieval.
"""

import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, List

import numpy as np

from app.core.config import EMBEDDING_MODEL_NAME, RERANKER_THRESHOLD, TOP_K
from app.models import DocumentMetadata, EvidenceSpan, RetrievalResult

logger = logging.getLogger(__name__)

try:  # Optional; if missing we degrade to fallback retrieval
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover - dependency wiring
    BM25Okapi = None  # type: ignore[assignment]

try:  # Optional; if missing we degrade to fallback retrieval
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - dependency wiring
    SentenceTransformer = None  # type: ignore[assignment]

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
except ImportError:
    _CrossEncoder = None  # type: ignore[assignment,misc]

# Data lives in repo root (news/data), not backend/data
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
PROJECT_ROOT = _BACKEND_DIR.parent if _BACKEND_DIR.name == "backend" else _BACKEND_DIR
DATA_DIR = PROJECT_ROOT / "data"
METADATA_PATH = DATA_DIR / "metadata.json"
CHUNKS_INDEX = DATA_DIR / "chunks" / "chunks_index.json"
EMBEDDINGS_DIR = DATA_DIR / "chunks" / "embeddings"

# Lazy-loaded in vector_search(); used by is_retrieval_warm() to detect cold start
_VEC_MODEL = None  # type: ignore[assignment]
_VEC_EMB = None  # type: ignore[assignment]
_VEC_IDS: list = []  # type: ignore[assignment]

# Cross-encoder reranker: model name from env, empty = disable (fall back to score sort only)
CROSS_ENCODER_MODEL: Optional[str] = (os.environ.get("RAG_CROSS_ENCODER_MODEL") or "cross-encoder/ms-marco-MiniLM-L-6-v2").strip() or None
RERANK_CANDIDATES = 30  # how many candidates to rescore with cross-encoder before taking top_k
MAX_TEXT_FOR_CROSS_ENCODER = 500  # truncate span text to avoid token limit

# Authoritative issuer allowlist (configurable). Only spans from listed issuers count for sufficiency.
AUTHORITATIVE_ISSUERS: set[str] = frozenset()

# Keywords for evidence sufficiency (Hainan FTP domain)
DOMAIN_KEYWORDS = (
    "hainan",
    "ftp",
    "free trade",
    "policy",
    "自贸",
    "customs",
    "tariff",
    "lingshui",
    "陵水",
    "haikou",
    "sanya",
    "tax",
    "investment",
    "tourism",
    "ecology",
    "sports",
    "livelihood",
    "旅游",
    "生态",
    "体育",
    "民生",
)

# Bilingual synonym map: English query terms -> Chinese terms for matching policy text.
# Covers Trade / Tourism / Customs / Travel / Culture / Ecology / Sports / Livelihood.
_EN_ZH_SYNONYMS: dict[str, list[str]] = {
    "tax": ["税", "税收", "个税", "所得税", "税务"],
    "tariff": ["关税", "零关税", "免税"],
    "customs": ["海关", "通关"],
    "duty": ["关税", "税费"],
    "tourism": ["旅游", "文旅", "景区", "游客"],
    "travel": ["旅游", "出行", "旅行", "航线"],
    "culture": ["文化", "文旅", "非遗"],
    "ecology": ["生态", "环保", "环境", "绿色", "低碳"],
    "sports": ["体育", "赛事", "运动"],
    "livelihood": ["民生", "就业", "社保", "医疗", "养老", "教育"],
    "employment": ["就业", "招聘", "人才"],
    "health": ["医疗", "卫生", "健康", "卫健"],
    "education": ["教育", "学校"],
    "investment": ["投资", "招商", "引资"],
    "talent": ["人才", "引进", "落户"],
    "trade": ["贸易", "进出口", "商务"],
    "business": ["商务", "企业", "营商"],
    "environment": ["环境", "生态", "环保", "营商环境"],
}

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\-\u4e00-\u9fff]{2,}")


def _extract_topic_terms(raw_topic: Optional[str]) -> set[str]:
    """
    Extract user-specific topic terms (excluding generic Hainan/FTP domain keywords).

    Used to decide whether retrieved evidence is truly related to the user's topic/beat,
    not just broadly in the Hainan FTP domain.
    """
    if not raw_topic:
        return set()
    tokens = _TOKEN_PATTERN.findall(raw_topic.lower())
    if not tokens:
        return set()
    domain_terms = {kw.lower() for kw in DOMAIN_KEYWORDS}
    # Keep only tokens that are not generic domain keywords
    return {t for t in tokens if t not in domain_terms}


def expand_query_for_retrieval(query: str) -> str:
    """
    Lightweight query expansion for first-stage retrieval (BM25/vector): add Chinese synonyms
    and optional Hainan scope so English queries pull more relevant policy text.
    Original query is still used for cross-encoder and display.
    """
    if not query or not query.strip():
        return query
    q = query.strip()
    qlower = q.lower()
    extra: list[str] = []
    # Add Chinese synonyms for English terms in query
    words = _TOKEN_PATTERN.findall(qlower)
    for w in words:
        syns = _EN_ZH_SYNONYMS.get(w)
        if syns:
            extra.extend(syns)
    if "free trade port" in qlower or "ftp" in qlower:
        extra.extend(["自由贸易港", "自贸港", "海南自由贸易港"])
    # Optional: add Hainan scope if not present (avoid diluting very specific queries)
    if "hainan" not in qlower and "海南" not in q and "自贸" not in q:
        extra.extend(["Hainan", "海南"])
    if not extra:
        return q
    seen: set[str] = set()
    unique_extra: list[str] = []
    for x in extra:
        if x and x not in seen:
            seen.add(x)
            unique_extra.append(x)
    return (q + " " + " ".join(unique_extra)).strip()


def _tokenize(text: str) -> List[str]:
    """Simple tokenizer for BM25 and bag-of-words style models."""
    if not text:
        return []
    return _TOKEN_PATTERN.findall(text.lower())


@lru_cache(maxsize=1)
def _load_chunks() -> list[dict]:
    """Load chunks from chunks_index.json for richer retrieval (cached)."""
    if not CHUNKS_INDEX.exists():
        return []
    try:
        data = json.loads(CHUNKS_INDEX.read_text(encoding="utf-8"))
        return data.get("chunks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _load_corpus_metadata() -> list[dict]:
    """Load corpus metadata for fallback retrieval."""
    if not METADATA_PATH.exists():
        return []
    try:
        data = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        return data.get("documents", [])
    except (json.JSONDecodeError, OSError):
        return []


def is_retrieval_warm() -> bool:
    """
    True if embedding model and chunk embeddings are already loaded (not cold start).
    Used by API layer: cold start -> no request timeout; warm -> 60s limit.
    """
    if not CHUNKS_INDEX.exists():
        return True
    return _VEC_EMB is not None  # type: ignore[truthy-function]


def _parse_date(s: str) -> str:
    """Normalize date string to YYYY-MM-DD for comparison; return empty if invalid."""
    if not s or not isinstance(s, str):
        return ""
    s = s.strip()[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s
    return ""


def _fallback_spans_from_corpus(
    query: str,
    top_k: int,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    issuing_bodies: Optional[list[str]] = None,
) -> list[EvidenceSpan]:
    """Return spans from chunks with keyword scoring; optional metadata filters (date range, issuing body)."""
    chunks = _load_chunks()
    qlower = query.lower()
    qwords = set(w for w in qlower.split() if len(w) > 1)
    has_domain = any(kw in qlower for kw in DOMAIN_KEYWORDS)

    # Expand English domain terms into a few Chinese synonyms so that
    # English-only queries can still retrieve Chinese-only policy text.
    zh_synonyms: set[str] = set()
    for w in qwords:
        syns = _EN_ZH_SYNONYMS.get(w)
        if syns:
            zh_synonyms.update(syns)
    if "free trade port" in qlower or "ftp" in qlower:
        zh_synonyms.update({"自由贸易港", "自贸港", "海南自由贸易港", "海南自贸港"})

    # Optional metadata filters
    want_issuing = frozenset((b or "").strip() for b in (issuing_bodies or []) if (b or "").strip())
    d_start = _parse_date(date_start) if date_start else ""
    d_end = _parse_date(date_end) if date_end else ""

    def _chunk_passes(c: dict) -> bool:
        pub = _parse_date(str(c.get("publication_date", "")))
        if d_start and pub and pub < d_start:
            return False
        if d_end and pub and pub > d_end:
            return False
        if want_issuing:
            ib = (c.get("issuing_body") or "").strip()
            if ib not in want_issuing:
                return False
        return True

    if chunks:
        filtered = [c for c in chunks if _chunk_passes(c)] if (d_start or d_end or want_issuing) else chunks
        # Score chunks by keyword overlap (including simple bilingual synonyms);
        # prefer chunks with query words and domain match.
        scored = []
        for c in filtered:
            text = (c.get("text") or "").lower()
            overlap = 0
            if qwords:
                overlap += sum(1 for w in qwords if w in text)
            if zh_synonyms:
                overlap += sum(1 for z in zh_synonyms if z in text)
            domain_match = 1 if has_domain else 0
            rel_score = min(0.95, 0.35 + 0.12 * overlap + 0.2 * domain_match)
            scored.append((rel_score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = []
        for score, c in scored[:top_k]:
            meta = DocumentMetadata(
                issuing_body=c.get("issuing_body", "Unknown"),
                publication_date=c.get("publication_date", "2024-01-01"),
                source_identifier=c.get("document_id", c.get("span_id", "")[:16]),
            )
            raw_text = c.get("text", "")
            text = raw_text[:400] + "..." if len(raw_text) > 400 else raw_text
            if not text.strip():
                text = f"Policy excerpt from {meta.issuing_body}"
            result.append(
                EvidenceSpan(
                    span_id=c.get("span_id", "")[:24],
                    text=text,
                    document_id=c.get("document_id", ""),
                    metadata=meta,
                    reranker_score=score,
                )
            )
        return result

    # Fallback to metadata-only
    docs = _load_corpus_metadata()
    if not docs:
        return []
    doc_list = [d for d in docs if _chunk_passes(d)] if (d_start or d_end or want_issuing) else docs
    score = 0.45 if has_domain else 0.25
    spans = []
    for i, doc in enumerate(doc_list[:top_k]):
        meta = DocumentMetadata(
            issuing_body=doc.get("issuing_body", "Unknown"),
            publication_date=doc.get("publication_date", "2024-01-01"),
            source_identifier=doc.get("source_identifier", f"doc-{i}"),
        )
        title = doc.get("title", "Untitled")
        sid = doc.get("source_identifier", f"span-{i}")[:16]
        spans.append(
            EvidenceSpan(
                span_id=sid,
                text=f"[Excerpt] {title}: Policy document from {meta.issuing_body}.",
                document_id=sid,
                metadata=meta,
                reranker_score=score,
            )
        )
    return spans


def lexical_search(query: str, top_n: int = TOP_K * 2) -> list[EvidenceSpan]:
    """
    Lexical search via BM25 over span texts.

    - Builds a BM25 index lazily on first call using chunks_index.json
    - Returns EvidenceSpan with reranker_score in [0, 1] (BM25 score normalized by max score)
    """
    chunks = _load_chunks()
    if not chunks or BM25Okapi is None:
        # Fallback: let hybrid_retrieve decide whether to use fallback corpus channel
        if BM25Okapi is None:
            logger.debug("BM25Okapi not available; lexical_search will return no results.")
        return []

    texts = [str(c.get("text") or "") for c in chunks]
    tokenized_corpus = [_tokenize(t) for t in texts]
    if not any(tokenized_corpus):
        return []

    bm25 = BM25Okapi(tokenized_corpus)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)
    if not isinstance(scores, np.ndarray):
        scores = np.array(scores, dtype=float)
    if scores.size == 0:
        return []

    top_n = min(top_n, len(chunks))
    top_idx = np.argsort(scores)[::-1][:top_n]
    max_score = float(scores[top_idx[0]]) if top_idx.size else 0.0
    denom = max(max_score, 1e-6)

    spans: list[EvidenceSpan] = []
    for i in top_idx:
        c = chunks[int(i)]
        meta = DocumentMetadata(
            issuing_body=c.get("issuing_body", "Unknown"),
            publication_date=c.get("publication_date", "2024-01-01"),
            source_identifier=c.get("document_id", c.get("span_id", "")[:16]),
        )
        raw_text = c.get("text", "")
        text = raw_text[:400] + "..." if len(raw_text) > 400 else raw_text
        if not text.strip():
            text = f"Policy excerpt from {meta.issuing_body}"
        norm_score = float(scores[int(i)]) / denom if denom > 0 else 0.0
        spans.append(
            EvidenceSpan(
                span_id=c.get("span_id", "")[:24],
                text=text,
                document_id=c.get("document_id", ""),
                metadata=meta,
                reranker_score=max(0.0, min(1.0, norm_score)),
            )
        )
    return spans


def _embedding_cache_path(model_name: str) -> Path:
    """
    Build a safe on-disk path for cached chunk embeddings for a given model.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)
    return EMBEDDINGS_DIR / f"{safe}.npz"


def _load_or_build_embeddings_for_chunks(model_name: str, chunks: list[dict]) -> None:
    """
    Ensure _VEC_MODEL, _VEC_EMB and _VEC_IDS are populated for the given chunks and model.
    Prefer loading a precomputed embedding cache from disk when available and compatible;
    otherwise encode all chunks and persist embeddings for future cold starts.
    """
    global _VEC_MODEL, _VEC_EMB, _VEC_IDS

    if SentenceTransformer is None:
        return
    if not chunks:
        return

    # Instantiate the model lazily so we can reuse it for queries.
    if _VEC_MODEL is None:  # type: ignore[truthy-function]
        _VEC_MODEL = SentenceTransformer(model_name)  # type: ignore[assignment]

    texts = [str(c.get("text") or "") for c in chunks]
    span_ids = [str(c.get("span_id", "")[:24]) for c in chunks]

    cache_path = _embedding_cache_path(model_name)
    if cache_path.exists():
        try:
            data = np.load(cache_path, allow_pickle=False)
            emb = data["emb"]
            cached_ids_arr = data["span_ids"]
            cached_ids = [str(x) for x in cached_ids_arr.tolist()]
            if len(cached_ids) == len(span_ids) and all(a == b for a, b in zip(cached_ids, span_ids)):
                _VEC_EMB = emb  # type: ignore[assignment]
                _VEC_IDS = cached_ids  # type: ignore[assignment]
                logger.info(
                    "Loaded %s precomputed chunk embeddings from %s",
                    len(span_ids),
                    cache_path,
                )
                return
            logger.info(
                "Embedding cache %s does not match current chunks (span_ids/length); recomputing.",
                cache_path,
            )
        except Exception as e:  # pragma: no cover - defensive logging only
            logger.warning("Failed to load embedding cache %s: %s; will recompute.", cache_path, e)

    # Compute embeddings and persist for future cold starts.
    logger.info(
        "Encoding %s chunks with embedding model %s for vector index...",
        len(texts),
        model_name,
    )
    emb = _VEC_MODEL.encode(texts, convert_to_numpy=True, show_progress_bar=False)  # type: ignore[assignment]
    _VEC_EMB = emb  # type: ignore[assignment]
    _VEC_IDS = span_ids  # type: ignore[assignment]
    try:
        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(cache_path, emb=emb, span_ids=np.asarray(span_ids, dtype="U24"))
        logger.info("Saved precomputed embeddings to %s", cache_path)
    except Exception as e:  # pragma: no cover - defensive logging only
        logger.warning("Failed to save embedding cache to %s: %s", cache_path, e)


def vector_search(query: str, top_n: int = TOP_K * 2) -> list[EvidenceSpan]:
    """
    Vector search via sentence-transformers over span texts.

    - Uses all-MiniLM-L6-v2 by default
    - Embeds all chunks on first call and caches them in-memory
    - Returns EvidenceSpan with reranker_score in [0, 1] (cosine similarity scaled)
    """
    if SentenceTransformer is None:
        logger.debug("SentenceTransformer not available; vector_search will return no results.")
        return []

    chunks = _load_chunks()
    if not chunks:
        return []

    global _VEC_MODEL, _VEC_EMB, _VEC_IDS
    if _VEC_EMB is None or not _VEC_IDS:  # type: ignore[truthy-function]
        _load_or_build_embeddings_for_chunks(EMBEDDING_MODEL_NAME, chunks)

    if _VEC_EMB is None or not _VEC_IDS:  # type: ignore[truthy-function]
        return []

    q_vec = _VEC_MODEL.encode(query, convert_to_numpy=True, show_progress_bar=False)  # type: ignore[assignment]
    if q_vec.ndim == 1:
        q_vec = q_vec[None, :]
    # Cosine similarity
    emb = _VEC_EMB  # type: ignore[assignment]
    q = q_vec[0]
    denom_q = np.linalg.norm(q) or 1e-6
    denom_docs = np.linalg.norm(emb, axis=1)
    sims = (emb @ q) / (denom_docs * denom_q + 1e-6)

    top_n = min(top_n, sims.shape[0])
    top_idx = np.argsort(sims)[::-1][:top_n]
    spans: list[EvidenceSpan] = []
    for i in top_idx:
        c = chunks[int(i)]
        meta = DocumentMetadata(
            issuing_body=c.get("issuing_body", "Unknown"),
            publication_date=c.get("publication_date", "2024-01-01"),
            source_identifier=c.get("document_id", c.get("span_id", "")[:16]),
        )
        raw_text = c.get("text", "")
        text = raw_text[:400] + "..." if len(raw_text) > 400 else raw_text
        if not text.strip():
            text = f"Policy excerpt from {meta.issuing_body}"
        # Normalize sim from [-1,1] to [0,1]
        sim = float(sims[int(i)])
        norm_score = 0.5 * (sim + 1.0)
        spans.append(
            EvidenceSpan(
                span_id=c.get("span_id", "")[:24],
                text=text,
                document_id=c.get("document_id", ""),
                metadata=meta,
                reranker_score=max(0.0, min(1.0, norm_score)),
            )
        )
    return spans


# Lazy-loaded cross-encoder for reranking (one model per process)
_cross_encoder_model = None


def _get_cross_encoder():
    """Load cross-encoder once; return None if disabled or unavailable."""
    global _cross_encoder_model
    if not CROSS_ENCODER_MODEL or _CrossEncoder is None:
        return None
    if _cross_encoder_model is None:
        try:
            _cross_encoder_model = _CrossEncoder(CROSS_ENCODER_MODEL)
            logger.info("Cross-encoder loaded: %s", CROSS_ENCODER_MODEL)
        except Exception as e:
            logger.warning("Cross-encoder load failed (%s): %s", CROSS_ENCODER_MODEL, e)
            return None
    return _cross_encoder_model


def _rerank_with_cross_encoder(
    query: str,
    candidates: list[EvidenceSpan],
    top_k: int,
) -> list[EvidenceSpan]:
    """
    Rerank with cross-encoder when available; otherwise sort by existing reranker_score.
    Takes up to RERANK_CANDIDATES candidates, rescores (query, text) pairs, returns top_k.
    """
    if not candidates:
        return []
    scored = [c for c in candidates if c.reranker_score is not None]
    if not scored:
        return []
    scored.sort(key=lambda s: s.reranker_score or 0.0, reverse=True)
    to_rerank = scored[: RERANK_CANDIDATES]
    model = _get_cross_encoder()
    if model is None:
        return to_rerank[:top_k]
    pairs = [(query, (s.text or "")[:MAX_TEXT_FOR_CROSS_ENCODER]) for s in to_rerank]
    try:
        raw_scores = model.predict(pairs)
        if raw_scores is None or len(raw_scores) != len(to_rerank):
            return to_rerank[:top_k]
        arr = np.asarray(raw_scores, dtype=float)
        if arr.size == 0:
            return to_rerank[:top_k]
        # Min-max to [0, 1]
        min_s, max_s = arr.min(), arr.max()
        if max_s - min_s > 1e-6:
            norm = (arr - min_s) / (max_s - min_s)
        else:
            norm = np.ones_like(arr)
        out = []
        for i, span in enumerate(to_rerank):
            new_score = float(norm[i])
            out.append(span.model_copy(update={"reranker_score": new_score}))
        out.sort(key=lambda s: s.reranker_score or 0.0, reverse=True)
        return out[:top_k]
    except Exception as e:
        logger.warning("Cross-encoder predict failed: %s", e)
        return to_rerank[:top_k]


def rerank(query: str, candidates: list[EvidenceSpan], top_k: int = TOP_K) -> list[EvidenceSpan]:
    """
    Rerank candidates: use cross-encoder when enabled, else sort by existing score.
    Returns top_k spans.
    """
    return _rerank_with_cross_encoder(query, candidates, top_k)


def apply_mmr(
    spans: list[EvidenceSpan],
    top_k: int,
    lambda_: float = 0.7,
) -> list[EvidenceSpan]:
    """
    Maximal Marginal Relevance: select top_k spans balancing relevance and diversity.
    Diversity = same document_id is penalized so we don't return many spans from one doc.
    """
    if not spans or top_k <= 0:
        return []
    if len(spans) <= top_k:
        return list(spans)
    scores = [s.reranker_score or 0.0 for s in spans]
    selected_indices: list[int] = []
    for _ in range(top_k):
        best_idx = -1
        best_mmr = -1e9
        for i in range(len(spans)):
            if i in selected_indices:
                continue
            rel = scores[i]
            sim_to_selected = 0.0
            if selected_indices:
                doc_id = spans[i].document_id or ""
                for j in selected_indices:
                    if (spans[j].document_id or "") == doc_id:
                        sim_to_selected = 1.0
                        break
            mmr = lambda_ * rel - (1.0 - lambda_) * sim_to_selected
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        if best_idx < 0:
            break
        selected_indices.append(best_idx)
    out = [spans[i] for i in selected_indices]
    out.sort(key=lambda s: s.reranker_score or 0.0, reverse=True)
    return out


def _filter_by_allowlist(spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
    """Keep only spans from allowlisted authoritative issuers. No filter if allowlist is empty."""
    if not AUTHORITATIVE_ISSUERS:
        return spans
    return [s for s in spans if s.metadata.issuing_body in AUTHORITATIVE_ISSUERS]


def _infer_downgrade_reason(spans: list[EvidenceSpan]) -> str:
    """Infer downgrade reason from retrieval result."""
    if not spans:
        return "no_authoritative_source_found"
    filtered = _filter_by_allowlist(spans)
    if not filtered and AUTHORITATIVE_ISSUERS:
        return "no_authoritative_source_found"
    return "low_relevance"


def hybrid_retrieve(
    query: str,
    top_k: int = TOP_K,
    reranker_threshold: float = RERANKER_THRESHOLD,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    issuing_bodies: Optional[list[str]] = None,
    original_topic: Optional[str] = None,
) -> RetrievalResult:
    """
    Hybrid retrieval entry: lexical + vector -> merge -> rerank -> threshold check.
    Optional metadata filters: date_start/date_end (YYYY-MM-DD), issuing_bodies (list).

    Core logic (design doc 2.3):
    - When max rerank score < 0.35, mark as evidence insufficient
    - Set downgrade_reason when insufficient
    """
    expanded_query = expand_query_for_retrieval(query)
    lexical_spans = lexical_search(expanded_query, top_n=top_k * 2)
    vector_spans = vector_search(expanded_query, top_n=top_k * 2)

    # Always compute a small fallback channel as a multilingual booster so that
    # English-only queries can still surface Chinese-only policy spans.
    fallback_spans = _fallback_spans_from_corpus(
        query,
        top_k,
        date_start=date_start,
        date_end=date_end,
        issuing_bodies=issuing_bodies,
    )

    # If both real indices are unavailable, fall back entirely to the fallback channel.
    if not lexical_spans and not vector_spans:
        merged = fallback_spans
    else:
        # Merge candidates by span_id, keeping the higher-scoring version when both channels return it.
        merged_by_id: dict[str, EvidenceSpan] = {}
        for s in lexical_spans + vector_spans + fallback_spans:
            existing = merged_by_id.get(s.span_id)
            if existing is None or (s.reranker_score or 0.0) > (existing.reranker_score or 0.0):
                merged_by_id[s.span_id] = s
        merged = list(merged_by_id.values())

    # Rerank to more candidates, then MMR to select top_k for diversity (avoid many spans from same doc)
    reranked = rerank(query, merged, top_k=min(top_k * 2, RERANK_CANDIDATES))
    reranked = apply_mmr(reranked, top_k, lambda_=0.7)

    # Reorder by issuing body preference (soft preference: order only, scores unchanged)
    ordered = reranked
    if issuing_bodies:
        pref_set = frozenset(
            (b or "").strip() for b in issuing_bodies if (b or "").strip()
        )
        if pref_set:
            preferred: list[EvidenceSpan] = []
            others: list[EvidenceSpan] = []
            for s in reranked:
                ib = (getattr(s.metadata, "issuing_body", "") or "").strip()
                if ib in pref_set:
                    preferred.append(s)
                else:
                    others.append(s)
            if preferred:
                ordered = preferred + others

    spans_for_threshold = (
        _filter_by_allowlist(reranked) if AUTHORITATIVE_ISSUERS else reranked
    )

    scores = [s.reranker_score or 0.0 for s in spans_for_threshold]
    max_score = max(scores) if scores else 0.0
    evidence_sufficient = max_score >= reranker_threshold

    # Topic-level relevance check: if caller provided the original topic/beat,
    # require at least one retrieved span to overlap with the topic terms (excluding
    # generic Hainan/FTP domain words). This prevents obviously out-of-domain topics
    # (e.g. arbitrary names) from being marked as evidence-sufficient just because
    # the query was expanded with Hainan scope.
    topic_terms: set[str] = set()
    if original_topic:
        topic_terms = _extract_topic_terms(original_topic)
    if evidence_sufficient and topic_terms and spans_for_threshold:
        # Concatenate span texts and simple metadata for a lightweight overlap check.
        combined_text_parts: list[str] = []
        for s in spans_for_threshold:
            text_part = (s.text or "").lower()
            source_id = getattr(s.metadata, "source_identifier", "") or ""
            combined_text_parts.append(text_part)
            if source_id:
                combined_text_parts.append(str(source_id).lower())
        combined_text = " ".join(combined_text_parts)
        has_topic_overlap = any(term in combined_text for term in topic_terms)
        if not has_topic_overlap:
            evidence_sufficient = False

    downgrade_reason: Optional[str] = None
    if not evidence_sufficient:
        downgrade_reason = _infer_downgrade_reason(reranked)

    # Lightweight retrieval log to help bad-case attribution (retrieval vs generation)
    top_span_ids = [s.span_id for s in ordered[:5]]
    used_fallback_only = not lexical_spans and not vector_spans
    logger.info(
        "RAG retrieve: query=%r len_spans=%s top5_ids=%s max_score=%.3f sufficient=%s fallback_only=%s",
        (query or "")[:50],
        len(ordered),
        top_span_ids,
        max_score,
        evidence_sufficient,
        used_fallback_only,
    )

    return RetrievalResult(
        spans=ordered,
        evidence_sufficient=evidence_sufficient,
        downgrade_reason=downgrade_reason,
    )
