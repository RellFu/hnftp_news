"""
Serper.dev Google Search API client for Reactive workflow.
Set SERPER_API_KEY in .env. Returns organic results (title, link, snippet).
"""

import logging
import time
from typing import Optional

import requests

from app.core.config import SERPER_API_KEY, SERPER_ENDPOINT

logger = logging.getLogger(__name__)

# Retries for transient SSL/network errors (e.g. UNEXPECTED_EOF_WHILE_READING)
SERPER_MAX_RETRIES = 2
SERPER_RETRY_DELAY = 1.0


def _latin1_safe(s: str) -> str:
    return "".join(c for c in (s or "") if ord(c) < 256)


def _user_facing_error(e: Exception) -> str:
    """Short message for UI; full details go to logs."""
    if isinstance(e, requests.exceptions.SSLError):
        return "Serper request failed (SSL or network). Check your network, VPN, or firewall; try again later."
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "Serper request failed (connection or timeout). Check your network or try again."
    return f"Serper request failed: {getattr(e, 'message', str(e))[:120]}"


def serper_search(
    query: str,
    num: int = 10,
    timeout: int = 15,
    date_restrict: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """
    Search the web via Serper. Returns (list of {title, link, snippet}, error_message).
    error_message is None on success, or a short reason string on failure.
    date_restrict: optional recency filter, e.g. "d3" (past 3 days), "d1" (past day), "w1" (past week).
    Serper may support dateRestrict in the request body; if not, it is ignored.
    """
    if not SERPER_API_KEY or not SERPER_API_KEY.strip():
        return [], "SERPER_API_KEY not set; add it to .env"
    q = (query or "").strip()[:200]
    if not q:
        return [], "Query is empty"

    body: dict = {"q": q, "num": min(num, 20)}
    if date_restrict:
        body["dateRestrict"] = date_restrict

    last_error = None
    for attempt in range(SERPER_MAX_RETRIES + 1):
        try:
            r = requests.post(
                SERPER_ENDPOINT,
                headers={
                    "X-API-KEY": SERPER_API_KEY.strip(),
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.HTTPError as e:
            msg = f"Serper HTTP error: {e.response.status_code}"
            try:
                body = (e.response.text or "")[:200]
                if body:
                    msg += f" — {body}"
            except Exception:
                pass
            logger.warning("serper_search failed: %s", msg)
            return [], msg
        except requests.exceptions.Timeout:
            logger.warning("serper_search timeout for q=%s", q[:50])
            return [], "Serper request timeout"
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            last_error = e
            logger.warning("serper_search attempt %s: %s", attempt + 1, e, exc_info=(attempt == SERPER_MAX_RETRIES))
            if attempt < SERPER_MAX_RETRIES:
                time.sleep(SERPER_RETRY_DELAY)
            continue
        except Exception as e:
            logger.warning("serper_search error: %s", e, exc_info=True)
            return [], _user_facing_error(e)
    else:
        assert last_error is not None
        return [], _user_facing_error(last_error)
    organic = data.get("organic") or data.get("organicResults") or []
    out = []
    for item in organic[:num]:
        title = item.get("title") or ""
        link = item.get("link") or item.get("url") or ""
        snippet = item.get("snippet") or item.get("description") or ""
        out.append({"title": _latin1_safe(title), "link": _latin1_safe(link), "snippet": _latin1_safe(snippet)})
    return out, None
