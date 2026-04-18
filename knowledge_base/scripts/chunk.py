#!/usr/bin/env python3
"""
Chunk documents into retrievable spans.

Reads from data/raw/articles/ and data/metadata.json.
Outputs to data/chunks/ with span-level metadata.
"""

import json
import re
import hashlib
from pathlib import Path

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_ARTICLES = DATA_DIR / "raw" / "articles"
CHUNKS_DIR = DATA_DIR / "chunks"

# P1 chunking
CHUNK_VERSION = "v2_paragraph_500_800_overlap_sentence"
MIN_CHUNK_LEN = 500
MAX_CHUNK_LEN = 800
OVERLAP_CHARS = 80  


def infer_article_no_and_section_type(chunk_text: str) -> tuple[str | None, str]:
    """
    Infer article/section markers from the chunk text.
    Returns (article_no, section_type).
    section_type: law_article | policy_clause | other
    """
    first_line = chunk_text.strip().splitlines()[0].strip() if chunk_text.strip() else ""
    if not first_line:
        return None, "other"
    m = re.match(r"(第[一二三四五六七八九十百千]+\s*条)", first_line)
    if m:
        return m.group(1), "law_article"
    m = re.match(r"(Article\s+\d+)", first_line, re.IGNORECASE)
    if m:
        return m.group(1), "law_article"
    if re.match(r"^\d+[.\)]\s+", first_line) or re.match(r"^[-*]\s+", first_line):
        return None, "policy_clause"
    return None, "other"

def split_into_sentences(para: str) -> list[str]:
    """
    Split a long paragraph into sentences on [。！？.!?] to avoid cutting mid-sentence.
    """
    # 在句末标点后切分，保留标点与当前句
    parts = re.split(r"(?<=[。！？.!?])\s*", para)
    return [p.strip() for p in parts if p.strip()]


def looks_like_new_clause(line: str) -> bool:
    """Heuristics to detect a new article/section."""
    line = line.strip()
    if not line:
        return False
    if re.match(r"^(Article|Section)\s+\d+", line):
        return True
    if re.match(r"^第[一二三四五六七八九十百千]+\s*条", line):
        return True
    if re.match(r"^\d+[\.\)]\s+", line):
        return True
    if re.match(r"^\(\d+\)\s+", line):
        return True
    if re.match(r"^[-*]\s+", line):
        return True
    if re.match(r"^#{1,3}\s+\S+", line):
        return True
    return False


def split_into_paragraphs(raw_text: str) -> list[str]:
    """
    Split raw text into paragraphs/clauses using newlines and simple structural cues.
    """
    lines = raw_text.splitlines()
    paras: list[str] = []
    buf: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                paras.append(" ".join(buf).strip())
                buf = []
            continue

        if buf and looks_like_new_clause(stripped):
            paras.append(" ".join(buf).strip())
            buf = [stripped]
        else:
            buf.append(stripped)

    if buf:
        paras.append(" ".join(buf).strip())

    return [p for p in paras if len(p) > 10]


def _group_sentences_into_chunks(sentences: list[str], start_idx: int) -> list[tuple[int, str]]:
    """
    Group sentences into chunks <= MAX_CHUNK_LEN, with OVERLAP_CHARS overlap between chunks.
    Used for long paragraphs that we split by sentence.
    """
    out: list[tuple[int, str]] = []
    idx = start_idx
    buf: list[str] = []
    buf_len = 0
    overlap_suffix = ""

    for sent in sentences:
        s_len = len(sent)
        if not sent:
            continue
        # 单句超长：按 MAX 硬切并带重叠（罕见）
        if not buf and s_len > MAX_CHUNK_LEN:
            start = 0
            while start < s_len:
                sub = sent[start : start + MAX_CHUNK_LEN].strip()
                if sub:
                    out.append((idx, sub))
                    idx += 1
                    overlap_suffix = sub[-OVERLAP_CHARS:] if len(sub) >= OVERLAP_CHARS else ""
                start += max(1, MAX_CHUNK_LEN - OVERLAP_CHARS)
            continue

        if buf_len + s_len <= MAX_CHUNK_LEN:
            buf.append(sent)
            buf_len += s_len
        else:
            if buf:
                text = " ".join(buf).strip()
                out.append((idx, text))
                idx += 1
                overlap_suffix = text[-OVERLAP_CHARS:] if len(text) >= OVERLAP_CHARS else ""
            buf = [overlap_suffix, sent] if overlap_suffix else [sent]
            buf_len = len(overlap_suffix) + (1 if overlap_suffix else 0) + s_len

    if buf:
        out.append((idx, " ".join(buf).strip()))
    return out


