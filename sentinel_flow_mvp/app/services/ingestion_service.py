"""Ingestion Service Domain Logic.

Handles the orchestration of incoming data batches and passes them to the Celery worker queue.
"""

import uuid
from typing import Dict

from app.domain.schemas import BatchIngestionRequest
from app.services.regional_router import RegionalComplianceRouter
from app.services.worker_tasks import process_batch_payload_task


def queue_batch_for_processing(batch_payload: BatchIngestionRequest) -> Dict[str, str]:
    """Accepts a validated ingestion payload, generates a tracking ID, and queues it for background processing via Celery.

    Compliance intercept:
        BEFORE any data enters the async queue, the payload is passed through
        `RegionalComplianceRouter.anonymize_batch()`. This guarantees that
        region-specific PII redaction happens synchronously, at ingress time,
        so no unredacted PII ever reaches the worker or database.

    Args:
        batch_payload: The validated data contract containing supplier records.

    Returns:
        A dictionary containing the generated job tracking ID and the initial status.
    """
    tracking_job_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # COMPLIANCE INTERCEPT: Route through regional state machine FIRST.
    # The sanitized payload (with PII redacted per region rules) is what
    # gets serialized and dispatched to the Celery worker.
    # ------------------------------------------------------------------
    sanitized_payload = RegionalComplianceRouter.anonymize_batch(
        batch_request=batch_payload,
    )

    payload_dictionary = sanitized_payload.model_dump()

    process_batch_payload_task.delay(payload_dictionary, tracking_job_id)

    response_metadata = {
        "job_id": tracking_job_id,
        "status": "QUEUED",
        "message": f"Batch {batch_payload.batch_identifier} accepted and queued for processing.",
    }

    return response_metadata