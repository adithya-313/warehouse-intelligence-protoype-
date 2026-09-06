"""Audit log read endpoint.

Provides a paginated, tenant-isolated view of all audit events recorded
in the audit_logs table. This is the read side of the audit system —
the write side lives in purchase_order_router.py (and will expand to
other mutating endpoints over time).

Beginner Note — Why tenant isolation matters here:

    Every query on this endpoint MUST filter by tenant_id. Without this
    filter, Tenant A could see Tenant B's audit entries, which reveals
    what medications they ordered, when, and from which suppliers. This
    is the exact bug class we fixed in Phase A (the /history cross-tenant
    leak). We never repeat that mistake.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.infrastructure.database import get_database_session
from app.infrastructure.models import AuditLogModel
from app.api.dependencies import get_current_tenant

router = APIRouter()


@router.get("")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_database_session),
):
    """Fetch a paginated, tenant-isolated list of audit log entries.

    Query Parameters:
        limit: Number of items per page (1-200, default 50).
        offset: Number of items to skip (for pagination, default 0).
        entity_type: Optional filter — e.g. "purchase_order", "medication_batch".
        action_type: Optional filter — e.g. "CREATE", "UPDATE", "DELETE".

    Returns:
        {items, total, limit, offset} — same shape as the supplier list endpoint.
    """
    # Build the base query with mandatory tenant filter.
    # Beginner Note: This is the non-negotiable line that prevents
    # cross-tenant data leakage. Every query on this endpoint starts here.
    query = db.query(AuditLogModel).filter(AuditLogModel.tenant_id == tenant_id)

    # Apply optional filters
    if entity_type:
        query = query.filter(AuditLogModel.entity_type == entity_type)
    if action_type:
        query = query.filter(AuditLogModel.action_type == action_type)

    # Count total matching rows (for frontend pagination UI)
    total = query.count()

    # Fetch the page, most recent first
    items = (
        query
        .order_by(desc(AuditLogModel.timestamp))
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Transform ORM objects to dicts for JSON serialization
    serialized = []
    for item in items:
        serialized.append({
            "id": item.id,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "tenant_id": item.tenant_id,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "action_type": item.action_type,
            "old_value": item.old_value,
            "new_value": item.new_value,
            "extra_metadata": item.extra_metadata,
        })

    return {
        "items": serialized,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
