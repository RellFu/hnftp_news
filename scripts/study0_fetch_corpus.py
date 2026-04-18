#!/usr/bin/env python3
"""
Study 0 corpus collection: use Serper to find real article URLs, fetch content, and write into data/study0/.

Hainan corpus sources: Nanhai Net, Hainan Daily, Hainan Broadcasting Group, Xinhua Hainan, People.cn Hainan
Non-Hainan sources: Xinhua, People.cn, BBC, New York Times, Reuters, AFP

Dependencies: requests, trafilatura, beautifulsoup4; configure SERPER_API_KEY in `.env`.
Usage: run from project root
  python scripts/study0_fetch_corpus.py
  python scripts/study0_fetch_corpus.py --target 50  # 50 articles per class
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Load .env (project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)
except Exception:
    pass

import requests
from bs4 import BeautifulSoup

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

DATA_DIR = PROJECT_ROOT / "data"
STUDY0_DIR = DATA_DIR / "study0"
HAINAN_DIR = STUDY0_DIR / "hainan"
NON_HAINAN_DIR = STUDY0_DIR / "non_hainan"
MIN_TEXT_LEN = 200
REQUEST_DELAY = 2.0
SERPER_ENDPOINT = "https://google.serper.dev/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# URL host -> Study 0 selected source (Hainan)
HAINAN_HOST_TO_OUTLET = {
    "hinews.cn": "南海网",
    "www.hinews.cn": "南海网",
    "m.hinews.cn": "南海网",
    "hndaily.com.cn": "海南日报",
    "www.hndaily.com.cn": "海南日报",
    "bluehn.com": "海南广播电视总台",
    "www.bluehn.com": "海南广播电视总台",
    "hnr.cn": "海南广播电视总台",
    "hainan.xinhuanet.com": "新华网海南频道",
    "www.hainan.xinhuanet.com": "新华网海南频道",
    "hq.xinhuanet.com": "新华网海南频道",
    "hi.people.com.cn": "人民网海南频道",
    "hainan.people.com.cn": "人民网海南频道",
}

# Non-Hainan
NON_HAINAN_HOST_TO_OUTLET = {
    "xinhuanet.com": "新华社",
    "www.xinhuanet.com": "新华社",
    "news.cn": "新华社",
    "www.news.cn": "新华社",
    "people.com.cn": "人民日报",
    "www.people.com.cn": "人民日报",
    "bbc.com": "BBC",
    "www.bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "reuters.com": "路透社",
    "www.reuters.com": "路透社",
    "nytimes.com": "纽约时报",
    "www.nytimes.com": "纽约时报",
    "afp.com": "法新社",
    "www.afp.com": "法新社",
}

# Serper search: (query, expected source) used to collect URLs
HAINAN_QUERIES = [
    ("海南 自贸港 site:hinews.cn", "南海网"),
    ("海南 发展 site:hinews.cn", "南海网"),
    ("海南 政策 site:hndaily.com.cn", "海南日报"),
    ("海南 自贸港 site:hndaily.com.cn", "海南日报"),
    ("海南 site:bluehn.com", "海南广播电视总台"),
    ("海南 site:hnr.cn", "海南广播电视总台"),
    ("海南 site:hainan.xinhuanet.com", "新华网海南频道"),
    ("海南 site:hq.xinhuanet.com", "新华网海南频道"),
    ("海南 site:hi.people.com.cn", "人民网海南频道"),
    ("海南 site:hainan.people.com.cn", "人民网海南频道"),
]
NON_HAINAN_QUERIES = [
    ("经济 政策 site:xinhuanet.com", "新华社"),
    ("时政 site:people.com.cn", "人民日报"),
    ("China economy site:bbc.com", "BBC"),
    ("China policy site:reuters.com", "路透社"),
    ("China site:nytimes.com", "纽约时报"),
    ("China site:afp.com", "法新社"),
    ("policy site:bbc.com", "BBC"),
    ("business site:reuters.com", "路透社"),
]


def _serper_search(query: str, num: int = 20, api_key: str = "") -> list[dict]:
    """Return list of {title, link, snippet} from Serper."""
    if not api_key or not api_key.strip():
        return []
    try:
        r = requests.post(
            SERPER_ENDPOINT,
            headers={"X-API-KEY": api_key.strip(), "Content-Type": "application/json"},
            json={"q": query[:200], "num": min(num, 20)},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        organic = data.get("organic") or data.get("organicResults") or []
        out = []
        for item in organic:
            link = (item.get("link") or item.get("url") or "").strip()
            if link:
                out.append({
                    "title": (item.get("title") or "")[:200],
                    "link": link,
                    "snippet": (item.get("snippet") or "")[:300],
                })
        return out
    except Exception as e:
        print(f"  Serper error for '{query[:50]}': {e}", flush=True)
        return []


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower().replace("www.", "")


def _outlet_for_hainan(url: str) -> str | None:
    h = _host(url)
    for suffix, outlet in HAINAN_HOST_TO_OUTLET.items():
        if suffix in h or h == suffix:
            return outlet
    return None


def _outlet_for_non_hainan(url: str) -> str | None:
    h = _host(url)
    for suffix, outlet in NON_HAINAN_HOST_TO_OUTLET.items():
        if suffix in h or h == suffix:
            return outlet
    return None


def _decode_html(content: bytes, resp: requests.Response) -> str:
    enc = resp.encoding or ""
    if not enc or enc.lower() == "iso-8859-1":
        m = re.search(rb'charset\s*=\s*["\']?([\w-]+)', content[:5000], re.I)
        enc = m.group(1).decode("ascii", errors="ignore") if m else "utf-8"
    for try_enc in (enc, "utf-8"):
        try:
            return content.decode(try_enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _extract_date(soup: BeautifulSoup, url: str) -> str:
    for sel in ['meta[property="article:published_time"]', 'meta[name="publishdate"]', 'meta[name="date"]']:
        tag = soup.select_one(sel)
        if tag:
            val = tag.get("content") or tag.get("value")
            if val:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", str(val))
                if m:
                    return m.group(1)
    m = re.search(r"/(\d{4})[/-]?(\d{2})[/-]?(\d{2})/", url) or re.search(r"(\d{4})-(\d{2})-(\d{2})", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return time.strftime("%Y-%m-%d")


def _extract_title(soup: BeautifulSoup, url: str) -> str:
    t = soup.find("title")
    if t and t.get_text(strip=True):
        return t.get_text(strip=True)[:200]
    p = urlparse(url).path.strip("/").split("/")[-1]
    return (p or "untitled").replace(".shtml", "").replace(".html", "")[:200]


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", s)[:40].strip() or "article"
    return re.sub(r"\s+", "-", s) or hashlib.md5(s.encode()).hexdigest()[:8]


def fetch_and_extract(url: str, session: requests.Session) -> dict | None:
    """Fetch URL, extract title + text; return dict with title, text, publication_date or None."""
    try:
        r = session.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        r.raise_for_status()
        if not r.content or len(r.content) < 100:
            return None
        html = _decode_html(r.content, r)
        soup = BeautifulSoup(html, "html.parser")
        title = _extract_title(soup, url)
        pub_date = _extract_date(soup, url)
        content = ""
        if HAS_TRAFILATURA:
            content = trafilatura.extract(html) or ""
        if not content or len(content.strip()) < MIN_TEXT_LEN:
            content = soup.get_text(separator="\n\n", strip=True)[:50000]
        if not content.strip() or len(content) < MIN_TEXT_LEN:
            return None
        return {"title": title, "text": content, "publication_date": pub_date, "url": url}
    except Exception as e:
        print(f"    Fetch/extract failed: {e}", flush=True)
        return None


def collect_urls(queries: list[tuple[str, str]], api_key: str, max_per_query: int = 20) -> list[tuple[str, str]]:
    """Return list of (url, outlet)."""
    seen = set()
    out = []
    for q, outlet in queries:
        results = _serper_search(q, num=max_per_query, api_key=api_key)
        for item in results:
            link = item.get("link", "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            out.append((link, outlet))
        time.sleep(1.2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Study 0: collect real Hainan/non-Hainan reporting corpus")
    parser.add_argument("--target", type=int, default=100, help="Target article count per class")
    parser.add_argument("--serper-num", type=int, default=20, help="Result count returned by each Serper query")
    parser.add_argument("--dry-run", action="store_true", help="Print planned searches only; do not fetch")
    args = parser.parse_args()

    api_key = __import__("os").environ.get("SERPER_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("Please configure SERPER_API_KEY in the project-root .env", file=sys.stderr)
        return 1

    STUDY0_DIR.mkdir(parents=True, exist_ok=True)
    HAINAN_DIR.mkdir(parents=True, exist_ok=True)
    NON_HAINAN_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    # 1) Hainan: collect URLs (keep only links from allowed sources)
    print("Collecting Hainan URLs via Serper...", flush=True)
    hainan_urls_raw = collect_urls(HAINAN_QUERIES, api_key, args.serper_num)
    hainan_urls = []
    for url, _ in hainan_urls_raw:
        outlet = _outlet_for_hainan(url)
        if outlet:
            hainan_urls.append((url, outlet))
    print(f"  Hainan URLs (from allowed outlets): {len(hainan_urls)}", flush=True)
    if args.dry_run:
        for u, o in hainan_urls[:15]:
            print(f"    {o}: {u[:70]}...")
        return 0

    # 2) Non-Hainan: collect URLs
    print("Collecting non-Hainan URLs via Serper...", flush=True)
    non_hainan_urls_raw = collect_urls(NON_HAINAN_QUERIES, api_key, args.serper_num)
    non_hainan_urls = []
    for url, _ in non_hainan_urls_raw:
        outlet = _outlet_for_non_hainan(url)
        if outlet:
            non_hainan_urls.append((url, outlet))
    print(f"  Non-Hainan URLs (from allowed outlets): {len(non_hainan_urls)}", flush=True)

    # 3) Fetch Hainan articles until target is reached
    hainan_docs = []
    for i, (url, outlet) in enumerate(hainan_urls):
        if len(hainan_docs) >= args.target:
            break
        print(f"  Fetching Hainan [{len(hainan_docs)+1}/{args.target}] {outlet} ...", flush=True)
        data = fetch_and_extract(url, session)
        if not data:
            time.sleep(REQUEST_DELAY)
            continue
        doc_id = f"hainan-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
        slug = _slug(data["title"]) or doc_id
        fname = f"{data['publication_date']}_{slug}.md"
        out_path = HAINAN_DIR / fname
        if out_path.exists():
            out_path = HAINAN_DIR / f"{out_path.stem}_{doc_id[:8]}.md"
        out_path.write_text(data["text"], encoding="utf-8")
        rel_path = f"hainan/{out_path.name}"
        hainan_docs.append({
            "doc_id": doc_id,
            "source": outlet,
            "publication_date": data["publication_date"],
            "title": data["title"],
            "file_path": rel_path,
            "url": url,
        })
        time.sleep(REQUEST_DELAY)
    print(f"Hainan: {len(hainan_docs)} articles saved.", flush=True)

    # 4) Fetch non-Hainan articles until target is reached
    non_hainan_docs = []
    for url, outlet in non_hainan_urls:
        if len(non_hainan_docs) >= args.target:
            break
        print(f"  Fetching non-Hainan [{len(non_hainan_docs)+1}/{args.target}] {outlet} ...", flush=True)
        data = fetch_and_extract(url, session)
        if not data:
            time.sleep(REQUEST_DELAY)
            continue
        doc_id = f"nonhainan-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
        slug = _slug(data["title"]) or doc_id
        fname = f"{data['publication_date']}_{slug}.md"
        out_path = NON_HAINAN_DIR / fname
        if out_path.exists():
            out_path = NON_HAINAN_DIR / f"{out_path.stem}_{doc_id[:8]}.md"
        out_path.write_text(data["text"], encoding="utf-8")
        rel_path = f"non_hainan/{out_path.name}"
        non_hainan_docs.append({
            "doc_id": doc_id,
            "source": outlet,
            "publication_date": data["publication_date"],
            "title": data["title"],
            "file_path": rel_path,
            "url": url,
        })
        time.sleep(REQUEST_DELAY)
    print(f"Non-Hainan: {len(non_hainan_docs)} articles saved.", flush=True)

    # 5) Write manifests (Study 0 requires: doc_id, source, publication_date, title, file_path)
    hainan_manifest = {
        "description": "Hainan corpus: Nanhai Net, Hainan Daily, Hainan Broadcasting Group, Xinhua Hainan, People.cn Hainan. Isolated from the project main corpus.",
        "documents": [{"doc_id": d["doc_id"], "source": d["source"], "publication_date": d["publication_date"], "title": d["title"], "file_path": d["file_path"]} for d in hainan_docs],
    }
    non_hainan_manifest = {
        "description": "Non-Hainan corpus: Xinhua, People.cn, BBC, New York Times, Reuters, AFP. Isolated from the project main corpus.",
        "documents": [{"doc_id": d["doc_id"], "source": d["source"], "publication_date": d["publication_date"], "title": d["title"], "file_path": d["file_path"]} for d in non_hainan_docs],
    }
    (STUDY0_DIR / "hainan_manifest.json").write_text(json.dumps(hainan_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (STUDY0_DIR / "non_hainan_manifest.json").write_text(json.dumps(non_hainan_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {STUDY0_DIR / 'hainan_manifest.json'} ({len(hainan_docs)} docs)", flush=True)
    print(f"Wrote {STUDY0_DIR / 'non_hainan_manifest.json'} ({len(non_hainan_docs)} docs)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
