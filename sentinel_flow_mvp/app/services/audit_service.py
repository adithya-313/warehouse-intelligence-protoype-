"""Shared audit logging helper for recording data changes.

Beginner Note — Why does this file exist?

    Every time a mutating endpoint (create, update, delete) runs in the
    system, we want a record of what changed, who changed it, and when.
    Instead of writing the same audit-insert code in every endpoint, we
    put it here once and import it wherever needed.

    This is called the "DRY principle" — Don't Repeat Yourself. If the
    audit table schema ever changes, we only need to update this one file.

How does atomicity work?

    This function adds an AuditLogModel row to the database session but
    does NOT call db.commit(). The calling endpoint's own db.commit()
    covers both the real business change and this audit entry together,
    atomically. This means:

      - If the business change succeeds, the audit row is also saved.
      - If either fails, both are rolled back — no half-written state.
      - There is no separate transaction or connection for audit logging.

    This is critical: if audit logging used its own commit, you could end
    up with a situation where the audit log says a change happened but the
    actual data doesn't reflect it (or vice versa). Sharing the transaction
    prevents this entirely.
"""

import logging
from sqlalchemy.orm import Session

from app.infrastructure.models import AuditLogModel

logger = logging.getLogger(__name__)


def log_audit_event(
    db: Session,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    action_type: str,
    old_value: dict = None,
    new_value: dict = None,
    extra_metadata: dict = None,
) -> None:
    """Record a single audit event in the current database transaction.

    This function is the primary way to write to the audit_logs table.
    It creates an AuditLogModel row and adds it to the given session,
    but deliberately does NOT commit. The caller's own db.commit()
    will persist both the business change and this audit entry together.

    Args:
        db: The active SQLAlchemy session. Must be the same session used
            for the business operation so they share a transaction.
        tenant_id: The tenant (pharmacy) performing this action. Obtained
            from Depends(get_current_tenant) in FastAPI endpoints.
        entity_type: The kind of record being changed, e.g. "purchase_order",
            "medication_batch", "patient". Use lowercase snake_case.
        entity_id: The specific record's primary key, e.g. "PO-abc123".
        action_type: What happened — must be "CREATE", "UPDATE", or "DELETE".
        old_value: JSON-serializable dict of the record BEFORE the change.
            Should be None for CREATE actions (no previous state exists).
            For UPDATE actions, include only the fields that changed.
        new_value: JSON-serializable dict of the record AFTER the change.
            Should be None for DELETE actions (no remaining state).
        extra_metadata: Any additional context worth capturing, e.g.
            {"endpoint": "/api/v1/purchase-orders/receive", "ip": "10.0.0.1"}.

    Returns:
        None. The audit row is added to the session but not committed.
    """
    entry = AuditLogModel(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action_type=action_type,
        old_value=old_value,
        new_value=new_value,
        extra_metadata=extra_metadata,
    )
    db.add(entry)

    logger.debug(
        "Audit event recorded: %s %s/%s by tenant %s (will commit with caller)",
        action_type,
        entity_type,
        entity_id,
        tenant_id,
    )
