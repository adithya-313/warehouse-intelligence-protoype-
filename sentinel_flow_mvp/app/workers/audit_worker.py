"""Audit Fraud Analysis Worker.

This Celery worker processes audit events asynchronously, scoring them
with the Isolation Forest model and persisting the results to the
audit_anomaly_scores table.

Domain-Driven Design context:
- Fraud analysis is decoupled from the API ingestion to avoid blocking
  the event submission flow.
- Results are written to a SEPARATE table (audit_anomaly_scores) to
  maintain the immutability guarantee of the audit_ledger.
"""

import logging

from sqlalchemy.orm import Session

from app.core.celery_app import celery_application
from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import AuditAnomalyScore, AuditLedger
from app.ml.fraud_model import FraudDetectionModel

logger = logging.getLogger(__name__)

# Instantiate the fraud detection model once at module load time
# This ensures the Isolation Forest is fit with synthetic data on worker boot
fraud_detector = FraudDetectionModel()


@celery_application.task(name="analyze_fraud_event")
def analyze_fraud_event_task(event_id: str) -> str:
    """Score an audit event for fraud and persist the result.

    This task is triggered asynchronously by the POST /audit/event endpoint.
    It fetches the event from the immutable ledger, runs it through the
    Isolation Forest model, and saves the anomaly score.

    Args:
        event_id: The UUID of the audit event to analyze.

    Returns:
        Status message indicating the result of the analysis.
    """
    logger.info(f"Starting fraud analysis for event: {event_id}")

    database_session: Session = SessionLocal()

    try:
        # Step 1: Fetch the audit event from the immutable ledger
        audit_event = database_session.query(AuditLedger).filter(
            AuditLedger.id == event_id
        ).first()

        if audit_event is None:
            error_message = f"Audit event {event_id} not found."
            logger.error(error_message)
            return error_message

        # Step 2: Run the event through the fraud detection model
        risk_score, is_flagged, reason = fraud_detector.predict(
            event_type=audit_event.event_type,
            amount_value=audit_event.amount_value,
        )

        # Step 3: Persist the anomaly score to the separate audit_anomaly_scores table
        # Using a separate table ensures the audit_ledger remains immutable
        anomaly_record = AuditAnomalyScore(
            event_id=event_id,
            risk_score=risk_score,
            is_flagged=is_flagged,
            reason=reason,
        )
        database_session.add(anomaly_record)
        database_session.commit()

        logger.info(
            f"Fraud analysis complete for event {event_id}: "
            f"risk={risk_score:.4f}, flagged={is_flagged}"
        )

        return f"Fraud analysis complete for event {event_id}."

    except Exception as execution_error:
        database_session.rollback()
        logger.error(f"Fraud analysis failed for event {event_id}: {str(execution_error)}")
        raise

    finally:
        database_session.close()
