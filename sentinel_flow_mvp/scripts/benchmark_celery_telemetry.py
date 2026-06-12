"""Baseline Benchmark — Current HTTP + Celery Telemetry Ingestion.

This script stress-tests the existing ingestion architecture by sending
a batch of 10,000 movement telemetry records via the synchronous HTTP API.

Purpose:
    Establish a performance baseline before replacing the ingestion layer
    with Redis Streams. We measure the HTTP API acceptance time (how long
    FastAPI takes to parse, validate, and return a 202 Accepted response).
    The actual Celery async processing happens in the background and is
    NOT measured here.

Domain-Driven Design context:
    The current architecture requires the client to send all 10,000 records
    in a single HTTP request body. This creates a synchronous bottleneck:
    the client blocks until the API finishes parsing and dispatching to
    Celery. Redis Streams will later decouple this by allowing the client
    to publish records continuously without blocking.
"""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

import requests


def generate_payload() -> Dict[str, Any]:
    """Generate a MovementTelemetryBatch payload with 10,000 dummy records.

    Each record contains randomised but structurally valid data that
    perfectly matches the `MovementTelemetryBatch` / `MovementTelemetryRecord`
    schemas defined in `app/domain/schemas.py`.

    Returns:
        A dictionary ready to be serialised as JSON and sent to the
        telemetry ingestion endpoint.
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
    """Execute the baseline benchmark against the current ingestion pipeline.

    Sends a single POST request containing 10,000 telemetry records to the
    `/api/v1/warehouse/telemetry/batch` endpoint. Measures the wall-clock
    time until the HTTP response is received.

    Returns:
        None. Prints the benchmark results directly to the console.
    """
    target_url = "http://localhost:8080/api/v1/warehouse/telemetry/batch"
    total_records = 10_000

    print("=" * 65)
    print("  BASELINE BENCHMARK — HTTP + Celery Telemetry Ingestion")
    print("=" * 65)
    print(f"  Endpoint: {target_url}")
    print(f"  Target:   {total_records:,} records")
    print(f"  Method:   POST (synchronous HTTP to FastAPI)")
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
    print(f"  HTTP API Response Time: {elapsed_seconds:.4f} seconds")
    print(f"  Throughput:             {throughput:,.0f} records/second")
    print("-" * 65)

    # ------------------------------------------------------------------
    # Step 4: Interpretation note
    # ------------------------------------------------------------------
    print("  NOTE: This measures only the API acceptance time.")
    print("  Celery is processing the records asynchronously in the")
    print("  background. Total E2E latency (accept + process) will be")
    print("  higher than the value reported above.")
    print("=" * 65)


if __name__ == "__main__":
    run_benchmark()
