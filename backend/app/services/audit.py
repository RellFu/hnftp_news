"""
Audit logging per design doc 2.3/3.1.

Per request records:
- Retrieved document identifiers, span identifiers
- Filter settings
- Prompt and model versions
- Latency
- Downgrade labels
"""

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AUDIT_FILE = PROJECT_ROOT / "data" / "audit_log.jsonl"


class AuditEntry(BaseModel):
    """Single audit log entry per request."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    endpoint: str = ""
    retrieval_doc_ids: list[str] = Field(default_factory=list)
    retrieval_span_ids: list[str] = Field(default_factory=list)
    filter_settings: dict = Field(default_factory=dict)
    prompt_version: str = "v1"
    llm_version: str = "unconfigured"
    latency_ms: float = 0.0
    downgrade_labels: list[str] = Field(default_factory=list)
    evidence_sufficient: Optional[bool] = None
    timeout: Optional[bool] = None


_entries: list[AuditEntry] = []


def log_audit(entry: AuditEntry) -> None:
    """Append audit entry to in-memory store and optionally persist."""
    _entries.append(entry)
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
    except OSError:
        pass


def get_audit_entries(limit: int = 100) -> list[AuditEntry]:
    """Return recent audit entries (newest first)."""
    return list(reversed(_entries[-limit:]))


def get_audit_by_id(request_id: str) -> Optional[AuditEntry]:
    """Return audit entry by request_id."""
    for e in reversed(_entries):
        if e.request_id == request_id:
            return e
    return None
