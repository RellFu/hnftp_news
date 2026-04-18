"""
OpenAI-compatible LLM client for pitch generation.

Uses requests (not httpx) to avoid ascii codec issues in some environments.
Set LLM_API_KEY (or OPENAI_API_KEY). Optionally LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SEC.
Retries on transient errors (ChunkedEncodingError, ConnectionError, Timeout, ProtocolError).
"""

import json
import re
import time
from typing import Optional

from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SEC

# Transient errors that are worth retrying (e.g. response ended prematurely, connection reset).
LLM_RETRY_EXCEPTIONS = (
    "ChunkedEncodingError",
    "ConnectionError",
    "Timeout",
    "ProtocolError",
    "ReadTimeout",
    "ConnectTimeout",
)


def _ascii_safe(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"[^\x00-\x7F]+", "?", s)


def _latin1_safe(s: str) -> str:
    """Keep only chars with ord < 256 (HTTP headers use Latin-1). Use for URL/headers, not key content."""
    if not s or not isinstance(s, str):
        return ""
    return "".join(c for c in s if ord(c) < 256)


def call_chat(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    timeout_sec: Optional[int] = None,
    ascii_safe_user: bool = True,
) -> str:
    """Call OpenAI-compatible chat API via requests. When ascii_safe_user=False, user content may contain UTF-8 (e.g. Chinese)."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("Install requests: pip install requests")

    system = _ascii_safe(system)
    if ascii_safe_user:
        user = _ascii_safe(user)
    else:
        user = (user or "").strip()
    base = _latin1_safe(LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    model = _ascii_safe(model or LLM_MODEL)
    timeout = timeout_sec if timeout_sec is not None else LLM_TIMEOUT_SEC
    # Headers must be Latin-1; strip any BOM or non-Latin-1 from key
    auth_header = _latin1_safe(f"Bearer {LLM_API_KEY}")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    body_bytes = json.dumps(body, ensure_ascii=True).encode("utf-8")
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json; charset=utf-8",
    }

    last_exc = None
    for attempt in range(3):
        try:
            r = requests.post(url, data=body_bytes, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = json.loads(r.content.decode("utf-8"))
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("Empty LLM response")
            content = (choices[0].get("message") or {}).get("content") or ""
            return content.strip()
        except Exception as e:
            last_exc = e
            exc_name = type(e).__name__
            if exc_name in LLM_RETRY_EXCEPTIONS and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise ValueError("Empty LLM response")


def extract_json_from_response(text: str) -> dict:
    """Extract a single JSON object from LLM output (handles markdown code blocks)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = m.group(1).strip() if m else text
    return json.loads(raw)
