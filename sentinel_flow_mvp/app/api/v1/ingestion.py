"""Ingestion API routes.

This module defines all API endpoints related to data ingestion.
Routes follow RESTful conventions and return appropriate response contracts.
"""

import json
import logging
import os
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_application_settings
from app.core.exceptions import raise_http_exception
from app.domain.schemas import (
    BatchIngestionRequest,
    PredictionResponse,
)
from app.services.ingestion_service import queue_batch_for_processing

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()

# Idempotency cache TTL: 24 hours in seconds
IDEMPOTENCY_TTL_SECONDS: int = 86400


def _get_idempotency_redis() -> aioredis.Redis:
    """Create a Redis connection for the idempotency cache."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.from_url(redis_url, decode_responses=True)


class BatchResponse(BaseModel):
    job_id: str
    status: str
    message: str


@router.post(
    path="/batch",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_batch(
    batch_request: BatchIngestionRequest,
    x_idempotency_key: str = Header(
        default=None,
        description="Unique key to prevent duplicate batch processing (24h TTL).",
    ),
) -> BatchResponse:
    """Ingest multiple data payloads in a single request.

    This endpoint accepts multiple data payloads and queues them
    for asynchronous processing by the Celery worker.
    Supports idempotent submission via X-Idempotency-Key header:
    - First call with a given key: processes and caches the response (24h TTL).
    - Subsequent calls with the same key: returns the cached response without
      re-triggering the Celery task.
    """
    # Idempotency check: if an X-Idempotency-Key is provided, check Redis
    # for a previously-computed result to prevent duplicate task spawning.
    if x_idempotency_key:
        redis_client = _get_idempotency_redis()
        try:
            cached_result = await redis_client.get(
                f"idempotency:{x_idempotency_key}"
            )
            if cached_result is not None:
                logger.info(
                    "Idempotency HIT for key=%s — returning cached response.",
                    x_idempotency_key,
                )
                cached_data = json.loads(cached_result)
                await redis_client.aclose()
                return BatchResponse(**cached_data)
        except Exception as cache_error:
            logger.warning(
                "Idempotency cache read failed for key=%s: %s. "
                "Proceeding without cache.",
                x_idempotency_key,
                str(cache_error),
            )

    try:
        # Process the batch through the ingestion service (dispatches to Celery)
        response = queue_batch_for_processing(
            batch_payload=batch_request,
        )

        # Cache the response under the idempotency key with 24h TTL
        if x_idempotency_key:
            redis_client = _get_idempotency_redis()
            try:
                serialized = json.dumps(response)
                await redis_client.setex(
                    f"idempotency:{x_idempotency_key}",
                    IDEMPOTENCY_TTL_SECONDS,
                    serialized,
                )
                logger.info(
                    "Idempotency cache SET for key=%s (TTL=%ds).",
                    x_idempotency_key,
                    IDEMPOTENCY_TTL_SECONDS,
                )
            except Exception as cache_error:
                logger.warning(
                    "Idempotency cache write failed for key=%s: %s.",
                    x_idempotency_key,
                    str(cache_error),
                )
            finally:
                await redis_client.aclose()

        logger.info(
            "Batch queued: idempotency_key=%s, job_id=%s",
            x_idempotency_key or "NONE",
            response.get("job_id", "UNKNOWN"),
        )
        return BatchResponse(**response)

    except Exception as exception:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to queue batch for processing",
            error_code="BATCH_QUEUED_FAILED",
            details=str(exception),
        )


@router.get(
    path="/health",
)
async def health_check() -> dict:
    """Check the health status of the application."""
    try:
        application_settings = get_application_settings()
        return {
            "application_name": application_settings.application_name,
            "application_version": application_settings.application_version,
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as exception:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Health check failed",
            error_code="HEALTH_CHECK_FAILED",
            details=str(exception),
        )