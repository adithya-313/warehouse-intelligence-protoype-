"""Redis Stream Benchmark — Proving the Performance Delta.

This script stress-tests the new Redis Stream ingestion architecture by
sending a batch of 10,000 movement telemetry records to the
`/api/v1/stream/telemetry` endpoint.

Purpose:
    Mathematically prove the performance improvement over the baseline
    HTTP + Celery architecture. The payload size (10,000 records) and
    structure are IDENTICAL to the baseline benchmark so the results
    are directly comparable.

    Expected outcome:
        Baseline (HTTP + Celery):  ~100–500 ms per 10,000 records.
        Redis Stream (O(1) xadd):   ~5–50 ms per 10,000 records.

    The delta is the mathematical proof that offloading parse + dispatch
    to Redis Streams eliminates the synchronous bottleneck.

Domain-Driven Design context:
    The Stream endpoint bypasses Pydantic model validation on the event
    loop and writes directly to Redis using O(1) `xadd`. The consumer
    group processes records asynchronously, so the client never blocks.
"""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

import requests


def generate_payload() -> Dict[str, Any]:
    """Generate a MovementTelemetryBatch payload with 10,000 dummy records.

    This function is an EXACT DUPLICATE of the baseline benchmark's
    generator. Payload structure and size are identical to ensure
    a strict 1:1 comparison between the two architectures.

    Returns:
        A dictionary ready to be serialised as JSON and sent to the
        Redis Stream telemetry endpoint.
    """
    current_time = datetime.utcnow()
    batch_id_value = str(uuid.uuid4())

    all_records: List[Dict[str, Any]] = []

    for record_index in range(10_000):

        entity_type_choice: str
        if record_index % 3 == 0:
            entity_type_choice = "forklift"
        elif record_index % 3 == 1:
            entity_type_choice = "robot"
        else:
            entity_type_choice = "worker"

        single_record: Dict[str, Any] = {
            "entity_id": f"entity_{record_index:05d}",
            "entity_type": entity_type_choice,
            "node_id": f"node_{record_index % 50:02d}",
            "timestamp": current_time.isoformat(),
        }

        all_records.append(single_record)

    payload: Dict[str, Any] = {
        "batch_id": batch_id_value,
        "records": all_records,
    }

    return payload


def run_benchmark() -> None:
    """Execute the Redis Stream benchmark against the new architecture.

    Sends a single POST request containing 10,000 telemetry records to the
    `/api/v1/stream/telemetry` endpoint. Measures the wall-clock time until
    the HTTP 202 Accepted response is received.

    The measured time represents the Redis O(1) `xadd` write latency,
    NOT the end-to-end processing time (which is handled asynchronously
    by the consumer group worker).

    Returns:
        None. Prints the benchmark results directly to the console.
    """
    target_url = "http://localhost:8080/api/v1/stream/telemetry"
    total_records = 10_000

    print("=" * 65)
    print("  REDIS STREAM BENCHMARK — O(1) xadd Ingestion")
    print("=" * 65)
    print(f"  Endpoint: {target_url}")
    print(f"  Target:   {total_records:,} records")
    print(f"  Method:   POST (raw JSON, no Pydantic parse)")
    print("-" * 65)

    # ------------------------------------------------------------------
    # Step 1: Build the payload (does NOT count toward benchmark time)
    # ------------------------------------------------------------------
    print("  [BUILD] Generating 10,000-record payload...")
    payload = generate_payload()
    print(f"  [BUILD] Payload generated (batch_id={payload['batch_id']})")

    # ------------------------------------------------------------------
    # Step 2: Send the request and measure HTTP acceptance time
    # ------------------------------------------------------------------
    start_time = time.perf_counter()

    try:
        http_response = requests.post(
            url=target_url,
            json=payload,
            timeout=120.0,
        )

        end_time = time.perf_counter()

    except requests.exceptions.ConnectionError:
        print("\n  [ERROR] Could not connect to the server.")
        print("  [ERROR] Is the FastAPI application running on port 8000?")
        return

    except requests.exceptions.Timeout:
        print("\n  [ERROR] Request timed out after 120 seconds.")
        print("  [ERROR] The server may be overloaded or unreachable.")
        return

    # ------------------------------------------------------------------
    # Step 3: Calculate and display the results
    # ------------------------------------------------------------------
    elapsed_seconds = end_time - start_time
    throughput = total_records / elapsed_seconds

    print("-" * 65)
    print(f"  HTTP Response Code:     {http_response.status_code}")
    print(f"  API Response Time (Redis O(1) Write): "
          f"{elapsed_seconds:.4f} seconds")
    print(f"  Throughput:             {throughput:,.0f} records/second")
    print("-" * 65)

    # ------------------------------------------------------------------
    # Step 4: Interpretation note
    # ------------------------------------------------------------------
    print("  NOTE: This measures the Redis Stream acceptance time only.")
    print("  The consumer group worker reads from the stream and")
    print("  bulk-inserts to the database asynchronously.")
    print("=" * 65)


if __name__ == "__main__":
    run_benchmark()
