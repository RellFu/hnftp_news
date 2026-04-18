#!/usr/bin/env python3
"""
Corpus manager for Hainan Free Trade Port policy reporting.

Three-layer design:
  Layer 1: Policy (policy.hnftp.gov.cn, hainan.gov.cn)
  Layer 2: Implementation (plan.hainan.gov.cn; haikou.customs.gov.cn currently paused)
  Layer 3: English (en.hnftp.gov.cn, en.hainan.gov.cn, HainanFTPinvestmentguide.pdf)

Chinese content is allowed for Layer 1–2; Layer 3 remains EN.
Output: /data/raw/articles/, /data/raw/pdfs/, /data/metadata.json
"""

import argparse
import json
import os
import re
import hashlib
import unicodedata
from collections import deque
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin
import time

import requests
from bs4 import BeautifulSoup
from io import BytesIO

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

# Paths (project root = parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_ARTICLES = DATA_DIR / "raw" / "articles"
RAW_PDFS = DATA_DIR / "raw" / "pdfs"

# =============================================================================
# Three-layer design sources (Layer 1–3). Includes only the sources below; excludes Xinhua/SCIO/CGTN, etc.
# =============================================================================

# Layer 1: Policy repository & government disclosures | Layer 2: Department implementation details | Layer 3: Official English translations
TARGET_URLS = [
    # --- Layer 1: Policy repository and government disclosures (policy.hnftp, provincial government docs) ---
    "https://policy.hnftp.gov.cn/policy-regulation-publish-web/home",
    "https://www.hainan.gov.cn/hainan/zchbbwwj/liebiao.shtml",
    # --- Layer 2: Department implementation details (DRC, business env, SASAC, tourism/culture, ecology, civil affairs, HRSS, health; Haikou Customs currently dropped) ---
    # "https://haikou.customs.gov.cn/",  # Dropped for now: persistent 504/412
    "https://plan.hainan.gov.cn/",
    "https://db.hainan.gov.cn/",       # Department of Business Environment
    "https://gzw.hainan.gov.cn/",      # SASAC
    "https://lwt.hainan.gov.cn/",      # Department of Tourism/Culture/Radio/TV/Sports
    "https://hnsthb.hainan.gov.cn/",   # Department of Ecology and Environment
    "https://mz.hainan.gov.cn/",       # Department of Civil Affairs
    "https://hrss.hainan.gov.cn/",     # Department of Human Resources and Social Security
    "https://wst.hainan.gov.cn/",      # Health Commission
    # --- Layer 3: Official English translations (FTP English portal, Hainan gov English portal, investment guide PDF) ---
    "https://en.hnftp.gov.cn/",
    "https://en.hainan.gov.cn/englishsitem/mindex.shtml",
    "https://en.hainan.gov.cn/englishsite/Dynamic/dynamic.shtml",
    "https://en.hainan.gov.cn/englishsite/Government/government.shtml",
    "https://regional.chinadaily.com.cn/pdf/HainanFTPinvestmentguide.pdf",
]

# Domain -> issuing body (only organisations in current design)
DOMAIN_ISSUER = {
    "policy.hnftp.gov.cn": "Hainan Free Trade Port Authority",
    "hnftp.gov.cn": "Hainan Free Trade Port Authority",
    "en.hnftp.gov.cn": "Hainan Free Trade Port Authority",
    "hainan.gov.cn": "Hainan Provincial Government",
    "en.hainan.gov.cn": "Hainan Provincial Government",
    "customs.gov.cn": "General Administration of Customs",
    "haikou.customs.gov.cn": "Haikou Customs",
    "plan.hainan.gov.cn": "Hainan Development and Reform Commission",
    "db.hainan.gov.cn": "Hainan Department of Business Environment",
    "gzw.hainan.gov.cn": "Hainan SASAC",
    "lwt.hainan.gov.cn": "Hainan Department of Tourism, Culture, Radio, Television and Sports",
    "hnsthb.hainan.gov.cn": "Hainan Department of Ecology and Environment",
    "mz.hainan.gov.cn": "Hainan Department of Civil Affairs",
    "hrss.hainan.gov.cn": "Hainan Department of Human Resources and Social Security",
    "wst.hainan.gov.cn": "Hainan Health Commission",
    "regional.chinadaily.com.cn": "China Daily",
}

