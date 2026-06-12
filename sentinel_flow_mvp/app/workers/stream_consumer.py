"""Stream Consumer — Redis Consumer Group Worker for Telemetry Ingestion.

This standalone worker script connects to the `telemetry_stream` Redis
Stream as part of a consumer group named `telemetry_group`. It reads
batches of up to 1000 messages, bulk-inserts them into the
`movement_telemetry` TimescaleDB hypertable, and acknowledges each
message via `xack` to prevent the Pending Entries List (PEL) from
overflowing.

Domain-Driven Design context:
- Consumer groups provide at-least-once delivery semantics.
- Bulk inserts minimise database connection overhead.
- Explicit `xack` prevents the PEL from growing indefinitely, which
  would degrade Redis memory and performance.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import configure_logging
# Configure JSON structured logging for the consumer process globally at the top
configure_logging(level=logging.INFO, json_output=True)
logger = logging.getLogger(__name__)

import redis

from app.infrastructure.database import SessionLocal

REDIS_STREAM_URL: str = "redis://localhost:6379/0"
TELEMETRY_STREAM_KEY: str = "telemetry_stream"
CONSUMER_GROUP_NAME: str = "telemetry_group"
CONSUMER_NAME: str = "stream_consumer_1"

# Number of messages to read in a single xreadgroup call
BATCH_SIZE: int = 1000

# How long to block waiting for new messages (milliseconds)
BLOCK_TIMEOUT_MS: int = 2000


def parse_record_from_message(
    message_payload: bytes,
) -> Optional[Dict[str, Any]]:
    """Parse a single Redis Stream message payload into a record dict.

    Each message in the stream stores the telemetry record as a JSON
    string under the field name "payload". This function deserialises
    it and returns a dictionary.

    Args:
        message_payload: The raw bytes value from the Redis Stream message.

    Returns:
        A dictionary with 'entity_id', 'entity_type', 'node_id', 'timestamp'
        keys, or None if parsing fails.
    """
    try:
        record_dictionary: Dict[str, Any] = json.loads(message_payload)
        return record_dictionary

    except (json.JSONDecodeError, TypeError) as parse_error:

        logger.error(
            f"Failed to parse stream message payload: {str(parse_error)}"
        )
        return None


def bulk_insert_records(
    database_session: Any,
    parsed_records: List[Dict[str, Any]],
) -> int:
    """Legacy telemetry persistence — deprecated with warehouse domain purge.

    The MovementTelemetryModel table has been dropped. This function
    acknowledges and discards any remaining stream messages.
    """
    logger.warning(
        "Discarding %d legacy movement telemetry records (warehouse domain purged).",
        len(parsed_records),
    )
    return 0


def run_stream_consumer() -> None:
    """Run the Redis Stream consumer group worker loop.

    This function:
    1. Connects to Redis and creates the consumer group (if it does not
       already exist).
    2. Enters a `while True` loop that reads messages from the stream in
       batches using `xreadgroup`.
    3. For each batch, opens a DB session, inserts the records, and
       acknowledges the messages.

    The consumer is designed to run as a standalone process (e.g., via
    `python -m app.workers.stream_consumer`).
    """
    logger.info("=" * 60)
    logger.info("  STREAM CONSUMER — Starting up")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Connect to Redis
    # ------------------------------------------------------------------
    redis_connection: redis.Redis = redis.Redis.from_url(
        REDIS_STREAM_URL,
        decode_responses=True,
    )

    # ------------------------------------------------------------------
    # Step 2: Create the consumer group (if it does not already exist)
    # ------------------------------------------------------------------
    try:
        redis_connection.xgroup_create(
            name=TELEMETRY_STREAM_KEY,
            groupname=CONSUMER_GROUP_NAME,
            id="0",
            mkstream=True,
        )
        logger.info(
            f"Consumer group '{CONSUMER_GROUP_NAME}' created on "
            f"stream '{TELEMETRY_STREAM_KEY}'."
        )

    except redis.exceptions.ResponseError as group_error:

        error_message: str = str(group_error)

        # BUSYGROUP Consumer Group name already exists — this is normal
        # on subsequent runs. We log it as info and continue.
        if "BUSYGROUP" in error_message:
            logger.info(
                f"Consumer group '{CONSUMER_GROUP_NAME}' already exists "
                f"(normal on restart). Continuing..."
            )
        else:
            logger.error(
                f"Failed to create consumer group: {error_message}"
            )
            return

    logger.info(
        f"Starting main loop (batch_size={BATCH_SIZE}, "
        f"block_timeout={BLOCK_TIMEOUT_MS}ms)..."
    )

    # ------------------------------------------------------------------
    # Step 3: Main consumer loop
    # ------------------------------------------------------------------
    loop_iteration_count: int = 0

    while True:

        loop_iteration_count += 1

        try:
            # ------------------------------------------------------------------
            # Step 3a: Read a batch of messages from the stream
            # ------------------------------------------------------------------
            stream_messages: List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]

            stream_messages = redis_connection.xreadgroup(
                groupname=CONSUMER_GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={TELEMETRY_STREAM_KEY: ">"},
                count=BATCH_SIZE,
                block=BLOCK_TIMEOUT_MS,
            )

            # ------------------------------------------------------------------
            # Step 3b: If there are no messages, skip this iteration
            # ------------------------------------------------------------------
            if not stream_messages:
                continue

            # ------------------------------------------------------------------
            # Step 3c: Parse all messages from all returned streams
            # ------------------------------------------------------------------
            all_message_ids: List[str] = []
            all_parsed_records: List[Dict[str, Any]] = []

            for stream_name, messages in stream_messages:

                for message_id, message_fields in messages:

                    all_message_ids.append(message_id)

                    raw_payload: Optional[str] = message_fields.get("payload")

                    if raw_payload is not None:
                        parsed_record = parse_record_from_message(
                            message_payload=raw_payload,
                        )

                        if parsed_record is not None:
                            all_parsed_records.append(parsed_record)

            if not all_message_ids:
                continue

            # ------------------------------------------------------------------
            # Step 3d: Open a DB session and bulk-insert the records
            # Retry loop: up to 3 attempts with exponential backoff (60s base)
            # to handle transient DB failures without losing stream messages.
            # ------------------------------------------------------------------
            max_retries: int = 3
            retry_delay_seconds: float = 60.0
            last_error: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                database_session = SessionLocal()
                try:
                    inserted_count: int = bulk_insert_records(
                        database_session=database_session,
                        parsed_records=all_parsed_records,
                    )

                    # Acknowledge (xack) all processed message IDs if successful
                    if inserted_count > 0:
                        redis_connection.xack(
                            name=TELEMETRY_STREAM_KEY,
                            groupname=CONSUMER_GROUP_NAME,
                            *all_message_ids,
                        )
                        logger.info(
                            f"Iteration {loop_iteration_count}: "
                            f"inserted {inserted_count} records, "
                            f"acked {len(all_message_ids)} messages "
                            f"(attempt {attempt})."
                        )

                    last_error = None
                    break  # Exit retry loop on success

                except Exception as processing_error:
                    database_session.rollback()
                    last_error = processing_error
                    logger.error(
                        f"Iteration {loop_iteration_count}, "
                        f"attempt {attempt}/{max_retries}: "
                        f"bulk insert failed — {str(processing_error)}"
                    )
                    if attempt < max_retries:
                        backoff_seconds = retry_delay_seconds * (2 ** (attempt - 1))
                        logger.info(
                            f"Retrying in {backoff_seconds:.0f}s "
                            f"(attempt {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(backoff_seconds)

                finally:
                    database_session.close()

            # After exhausting all retries, log critical failure but do not
            # xack the messages — they will remain in the PEL for manual
            # inspection or a later consumer restart.
            if last_error is not None:
                logger.critical(
                    f"Iteration {loop_iteration_count}: "
                    f"bulk insert failed after {max_retries} retries. "
                    f"Messages NOT acknowledged — pending in PEL. "
                    f"Last error: {str(last_error)}"
                )

        except redis.exceptions.ConnectionError as connection_error:

            logger.error(
                f"Redis connection lost: {str(connection_error)}. "
                f"Reconnecting in 5 seconds..."
            )
            time.sleep(5)

        except Exception as unexpected_error:

            logger.error(
                f"Unexpected consumer error: {str(unexpected_error)}"
            )
            time.sleep(1)


if __name__ == "__main__":
    run_stream_consumer()
