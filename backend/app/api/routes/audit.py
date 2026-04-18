"""Audit log API routes."""

from fastapi import APIRouter, HTTPException

from app.services.audit import get_audit_entries, get_audit_by_id

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit_log(limit: int = 100):
    """List recent audit entries."""
    entries = get_audit_entries(limit=limit)
    return {"entries": [e.model_dump() for e in entries], "total": len(entries)}


@router.get("/{request_id}")
async def get_audit_entry(request_id: str):
    """Get single audit entry by request_id."""
    entry = get_audit_by_id(request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    return entry.model_dump()