# Hosts that may contain Chinese official content (Layer 1–2).
# When host matches one of these, we do not reject non-English content.
ALLOW_CHINESE_HOSTS = (
    "policy.hnftp.gov.cn",
    "hnftp.gov.cn",  # paired with the next rule: en.* is still treated as English portal
    "hainan.gov.cn",
    "customs.gov.cn",
    "plan.hainan.gov.cn",
    "db.hainan.gov.cn",
    "gzw.hainan.gov.cn",
    "lwt.hainan.gov.cn",
    "hnsthb.hainan.gov.cn",
    "mz.hainan.gov.cn",
    "hrss.hainan.gov.cn",
    "wst.hainan.gov.cn",
)

# Max share of non-ASCII (CJK etc.) chars; above this = reject as non-English
NON_ENGLISH_THRESHOLD = 0.25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY = 1.5

# Hainan Provincial Government crawl settings (English portal)
HAINAN_SEED_URLS = [
    "https://en.hainan.gov.cn/englishsitem/mindex.shtml",
    "https://en.hainan.gov.cn/englishsite/Dynamic/dynamic.shtml",
    "https://en.hainan.gov.cn/englishsite/Travel/travel.shtml",
    "https://en.hainan.gov.cn/englishsite/Online/service.shtml",
    "https://en.hainan.gov.cn/englishsite/Government/government.shtml",
    "https://en.hainan.gov.cn/englishsitem/Business/business.shtml",
]
MAX_HAINAN_PAGES = 120

# Hainan Free Trade Port Authority crawl settings (Chinese portal)
HNFTP_SEED_URLS = [
    "http://www.hnftp.gov.cn/",
    "https://policy.hnftp.gov.cn/policy-regulation-publish-web/home",
]
MAX_HNFTP_PAGES = 120

# Hainan Development and Reform Commission (plan.hainan.gov.cn) crawl config (Layer 2)
PLAN_HAINAN_SEED_URLS = [
    "https://plan.hainan.gov.cn/",
    "https://plan.hainan.gov.cn/xxgk/",  # information disclosure
]
MAX_PLAN_HAINAN_PAGES = 80

# Haikou Customs (haikou.customs.gov.cn) crawl config (Layer 2)
HAIKOU_CUSTOMS_SEED_URLS = [
    "http://haikou.customs.gov.cn/",
    "https://haikou.customs.gov.cn/",
]
MAX_HAIKOU_CUSTOMS_PAGES = 120

# Layer 2 BFS crawl for department portals (target: 100+ pages per site)
MAX_DEPARTMENT_PAGES = 120
DEPARTMENT_CRAWLS = [
    ("db.hainan.gov.cn", ["https://db.hainan.gov.cn/", "https://db.hainan.gov.cn/xxgk/"], "Business Environment"),
    ("gzw.hainan.gov.cn", ["https://gzw.hainan.gov.cn/", "https://gzw.hainan.gov.cn/xxgk/"], "SASAC"),
    ("lwt.hainan.gov.cn", ["https://lwt.hainan.gov.cn/", "https://lwt.hainan.gov.cn/xxgk_55333/"], "Tourism and Culture"),
    ("hnsthb.hainan.gov.cn", ["https://hnsthb.hainan.gov.cn/", "https://hnsthb.hainan.gov.cn/xxgk/"], "Ecology and Environment"),
    ("mz.hainan.gov.cn", ["https://mz.hainan.gov.cn/", "https://mz.hainan.gov.cn/xxgk/"], "Civil Affairs"),
    ("hrss.hainan.gov.cn", ["https://hrss.hainan.gov.cn/", "https://hrss.hainan.gov.cn/xxgk/"], "HRSS"),
    ("wst.hainan.gov.cn", ["https://wst.hainan.gov.cn/", "https://wst.hainan.gov.cn/swjw/xxgk/"], "Health Commission"),
]


