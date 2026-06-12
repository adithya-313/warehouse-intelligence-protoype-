"""Immutable Audit Ledger API Routes.

This module exposes endpoints for recording auditable events into the
immutable PostgreSQL/TimescaleDB ledger for fraud detection and compliance.

Domain-Driven Design context:
- Every financial or inventory change must be recorded immutably.
- The ledger is backed by a PostgreSQL trigger that enforces immutability
  by blocking UPDATE and DELETE operations.
- Fraud analysis is triggered asynchronously via Celery after event ingestion.
- Rate limiting (velocity) and deduplication (transaction_id) prevent abuse.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.schemas import (
    AnomalyScoreResponse,
    AuditEventPayload,
    AuditEventType,
)
from app.infrastructure.database import get_database_session
from app.infrastructure.db.models import AuditAnomalyScore, AuditLedger
from app.services.velocity_service import VelocityRateLimiter
from app.workers.audit_worker import analyze_fraud_event_task

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()


@router.post(
    path="/event",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnomalyScoreResponse,
    summary="Ingest an auditable event with velocity & dedup checks",
    description="Records an event in the immutable audit ledger. Enforces "
    "Redis-based rate limiting and database-level transaction deduplication.",
)
async def ingest_audit_event(
    event_payload: AuditEventPayload,
    database_session: Session = Depends(get_database_session),
    velocity_limiter: VelocityRateLimiter = Depends(VelocityRateLimiter),
) -> AnomalyScoreResponse:
    """Record an auditable event with rate limiting and deduplication.

    This endpoint performs three layers of protection before persisting:
    1. Velocity check: limits how many events an entity can submit per window.
    2. Dedup check: unique index on transaction_id prevents duplicate financial events.
    3. Immutable storage: event is written to the audit_ledger with a tamper-proof trigger.

    Args:
        event_payload: The audit event details.
        database_session: Injected SQLAlchemy session.
        velocity_limiter: Injected Redis-based rate limiter.

    Returns:
        AnomalyScoreResponse with the event ID and a pending status.
    """
    # Step 1: Generate a unique event identifier
    event_id = str(uuid4())
    logger.info(
        f"Audit event received: type={event_payload.event_type.value}, "
        f"entity={event_payload.entity_id}, event_id={event_id}"
    )

    # Step 2: Check entity velocity before touching the database
    # This prevents rapid-fire submissions from a single entity
    # If the limit is exceeded, an HTTP 429 exception is raised automatically
    await velocity_limiter.check_velocity(
        entity_id=event_payload.entity_id,
        event_type=event_payload.event_type.value,
    )

    try:
        # Step 3: Persist the event to the immutable audit_ledger table
        # The PostgreSQL trigger will prevent any future modification or deletion
        ledger_entry = AuditLedger(
            id=event_id,
            event_type=event_payload.event_type.value,
            entity_id=event_payload.entity_id,
            sku_id=event_payload.sku_id,
            amount_value=event_payload.amount_value,
            event_metadata=dict(event_payload.metadata),
        )
        database_session.add(ledger_entry)
        database_session.commit()

        logger.info(f"Audit event {event_id} committed to immutable ledger.")

        # Step 4: Trigger asynchronous fraud analysis via Celery
        # The worker will score the event and persist results to audit_anomaly_scores
        analyze_fraud_event_task.delay(event_id)
        logger.info(f"Fraud analysis triggered asynchronously for event {event_id}.")

        # Step 5: Return pending status immediately
        return AnomalyScoreResponse(
            event_id=event_id,
            risk_score=0.0,
            is_flagged=False,
            reason="Fraud analysis triggered asynchronously. Check back using GET /event/{event_id}/score.",
        )

    except IntegrityError:
        # Step 6: Handle duplicate transaction_id violations
        # The database-level unique index caught a duplicate submission
        database_session.rollback()
        logger.warning(
            f"Duplicate event rejected: entity={event_payload.entity_id}, "
            f"event_id={event_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate transaction_id detected. Event rejected.",
        )

    except Exception as error:
        database_session.rollback()
        logger.error(f"Failed to persist audit event: {str(error)}")
        raise


@router.get(
    path="/event/{event_id}/score",
    response_model=AnomalyScoreResponse,
    summary="Get anomaly score for an audit event",
    description="Retrieves the fraud/anomaly score for a previously ingested event.",
)
def get_event_anomaly_score(
    event_id: str,
    database_session: Session = Depends(get_database_session),
) -> AnomalyScoreResponse:
    """Retrieve the anomaly score for a specific audit event.

    Queries the audit_anomaly_scores table (separate from the immutable ledger)
    and returns the risk assessment. Returns 404 if the event doesn't exist
    or hasn't been scored yet.

    Args:
        event_id: The UUID of the audit event to query.
        database_session: Injected SQLAlchemy session.

    Returns:
        AnomalyScoreResponse with the risk score.

    Raises:
        HTTPException 404: If the event or score is not found.
    """
    # Step 1: Check if the event exists in the ledger
    audit_event = database_session.query(AuditLedger).filter(
        AuditLedger.id == event_id
    ).first()

    if audit_event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event '{event_id}' not found.",
        )

    # Step 2: Query the anomaly score from the separate scores table
    anomaly_record = database_session.query(AuditAnomalyScore).filter(
        AuditAnomalyScore.event_id == event_id
    ).first()

    if anomaly_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Anomaly score for event '{event_id}' not yet available. "
                   f"Fraud analysis may still be in progress.",
        )

    # Step 3: Return the score response
    return AnomalyScoreResponse(
        event_id=anomaly_record.event_id,
        risk_score=anomaly_record.risk_score,
        is_flagged=anomaly_record.is_flagged,
        reason=anomaly_record.reason,
    )