def group_paragraphs_into_chunks(paras: list[str]) -> list[tuple[int, str]]:
    """
    Group paragraphs into chunks with length roughly in [MIN_CHUNK_LEN, MAX_CHUNK_LEN].
    - 先按段落聚合，尽量不打断条款
    - 单段超长时按句号/问号/感叹号分句后再组块，避免句中硬切
    - 块间保留 OVERLAP_CHARS 重叠，缓解边界效应
    - 短尾块仅在与前一块合并后仍 <= MAX 时才合并
    """
    chunks: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_len = 0
    idx = 0
    overlap_suffix = ""

    for para in paras:
        p_len = len(para)

        # 单段超长：按句切分后再组块
        if not buf and p_len > MAX_CHUNK_LEN:
            sentences = split_into_sentences(para)
            if not sentences:
                # 无句末标点则退化为按 MAX 切
                start = 0
                while start < p_len:
                    sub = para[start : start + MAX_CHUNK_LEN].strip()
                    if sub:
                        chunks.append((idx, sub))
                        idx += 1
                    start += MAX_CHUNK_LEN
            else:
                sub_chunks = _group_sentences_into_chunks(sentences, idx)
                chunks.extend(sub_chunks)
                idx = sub_chunks[-1][0] + 1 if sub_chunks else idx
            continue

        # 尝试把当前段落追加到 buffer
        if buf_len + p_len <= MAX_CHUNK_LEN:
            buf.append(para)
            buf_len += p_len
        else:
            if buf:
                text = " ".join(buf).strip()
                chunks.append((idx, text))
                idx += 1
                overlap_suffix = text[-OVERLAP_CHARS:] if len(text) >= OVERLAP_CHARS else ""
            buf = [overlap_suffix, para] if overlap_suffix else [para]
            buf_len = len(overlap_suffix) + (1 if overlap_suffix else 0) + p_len

    if buf:
        chunks.append((idx, " ".join(buf).strip()))

    # 短尾合并：仅当合并后仍 <= MAX 时才合并，避免产生过长块
    if len(chunks) >= 2:
        last_idx, last_text = chunks[-1]
        prev_idx, prev_text = chunks[-2]
        if len(last_text) < MIN_CHUNK_LEN and len(prev_text) + len(last_text) + 1 <= MAX_CHUNK_LEN:
            merged = f"{prev_text} {last_text}".strip()
            chunks[-2] = (prev_idx, merged)
            chunks.pop()

    return chunks


def make_span_id(document_id: str, chunk_text: str) -> str:
    """
    Build a stable span_id from document_id + normalized text hash.
    """
    # 归一化空白，避免无关差异
    norm = " ".join(chunk_text.split())
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return f"{document_id}-span-{h}"


def extract_pdf_text(path: Path) -> str:
    """Extract text from PDF. Returns empty string if PyPDF2 unavailable or on error."""
    if not HAS_PYPDF2:
        return ""
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = DATA_DIR / "metadata.json"
    if not meta_path.exists():
        print("No metadata.json found. Run corpus_manager.py first.")
        return
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    docs = data.get("documents", [])
    all_chunks = []
    seen_doc_hashes: set[str] = set()
    for doc in docs:
        fp = doc.get("file_path", "")
        path = DATA_DIR / fp
        if not path.exists():
            continue
        if fp.endswith(".md"):
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        elif fp.endswith(".pdf"):
            raw_text = extract_pdf_text(path)
        else:
            continue
        if not raw_text:
            continue

        # De-duplicate documents by full-text hash so that mirrored or
        # http/https-duplicate pages do not produce duplicate chunks.
        doc_fingerprint = hashlib.sha1(raw_text.encode("utf-8", errors="ignore")).hexdigest()
        if doc_fingerprint in seen_doc_hashes:
            continue
        seen_doc_hashes.add(doc_fingerprint)

        paragraphs = split_into_paragraphs(raw_text)
        if not paragraphs:
            continue

        doc_id = doc.get("source_identifier") or "doc"
        language = doc.get("language") or "en"
        legal_hierarchy = doc.get("legal_hierarchy")
        policy_level = doc.get("policy_level")
        canonical_policy_id = doc.get("canonical_policy_id") or doc_id

        chunks = group_paragraphs_into_chunks(paragraphs)
        for local_idx, chunk_text in chunks:
            span_id = make_span_id(doc_id, chunk_text)
            article_no, section_type = infer_article_no_and_section_type(chunk_text)
            chunk_file = CHUNKS_DIR / f"{span_id}.txt"
            chunk_file.write_text(chunk_text, encoding="utf-8")
            all_chunks.append(
                {
                    "span_id": span_id,
                    "document_id": doc.get("source_identifier"),
                    "text": chunk_text,
                    "issuing_body": doc.get("issuing_body"),
                    "publication_date": doc.get("publication_date"),
                    "chunk_version": CHUNK_VERSION,
                    "language": language,
                    "legal_hierarchy": legal_hierarchy,
                    "policy_level": policy_level,
                    "canonical_policy_id": canonical_policy_id,
                    "article_no": article_no,
                    "section_type": section_type,
                }
            )
    out_index = CHUNKS_DIR / "chunks_index.json"
    out_index.write_text(json.dumps({"chunks": all_chunks}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Chunked {len(docs)} docs into {len(all_chunks)} spans. Index: {out_index}")


if __name__ == "__main__":
    main()