def slugify(text: str, max_len: int = 60) -> str:
    """Create filesystem-safe slug from title."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[/\\:*?"<>|]', "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    text = text[:max_len].rstrip("-") if len(text) > max_len else text
    if not text or len(text.strip()) < 2:
        return "untitled"
    return text


def infer_issuing_body(url: str) -> str:
    """Infer issuing body from URL domain. Prefer longer (more specific) domain match."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    # Sort by descending domain length so specific domains match first (e.g. plan.hainan.gov.cn before hainan.gov.cn)
    for domain, issuer in sorted(DOMAIN_ISSUER.items(), key=lambda x: -len(x[0])):
        if domain in host:
            return issuer
    return host.split(".")[-2] if "." in host else "Unknown"


def infer_document_meta(url: str, default_type: str = "article") -> dict:
    """
    Infer high-level document metadata from URL for downstream retrieval.

    Returns a dict that may contain:
    - document_type: law | pdf | policy | guideline | article | ...
    - legal_hierarchy: national_law | regulation_or_policy | provincial_policy | tax_guideline | customs_rule | planning_policy | other
    - policy_level: central | provincial | ftp_authority | department | customs | other
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    doc_type = default_type
    legal_hierarchy: str | None = None
    policy_level: str | None = None

    if "policy.hnftp.gov.cn" in host:
        doc_type = "policy"
        legal_hierarchy = "regulation_or_policy"
        policy_level = "ftp_authority"
    elif "customs.gov.cn" in host:
        doc_type = "guideline"
        legal_hierarchy = "customs_rule"
        policy_level = "central"
    elif "plan.hainan.gov.cn" in host:
        doc_type = "policy"
        legal_hierarchy = "planning_policy"
        policy_level = "provincial"
    elif "db.hainan.gov.cn" in host:
        doc_type = "policy"
        legal_hierarchy = "provincial_policy"
        policy_level = "provincial"
    elif "gzw.hainan.gov.cn" in host:
        doc_type = "policy"
        legal_hierarchy = "provincial_policy"
        policy_level = "provincial"
    elif "lwt.hainan.gov.cn" in host or "hnsthb.hainan.gov.cn" in host or "mz.hainan.gov.cn" in host or "hrss.hainan.gov.cn" in host or "wst.hainan.gov.cn" in host:
        doc_type = "policy"
        legal_hierarchy = "provincial_policy"
        policy_level = "provincial"
    elif "en.hnftp.gov.cn" in host or "hnftp.gov.cn" in host:
        policy_level = "ftp_authority"
        legal_hierarchy = legal_hierarchy or "portal_or_policy"
    elif "en.hainan.gov.cn" in host or "hainan.gov.cn" in host:
        policy_level = "provincial"
        legal_hierarchy = legal_hierarchy or "provincial_policy"
    elif "english.www.gov.cn" in host or "scio.gov.cn" in host or "news.cn" in host:
        policy_level = "central"
        legal_hierarchy = legal_hierarchy or "central_policy"

    return {
        "document_type": doc_type,
        "legal_hierarchy": legal_hierarchy or "other",
        "policy_level": policy_level or "other",
    }

def canonical_url(url: str) -> str:
    """
    Build a canonical key for URL de-duplication.

    - Ignore scheme (http / https)
    - Lowercase host
    - Strip leading 'www.'
    - Normalize path by removing trailing slashes
    - Keep query string when present
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    query = parsed.query or ""
    if query:
        return f"{host}{path}?{query}"
    return f"{host}{path}"

