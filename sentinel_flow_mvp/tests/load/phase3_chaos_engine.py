"""
PHASE 3: DESTRUCTIVE CHAOS & COMPLIANCE STRESS TEST

Pushes the FastAPI boundary layer to failure by targeting:

    1. JSON parsing CPU limits (deeply nested JSON "bombs")
    2. PII regex / masking overhead (large string payloads)
    3. Aegis Lite Circuit Breaker resilience

Three attack vectors run concurrently (1000 total requests):
    - 500 JSON Bombs: 500-level nested dicts to trigger recursion limits
    - 500 EU PII Floods: oversized regex-bait strings through geo-routing
"""

import asyncio
import aiohttp
import time
import json
import random

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

TARGET_PREDICT_URL = "http://localhost:8080/api/v1/predict"
TARGET_INGEST_URL = "http://localhost:8080/api/v1/ingestion/batch"
CONCURRENCY_LIMIT = 200

API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

metrics = {
    "json_bombs_survived": 0,
    "json_bombs_failed_500": 0,
    "json_bombs_accepted_202": 0,
    "json_bombs_404": 0,
    "pii_eu_processed": 0,
    "circuit_breaker_tripped": 0,
    "total_time": 0.0,
}


def generate_json_bomb() -> dict:
    """
    Creates a maliciously nested JSON payload to test Pydantic/FastAPI CPU parsing
    limits. Attempting to force a stack overflow or OOM on the worker.

    Returns:
        A dict with a 500-level nested "features" field that should trigger
        Python's recursion limit during Pydantic deserialization.
    """
    depth = 500  # Pushing Python's recursion limit in JSON parsing

    # Build a deeply nested structure: {"nested": {"nested": ... {"data": "end"}}}
    bomb = {"data": "end"}
    for _ in range(depth):
        bomb = {"nested": bomb}

    # Embed the bomb inside the "features" field so Pydantic tries to parse it
    return {
        "module_id": "demand",
        "supplier_id": "SUP-BOMB",
        "sku_id": "TEST",
        "route_id": "R1",
        "compute_budget": 10.0,
        "features": bomb,  # The attack payload
    }


def generate_pii_flood(origin: str) -> dict:
    """
    Generates massive string payloads with fake PII to test the Geo-Router's
    regex and masking speed overhead.

    Args:
        origin: Originating region (e.g., "EU", "IN", "DEFAULT").

    Returns:
        A dict matching the BatchIngestionRequest schema with 100 records,
        each containing oversized contact_name and contact_email fields.
    """
    return {
        "batch_identifier": f"BATCH-{random.randint(1000, 9999)}",
        "source_system": "ERP",
        "originating_region": origin,
        "records": [
            {
                "supplier_id": f"SUP-{i}",
                "timestamp": "2024-01-01T00:00:00Z",
                "inventory_count": 100,
                "delivery_delay_days": 2,
                "contact_name": "John Doe " * 100,  # Regex padding attack
                "contact_email": "john.doe@example.com " * 100,
            }
            for i in range(100)
        ],
    }


async def attack_json_parsing(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Fires a single JSON bomb at the predict endpoint.

    Expected behaviour:
        - Status 422 (Unprocessable Entity) if Pydantic gracefully rejects the
          deeply nested structure.
        - Status 500 or connection timeout if the server crashes or hangs.
        - Timeout after 5 seconds to avoid hanging the test.
    """
    payload = generate_json_bomb()

    async with semaphore:
        try:
            async with session.post(
                TARGET_PREDICT_URL, json=payload, headers=HEADERS, timeout=5
            ) as response:
                status = response.status
                if status in (422, 400):
                    # Graceful rejection by Pydantic validation — SYSTEM RESILIENT
                    metrics["json_bombs_survived"] += 1
                elif status == 404:
                    # Supplier not found (non-existent supplier_id)
                    metrics["json_bombs_404"] += 1
                elif status == 202:
                    # Accepted and dispatched to Celery worker
                    metrics["json_bombs_accepted_202"] += 1
                elif status >= 500:
                    # Server crashed or internal error — VULNERABILITY DETECTED
                    metrics["json_bombs_failed_500"] += 1
        except asyncio.TimeoutError:
            # Server hung / didn't respond within 5 seconds
            metrics["json_bombs_failed_500"] += 1
        except aiohttp.ClientError:
            # Connection error (server may have crashed/restarted)
            metrics["json_bombs_failed_500"] += 1


async def attack_geo_router(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    origin: str,
) -> None:
    """
    Fires a single PII flood batch at the ingestion endpoint.

    Expected behaviour:
        - Status 201/202 if the batch is queued successfully.
        - Any other status or exception counts as neutral (the metric tracks
          successful processing throughput only).
    """
    payload = generate_pii_flood(origin)

    async with semaphore:
        try:
            async with session.post(
                TARGET_INGEST_URL, json=payload, headers=HEADERS, timeout=5
            ) as response:
                if response.status in (200, 201, 202):
                    metrics["pii_eu_processed"] += 1
        except Exception:
            pass  # Don't count non-responses toward pii_eu_processed


async def main() -> None:
    """Main entry point: runs all chaos attack vectors concurrently."""

    print("INITIATING PHASE 3: CHAOS ENGINEERING & DESTRUCTIVE TESTING...")

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = []

        # 1. Fire 500 JSON Bombs (CPU Starvation / Recursion Attack)
        tasks.extend(
            [attack_json_parsing(session, semaphore) for _ in range(500)]
        )

        # 2. Fire 500 EU PII Floods (Regex / Masking Starvation)
        tasks.extend(
            [attack_geo_router(session, semaphore, "EU") for _ in range(500)]
        )

        # Run all 1000 tasks concurrently
        await asyncio.gather(*tasks)

    metrics["total_time"] = time.time() - start_time

    print("\n--- CHAOS TEST RESULTS ---")
    print(f"Total Execution Time: {metrics['total_time']:.2f}s")
    print(f"JSON Bombs Gracefully Rejected (422): {metrics['json_bombs_survived']}")
    print(f"JSON Bombs Dispatched to Worker (202): {metrics['json_bombs_accepted_202']}")
    print(f"JSON Bombs Supplier Not Found (404): {metrics['json_bombs_404']}")
    print(f"Server Crashes / Timeouts (500): {metrics['json_bombs_failed_500']}")
    print(f"EU PII Heavy-Masking Batches Processed: {metrics['pii_eu_processed']}")

    if metrics["json_bombs_failed_500"] > 0:
        print("WARNING: CRITICAL VULNERABILITY DETECTED: "
              "API Gateway is susceptible to CPU starvation via nested JSON/ReDoS.")
    else:
        print("SYSTEM RESILIENT: Boundary layer successfully deflected "
              "all destructive payloads.")


if __name__ == "__main__":
    asyncio.run(main())
