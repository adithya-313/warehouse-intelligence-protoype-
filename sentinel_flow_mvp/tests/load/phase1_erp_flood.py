"""
PHASE 1: ERP DATA FLOOD & LOAD GENERATION

An asynchronous, high-performance load generator that simulates
a burst of warehouse telemetry data hitting the Redis Stream
ingestion endpoint (/api/v1/stream/telemetry).

Why this script exists:
    We need to verify the system can sustain high-throughput ingestion
    (50,000+ telemetry records) without connection starvation, 503
    errors, or Redis Stream backpressure. This script measures:
    - Raw throughput (requests/second)
    - HTTP error rates
    - Rate-limiting behavior (429 responses)

Architecture:
    asyncio       → Event loop for concurrent HTTP requests
    aiohttp       → Async HTTP client with connection pooling
    Semaphore(100)→ Prevents OS socket pool exhaustion
    generate_payload() → Creates 50 warehouse movement records per request
"""

import asyncio
import aiohttp
import time
import uuid
from datetime import datetime, timezone

# ------------------------------------------------------------------
# CONFIGURATION
# Modify these constants to control load test parameters.
# ------------------------------------------------------------------

# The FastAPI endpoint that accepts telemetry via Redis Stream
TARGET_URL = "http://localhost:8080/api/v1/stream/telemetry"

# API authentication header — the stream endpoint requires X-API-Key
# matching the API_KEY value in the .env file
API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

# Total number of HTTP requests to send
# Each request contains RECORDS_PER_REQUEST individual telemetry records
TOTAL_REQUESTS = 10

# Number of telemetry records packed into a single HTTP POST body
# 50 records per request × 1000 requests = 50,000 total records at full scale
RECORDS_PER_REQUEST = 50

# Maximum number of simultaneous HTTP connections
# 100 keeps the OS socket pool healthy while sustaining high throughput
CONCURRENCY_LIMIT = 100

# ------------------------------------------------------------------
# METRICS TRACKING
# A shared dictionary updated by each coroutine after its request completes.
# We use a plain dict (not a lock-protected one) because += on ints
# is atomic in CPython due to the GIL for simple operations.
# ------------------------------------------------------------------
metrics = {
    "success": 0,
    "rate_limited": 0,
    "failed": 0,
    "total_records_sent": 0,
}


def generate_payload() -> dict:
    """
    Generates a mock batch payload that matches the endpoint schema.

    The endpoint expects a JSON body with a single key "records"
    containing an array of movement telemetry objects. Each object
    has four fields matching the MovementTelemetryRecord Pydantic model:
        entity_id  : Unique identifier for the moving entity (robot/forklift/worker)
        entity_type: One of "robot", "forklift", "worker"
        node_id    : The warehouse location node where detected
        timestamp  : ISO 8601 timestamp of the detection event

    Returns:
        A dict ready to be serialised as JSON and POSTed to the API.
    """
    records = []
    for _ in range(RECORDS_PER_REQUEST):
        records.append({
            # Use a random suffix so each robot appears unique to the system
            "entity_id": f"ROBOT-{uuid.uuid4().hex[:6]}",
            "entity_type": "robot",
            # All robots move through the same picking zone for this test
            "node_id": "ZONE-A-PICKING",
            # Current UTC time forces a new hypertable partition each run
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return {"records": records}


async def send_request(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Sends a single HTTP POST request with semaphore-guarded concurrency.

    Steps:
        1. Acquire the semaphore (blocks if 100 connections are already in flight).
        2. POST the generated payload to the target endpoint.
        3. Classify the HTTP response status and update metrics accordingly.
        4. If the request itself throws (e.g., connection refused), count as failed.

    Args:
        session:   The shared aiohttp ClientSession for connection pooling.
        semaphore: Limits how many coroutines can enter this block simultaneously.
    """
    payload = generate_payload()

    # The semaphore ensures we never exceed CONCURRENCY_LIMIT simultaneous
    # outbound TCP connections. This prevents ephemeral port exhaustion.
    async with semaphore:
        try:
            # POST the payload as JSON. aiohttp automatically sets
            # Content-Type: application/json and serialises the dict.
            async with session.post(TARGET_URL, json=payload, headers=HEADERS) as response:
                status = response.status

                if status in (200, 201, 202):
                    # Successful ingestion — the API accepted the records
                    metrics["success"] += 1
                    metrics["total_records_sent"] += RECORDS_PER_REQUEST
                elif status == 429:
                    # Rate-limited — the API is throttling us
                    metrics["rate_limited"] += 1
                else:
                    # Any other status (404, 422, 500+) is a failure
                    metrics["failed"] += 1

        except Exception:
            # Network errors, DNS failures, connection refused, etc.
            metrics["failed"] += 1


async def main() -> None:
    """
    Main entry point: orchestrates the concurrent load test.

    Flow:
        1. Print the test configuration.
        2. Create an aiohttp ClientSession for connection pooling.
        3. Create TOTAL_REQUESTS coroutines, each sending one HTTP POST.
        4. Run all coroutines concurrently via asyncio.gather().
        5. Print the final metrics summary.
    """
    print(f"--- PHASE 1: ERP DATA FLOOD ---")
    print(f"Target: {TARGET_URL}")
    print(f"Requests: {TOTAL_REQUESTS}")
    print(f"Records per request: {RECORDS_PER_REQUEST}")
    print(f"Total records: {TOTAL_REQUESTS * RECORDS_PER_REQUEST}")
    print(f"Concurrency limit: {CONCURRENCY_LIMIT}")
    print()

    # Create the asyncio Semaphore that gates concurrent connections
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    # Record the wall-clock start time for throughput calculation
    start_time = time.time()

    # Use a single ClientSession for connection pooling.
    # aiohttp will reuse TCP connections (HTTP keep-alive) when possible,
    # which dramatically improves throughput vs. opening a new connection
    # for every request.
    async with aiohttp.ClientSession() as session:
        # Build a list of coroutine tasks — one per HTTP request
        tasks = [send_request(session, semaphore) for _ in range(TOTAL_REQUESTS)]

        # Execute all tasks concurrently. asyncio.gather() returns when
        # every single task has completed (or raised).
        await asyncio.gather(*tasks)

    end_time = time.time()
    duration = end_time - start_time
    requests_per_second = TOTAL_REQUESTS / duration if duration > 0 else 0.0

    # ------------------------------------------------------------------
    # RESULTS SUMMARY
    # ------------------------------------------------------------------
    print()
    print("--- LOAD TEST RESULTS ---")
    print(f"Duration:              {duration:.2f}s")
    print(f"Throughput:            {requests_per_second:.2f} req/s")
    print(f"Total records sent:    {metrics['total_records_sent']}")
    print(f"  Successful (2xx):    {metrics['success']}")
    print(f"  Rate-limited (429):  {metrics['rate_limited']}")
    print(f"  Failed (errors):     {metrics['failed']}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