def extract_date_from_html(soup: BeautifulSoup, url: str) -> str | None:
    """Try to extract publication date from HTML."""
    # Meta tags
    for selector in ['meta[property="article:published_time"]', 'meta[name="publishdate"]', 'meta[name="date"]']:
        tag = soup.select_one(selector)
        if tag:
            val = tag.get("content") or tag.get("value")
            if val:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", str(val))
                if m:
                    return m.group(1)
    # Common class patterns
    for cls in ["publish-date", "date", "pub-date", "time"]:
        tag = soup.find(class_=re.compile(cls, re.I))
        if tag:
            m = re.search(r"(\d{4})[-\/](\d{2})[-\/](\d{2})", tag.get_text())
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # URL path (e.g. /202106/t20210610_...)
    m = re.search(r"/(\d{4})(\d{2})(\d{2})/", url) or re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def extract_title_from_html(soup: BeautifulSoup, url: str) -> str:
    """Extract page title."""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)[:120]
    parsed = urlparse(url)
    return parsed.path.strip("/").split("/")[-1].replace(".shtml", "").replace(".html", "") or "untitled"


def is_pdf_url(url: str) -> bool:
    """Check if URL points to PDF."""
    return ".pdf" in url.lower() or "UERGL" in url  # base64 PDF links


