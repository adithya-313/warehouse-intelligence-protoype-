"""Redis Stream Ingestion Router — High-Throughput Telemetry Producer.

This router provides a fast-path streaming endpoint that accepts raw
telemetry records and pushes them into a Redis Stream (`telemetry_stream`)
using O(1) `xadd` operations. This decouples the client from the Celery
worker queue and allows continuous, non-blocking ingestion.

Domain-Driven Design context:
- The Stream replaces the synchronous HTTP → Celery path for telemetry.
- The endpoint reads the raw JSON body directly (no Pydantic parse on the
  event loop) to maximise throughput under high load.
- Each record is individualy pushed to the Stream so partial failures do
  not block the entire batch.
"""

import json
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()

# Redis connection string — uses the REDIS_URL env var set by docker-compose
# Falls back to localhost for local development.
REDIS_STREAM_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TELEMETRY_STREAM_KEY: str = "telemetry_stream"

# Maximum number of records accepted in a single request to limit memory use
MAX_RECORDS_PER_REQUEST: int = 50_000


@router.post(
    path="/telemetry",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["stream"],
    summary="Ingest telemetry via Redis Stream",
    description="Accept raw telemetry records and push each one to a Redis Stream. "
    "Returns 202 Accepted immediately. The stream consumer processes "
    "records asynchronously.",
)
async def ingest_telemetry_stream(
    request: Request,
) -> Dict[str, Any]:
    """High-throughput telemetry ingestion via Redis Stream.

    This endpoint reads the raw JSON body directly to avoid blocking the
    event loop with Pydantic validation of large payloads. Each record is
    pushed to the `telemetry_stream` Redis Stream using `xadd`.

    Args:
        request: The raw FastAPI Request object.

    Returns:
        A dictionary with the count of records accepted and the stream key.
    """
    # ------------------------------------------------------------------
    # Step 1: Read the raw JSON body as a Python dictionary
    # ------------------------------------------------------------------
    raw_body: Dict[str, Any] = await request.json()

    all_records: List[Dict[str, Any]] = raw_body.get("records", [])

    total_record_count: int = len(all_records)

    logger.info(
        f"Stream ingestion received {total_record_count} records."
    )

    # ------------------------------------------------------------------
    # Step 2: Enforce a maximum record limit per request
    # ------------------------------------------------------------------
    if total_record_count > MAX_RECORDS_PER_REQUEST:

        logger.warning(
            f"Record count {total_record_count} exceeds maximum "
            f"{MAX_RECORDS_PER_REQUEST}. Truncating."
        )

        all_records = all_records[:MAX_RECORDS_PER_REQUEST]
        total_record_count = len(all_records)

    # ------------------------------------------------------------------
    # Step 3: Open a Redis connection and push each record to the Stream
    # ------------------------------------------------------------------
    redis_connection: aioredis.Redis = aioredis.from_url(REDIS_STREAM_URL)

    try:
        # ------------------------------------------------------------------
        # Step 3a: Create an async pipeline to batch all xadd commands
        # Pipeline buffers commands and sends them in a single network
        # round-trip, eliminating the per-record I/O bottleneck.
        # ------------------------------------------------------------------
        redis_pipeline = redis_connection.pipeline()

        for each_record in all_records:

            # Convert the record dict to a JSON string so Redis stores it
            # as a single field-value pair called "payload"
            record_as_json: str = json.dumps(each_record, default=str)

            # NOTE: No `await` here — pipeline queues the command locally
            redis_pipeline.xadd(
                name=TELEMETRY_STREAM_KEY,
                fields={"payload": record_as_json},
                maxlen=1_000_000,
            )

        # Execute all queued xadd commands in a single network call
        await redis_pipeline.execute()

    except Exception as stream_error:

        logger.error(
            f"Redis Stream xadd failed: {str(stream_error)}"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": f"Stream write failed: {str(stream_error)}",
                "error_code": "STREAM_WRITE_FAILED",
                "records_accepted": 0,
            },
            headers={"Retry-After": "5"},
        )

    finally:

        await redis_connection.aclose()

    # ------------------------------------------------------------------
    # Step 4: Return 202 Accepted with a summary
    # ------------------------------------------------------------------
    logger.info(
        f"Pushed {total_record_count} records to stream "
        f"'{TELEMETRY_STREAM_KEY}'."
    )

    return {
        "accepted": True,
        "message": "Records accepted and queued in Redis Stream.",
        "records_accepted": total_record_count,
        "stream_key": TELEMETRY_STREAM_KEY,
    }