def fetch_url(
    url: str,
    session: requests.Session,
    timeout: int = 30,
    max_retries: int = 0,
    extra_headers: dict | None = None,
) -> requests.Response | None:
    """Fetch URL with error handling. Optional retries for 412/5xx and timeouts."""
    verify_ssl = os.environ.get("CORPUS_VERIFY_SSL", "1") != "0"
    headers = {**HEADERS, **(extra_headers or {})}
    last_error: Exception | None = None
    for attempt in range(max(1, max_retries + 1)):
        try:
            r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True, verify=verify_ssl)
            if r.status_code in (412, 502, 503, 504) and attempt < max_retries:
                time.sleep(REQUEST_DELAY * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(REQUEST_DELAY * (attempt + 1))
            else:
                print(f"  Fetch error: {e}")
                return None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(REQUEST_DELAY * (attempt + 1))
            else:
                print(f"  Fetch error: {e}")
                return None
        except Exception as e:
            print(f"  Fetch error: {e}")
            return None
    if last_error:
        print(f"  Fetch error: {last_error}")
    return None


def _decode_html(content: bytes, response: requests.Response) -> str:
    """Decode HTML. English sources: prefer UTF-8 only to avoid mojibake."""
    enc = response.encoding
    if not enc or enc.lower() == "iso-8859-1":
        m = re.search(rb'charset\s*=\s*["\']?([\w-]+)', content[:5000], re.I)
        enc = m.group(1).decode("ascii", errors="ignore") if m else "utf-8"
    for try_enc in (enc, "utf-8"):
        try:
            return content.decode(try_enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _is_english_content(text: str) -> bool:
    """Reject content with too much non-English (CJK, etc.)."""
    if not text or len(text.strip()) < 50:
        return False
    sample = text[:10000]
    non_latin = sum(1 for c in sample if ord(c) > 0x024F and not c.isspace())
    return (non_latin / len(sample)) <= NON_ENGLISH_THRESHOLD


def process_html(
    url: str,
    session: requests.Session,
    timeout: int = 30,
    max_retries: int = 0,
    extra_headers: dict | None = None,
) -> dict | None:
    """Fetch HTML, extract content, save as .md, return metadata."""
    r = fetch_url(url, session, timeout=timeout, max_retries=max_retries, extra_headers=extra_headers)
    if not r or not r.content:
        return None
    html = _decode_html(r.content, r)
    soup = BeautifulSoup(html, "html.parser")
    title = extract_title_from_html(soup, url)
    pub_date = extract_date_from_html(soup, url) or datetime.now().strftime("%Y-%m-%d")
    content = ""
    if HAS_TRAFILATURA:
        content = trafilatura.extract(html) or ""
    if not content:
        content = soup.get_text(separator="\n\n", strip=True)[:50000]
    if not content.strip():
        print(f"  No content extracted: {url}")
        return None

    # Three-layer rule: policy/implementation layers allow Chinese; en.* portals keep English only.
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    allow_non_english = any(h in host for h in ALLOW_CHINESE_HOSTS) and not host.startswith("en.")

    is_english = _is_english_content(content)
    if not is_english and not allow_non_english:
        print(f"  Skipped (non-English content): {url}")
        return None
    language = "en" if is_english else "zh"
    slug = slugify(title) or hashlib.md5(url.encode()).hexdigest()[:12]
    fname = f"{pub_date}_{slug}.md"
    out_path = RAW_ARTICLES / fname
    RAW_ARTICLES.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        base = out_path.stem
        suffix = hashlib.md5(url.encode()).hexdigest()[:8]
        out_path = RAW_ARTICLES / f"{base}_{suffix}.md"
    out_path.write_text(content, encoding="utf-8")
    rel_path = out_path.relative_to(DATA_DIR)
    source_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    base_meta = {
        "file_path": str(rel_path),
        "source_url": url,
        "issuing_body": infer_issuing_body(url),
        "publication_date": pub_date,
        "source_identifier": f"corpus-{source_id}",
        "title": title,
        "language": language,
        "canonical_policy_id": f"policy-{source_id}",
    }
    inferred = infer_document_meta(url, default_type="article")
    base_meta.update(inferred)
    return base_meta


def _extract_hainan_links(html: str, base_url: str) -> list[str]:
    """Extract en.hainan.gov.cn links from a page for crawling."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if "en.hainan.gov.cn" not in full:
            continue
        links.append(full)
    return links


def crawl_hainan(
    session: requests.Session,
    seen_urls: set[str],
    metadata_list: list[dict],
    max_pages: int = MAX_HAINAN_PAGES,
) -> None:
    """
    Crawl en.hainan.gov.cn starting from seed URLs.

    - Breadth-first crawl within the domain
    - English-only filter applied via process_html
    - Deduplicates by URL using seen_urls
    """
    queue: deque[str] = deque(HAINAN_SEED_URLS)
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        if "en.hainan.gov.cn" not in url:
            continue

        print(f"[HAINAN] {len(visited)}/{max_pages} {url[:90]}...")

        # Fetch page once for link extraction
        r = fetch_url(url, session)
        if not r or not r.content:
            continue
        html = _decode_html(r.content, r)
        for link in _extract_hainan_links(html, url):
            key = canonical_url(link)
            if link not in visited and key not in seen_urls:
                queue.append(link)

        # Skip if we already processed this URL (by canonical key) as a target
        key = canonical_url(url)
        if key in seen_urls:
            continue

        # Use existing HTML processor (which will re-fetch; acceptable at this scale)
        meta = process_html(url, session)
        if meta:
            metadata_list.append(meta)
            seen_urls.add(key)
            print(f"  -> {meta.get('file_path', '')}")

        time.sleep(REQUEST_DELAY)


def _extract_hnftp_links(html: str, base_url: str) -> list[str]:
    """Extract hnftp.gov.cn links from a page for crawling (Chinese FTP authority portal)."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if "hnftp.gov.cn" not in full:
            continue
        links.append(full)
    return links


def crawl_hnftp(
    session: requests.Session,
    seen_urls: set[str],
    metadata_list: list[dict],
    max_pages: int = MAX_HNFTP_PAGES,
) -> None:
    """Crawl hnftp.gov.cn (Chinese) starting from seed URLs."""
    queue: deque[str] = deque(HNFTP_SEED_URLS)
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        if "hnftp.gov.cn" not in url:
            continue

        print(f"[HNFTP] {len(visited)}/{max_pages} {url[:90]}...")

        r = fetch_url(url, session)
        if not r or not r.content:
            continue
        html = _decode_html(r.content, r)
        for link in _extract_hnftp_links(html, url):
            key = canonical_url(link)
            if link not in visited and key not in seen_urls:
                queue.append(link)

        key = canonical_url(url)
        if key in seen_urls:
            continue

        meta = process_html(url, session)
        if meta:
            metadata_list.append(meta)
            seen_urls.add(key)
            print(f"  -> {meta.get('file_path', '')}")

        time.sleep(REQUEST_DELAY)


def _extract_plan_hainan_links(html: str, base_url: str) -> list[str]:
    """Extract plan.hainan.gov.cn links for BFS crawl (provincial DRC)."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if "plan.hainan.gov.cn" not in full:
            continue
        links.append(full)
    return links


def crawl_plan_hainan(
    session: requests.Session,
    seen_urls: set[str],
    metadata_list: list[dict],
    max_pages: int = MAX_PLAN_HAINAN_PAGES,
) -> None:
    """Crawl plan.hainan.gov.cn (Hainan DRC) for Layer 2 implementation docs."""
    queue: deque[str] = deque(PLAN_HAINAN_SEED_URLS)
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        if "plan.hainan.gov.cn" not in url:
            continue

        print(f"[PLAN_HAINAN] {len(visited)}/{max_pages} {url[:90]}...")

        r = fetch_url(url, session)
        if not r or not r.content:
            continue
        html = _decode_html(r.content, r)
        for link in _extract_plan_hainan_links(html, url):
            key = canonical_url(link)
            if link not in visited and key not in seen_urls:
                queue.append(link)

        key = canonical_url(url)
        if key in seen_urls:
            continue

        meta = process_html(url, session)
        if meta:
            metadata_list.append(meta)
            seen_urls.add(key)
            print(f"  -> {meta.get('file_path', '')}")

        time.sleep(REQUEST_DELAY)


def _extract_haikou_customs_links(html: str, base_url: str) -> list[str]:
    """Extract haikou.customs.gov.cn links for BFS crawl (Haikou Customs)."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if "haikou.customs.gov.cn" not in full:
            continue
        links.append(full)
    return links


def crawl_haikou_customs(
    session: requests.Session,
    seen_urls: set[str],
    metadata_list: list[dict],
    max_pages: int = MAX_HAIKOU_CUSTOMS_PAGES,
) -> None:
    """Crawl haikou.customs.gov.cn (Haikou Customs) for Layer 2 implementation docs."""
    queue: deque[str] = deque(HAIKOU_CUSTOMS_SEED_URLS)
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        if "haikou.customs.gov.cn" not in url:
            continue

        print(f"[HAIKOU_CUSTOMS] {len(visited)}/{max_pages} {url[:90]}...")

        customs_headers = {"Referer": "https://haikou.customs.gov.cn/"}
        r = fetch_url(url, session, timeout=60, max_retries=3, extra_headers=customs_headers)
        if not r or not r.content:
            continue
        html = _decode_html(r.content, r)
        for link in _extract_haikou_customs_links(html, url):
            key = canonical_url(link)
            if link not in visited and key not in seen_urls:
                queue.append(link)

        key = canonical_url(url)
        if key in seen_urls:
            continue

        meta = process_html(url, session, timeout=60, max_retries=3, extra_headers=customs_headers)
        if meta:
            metadata_list.append(meta)
            seen_urls.add(key)
            print(f"  -> {meta.get('file_path', '')}")

        time.sleep(REQUEST_DELAY)


def _extract_domain_links(html: str, base_url: str, domain: str) -> list[str]:
    """Extract links that belong to the given domain (for generic department crawl)."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if domain not in full:
            continue
        links.append(full)
    return links


def crawl_domain(
    session: requests.Session,
    seen_urls: set[str],
    metadata_list: list[dict],
    domain: str,
    seed_urls: list[str],
    max_pages: int,
    label: str,
) -> None:
    """Generic BFS crawl for a single *.hainan.gov.cn department site (Layer 2, target 100+ pages)."""
    queue: deque[str] = deque(seed_urls)
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        if domain not in url:
            continue

        print(f"[{label}] {len(visited)}/{max_pages} {url[:85]}...")

        r = fetch_url(url, session, timeout=45, max_retries=2)
        if not r or not r.content:
            continue
        html = _decode_html(r.content, r)
        for link in _extract_domain_links(html, url, domain):
            key = canonical_url(link)
            if link not in visited and key not in seen_urls:
                queue.append(link)

        key = canonical_url(url)
        if key in seen_urls:
            continue

        meta = process_html(url, session, timeout=45, max_retries=2)
        if meta:
            metadata_list.append(meta)
            seen_urls.add(key)
            print(f"  -> {meta.get('file_path', '')}")

        time.sleep(REQUEST_DELAY)


def process_pdf(url: str, session: requests.Session) -> dict | None:
    """Download PDF, save to pdfs/, return metadata. English-only."""
    r = fetch_url(url, session)
    if not r or not r.content:
        return None
    ct = r.headers.get("Content-Type", "")
    if "pdf" not in ct and not url.lower().endswith(".pdf"):
        print(f"  Not a PDF response: {url}")
        return None
    pub_date = datetime.now().strftime("%Y-%m-%d")
    pdf_text_for_check = ""
    try:
        parsed = urlparse(url)
        path = parsed.path or ""
        fname_from_url = path.split("/")[-1] or "document"
        if fname_from_url.lower().endswith(".pdf"):
            title = fname_from_url[:-4].replace("_", " ").replace("-", " ")
        else:
            title = "document"
        if HAS_PYPDF2:
            pr = PdfReader(BytesIO(r.content))
            info = pr.metadata
            if info:
                created = info.get("/CreationDate")
                if created:
                    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", str(created))
                    if m:
                        pub_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                if info.get("/Title"):
                    title = info.get("/Title", "")[:80]
            for page in pr.pages:
                pdf_text_for_check += (page.extract_text() or "") + "\n"
    except Exception:
        pass
    is_english = True
    if pdf_text_for_check:
        is_english = _is_english_content(pdf_text_for_check)
    if pdf_text_for_check and not is_english:
        print(f"  Skipped PDF (non-English content): {url}")
        return None
    slug = slugify(title) or hashlib.md5(url.encode()).hexdigest()[:12]
    fname = f"{pub_date}_{slug}.pdf"
    out_path = RAW_PDFS / fname
    RAW_PDFS.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        base = out_path.stem
        suffix = hashlib.md5(url.encode()).hexdigest()[:8]
        out_path = RAW_PDFS / f"{base}_{suffix}.pdf"
    out_path.write_bytes(r.content)
    rel_path = out_path.relative_to(DATA_DIR)
    source_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    base_meta = {
        "file_path": str(rel_path),
        "source_url": url,
        "issuing_body": infer_issuing_body(url),
        "publication_date": pub_date,
        "source_identifier": f"corpus-{source_id}",
        "title": title,
        "language": "en" if is_english else "zh",
        "canonical_policy_id": f"policy-{source_id}",
    }
    inferred = infer_document_meta(url, default_type="pdf")
    base_meta.update(inferred)
    return base_meta


def clear_corpus():
    """Remove existing corpus data (articles, pdfs, metadata, chunks)."""
    for d in (RAW_ARTICLES, RAW_PDFS):
        if d.exists():
            for f in d.iterdir():
                f.unlink()
    chunks_dir = DATA_DIR / "chunks"
    if chunks_dir.exists():
        for f in chunks_dir.iterdir():
            f.unlink()
    meta_path = DATA_DIR / "metadata.json"
    if meta_path.exists():
        meta_path.unlink()
    print("Corpus cleared.")


def main():
    parser = argparse.ArgumentParser(description="Fetch corpus for Hainan FTP RAG (3-layer design: policy / implementation / English)")
    parser.add_argument("--clear", action="store_true", help="Clear existing corpus before fetch")
    parser.add_argument(
        "--rebuild-from-design",
        action="store_true",
        help="Clear corpus and rebuild from design source list only (TARGET_URLS + optional crawls)",
    )
    parser.add_argument(
        "--crawl-hainan",
        action="store_true",
        help="Breadth-first crawl en.hainan.gov.cn from seed pages (Layer 3 English)",
    )
    parser.add_argument(
        "--crawl-hnftp",
        action="store_true",
        help="Breadth-first crawl hnftp.gov.cn / policy.hnftp.gov.cn (Layer 1 Chinese policy)",
    )
    parser.add_argument(
        "--crawl-plan-hainan",
        action="store_true",
        help="Breadth-first crawl plan.hainan.gov.cn (Layer 2 Hainan DRC)",
    )
    parser.add_argument(
        "--crawl-haikou-customs",
        action="store_true",
        help="Breadth-first crawl haikou.customs.gov.cn (Layer 2 Haikou Customs, about 120 pages)",
    )
    parser.add_argument(
        "--crawl-departments",
        action="store_true",
        help="BFS crawl 7 department sites (business environment/SASAC/tourism/ecology/civil affairs/HRSS/health), max 120 pages per site, target 100+ pages each",
    )
    args = parser.parse_args()
    if args.rebuild_from_design or args.clear:
        clear_corpus()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_ARTICLES.mkdir(parents=True, exist_ok=True)
    RAW_PDFS.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    metadata_list: list[dict] = []
    seen_urls: set[str] = set()

    # When not clearing: load existing metadata and append new corpus items to avoid overwrite
    if not args.rebuild_from_design and not args.clear:
        meta_path = DATA_DIR / "metadata.json"
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                metadata_list = list(existing.get("documents", []))
                for doc in metadata_list:
                    u = doc.get("source_url") or ""
                    if u:
                        seen_urls.add(canonical_url(u))
                print(f"Loaded {len(metadata_list)} existing documents; will append new fetches.")
            except (json.JSONDecodeError, OSError):
                pass

    for i, url in enumerate(TARGET_URLS):
        print(f"[{i + 1}/{len(TARGET_URLS)}] {url[:70]}...")
        key = canonical_url(url)
        if key in seen_urls:
            print(f"  Skipped duplicate canonical URL: {url}")
            continue
        seen_urls.add(key)
        if is_pdf_url(url):
            meta = process_pdf(url, session)
        else:
            meta = process_html(url, session)
        if meta:
            metadata_list.append(meta)
            print(f"  -> {meta.get('file_path', '')}")
        time.sleep(REQUEST_DELAY)

    if args.crawl_hainan:
        print("\n=== Crawling en.hainan.gov.cn (broad topics) ===")
        crawl_hainan(session, seen_urls, metadata_list, max_pages=MAX_HAINAN_PAGES)

    if args.crawl_hnftp:
        print("\n=== Crawling hnftp.gov.cn (Chinese FTP authority portal) ===")
        crawl_hnftp(session, seen_urls, metadata_list, max_pages=MAX_HNFTP_PAGES)

    if args.crawl_plan_hainan:
        print("\n=== Crawling plan.hainan.gov.cn (Hainan DRC) ===")
        crawl_plan_hainan(session, seen_urls, metadata_list, max_pages=MAX_PLAN_HAINAN_PAGES)

    if args.crawl_haikou_customs:
        print("\n=== Crawling haikou.customs.gov.cn (Haikou Customs) ===")
        crawl_haikou_customs(session, seen_urls, metadata_list, max_pages=MAX_HAIKOU_CUSTOMS_PAGES)

    if args.crawl_departments:
        for domain, seeds, label in DEPARTMENT_CRAWLS:
            print(f"\n=== Crawling {domain} ({label}) ===")
            crawl_domain(session, seen_urls, metadata_list, domain, seeds, MAX_DEPARTMENT_PAGES, label)

    index_path = DATA_DIR / "metadata.json"
    index = {
        "corpus_version": "3-layer-design",
        "created_at": datetime.now().isoformat(),
        "total_documents": len(metadata_list),
        "documents": metadata_list,
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {len(metadata_list)} documents. Index: {index_path}")


if __name__ == "__main__":
    main()
