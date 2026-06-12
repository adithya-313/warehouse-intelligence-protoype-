"""
PHASE 2: ML ORCHESTRATOR & HYPERVISOR STRESS TEST — DRY RUN

An asynchronous stress test that fires POST requests to /api/v1/predict
and polls /api/v1/tasks/{task_id} to measure true end-to-end ML inference time.

Three attack vectors:
    A — LoRA Thrashing (different suppliers -> forces adapter swaps under lock)
    B — Mutex Race Lock (identical suppliers -> tests asyncio.Lock() stability)
    C — Budget Starvation (negative budget -> hypervisor bypasses ML)

Architecture:
    asyncio       -> Event loop for concurrent HTTP + polling
    aiohttp       -> Async HTTP client
    fire_and_poll -> POSTs predict, then polls task status until SUCCESS/FAILURE
    run_attack_vector -> Orchestrates a batch of concurrent payloads with metrics
"""

import asyncio
import aiohttp
import time

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

PREDICT_URL = "http://localhost:8080/api/v1/predict"
TASK_URL = "http://localhost:8080/api/v1/tasks"
REQUESTS_PER_VECTOR = 2   # Dry-run: small batch to verify queue + polling
POLL_INTERVAL = 0.5        # Seconds between task status checks

# API key for authenticated endpoints
API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

# Real supplier IDs from the database
SUPPLIERS = [
    "NVIDIA", "AMD Inc", "Intel Corp", "ASUS Global",
    "Corsair Components", "NVIDIA Corporation", "AMD",
]


async def poll_task(
    session: aiohttp.ClientSession,
    task_id: str,
) -> dict:
    """
    Continuously polls the Celery task endpoint until the task finishes.

    Args:
        session: The shared aiohttp ClientSession.
        task_id: The UUID of the Celery task returned by /predict.

    Returns:
        A dict with 'status', 'latency' (seconds), and optional 'data'.
    """
    start_poll = time.time()

    while True:
        # GET /api/v1/tasks/{task_id} to check the background worker status
        async with session.get(
            f"{TASK_URL}/{task_id}", headers=HEADERS
        ) as response:
            # If the endpoint itself returns an error, bail out
            if response.status != 200:
                return {
                    "status": "HTTP_ERROR",
                    "latency": time.time() - start_poll,
                }

            # Parse the JSON response
            data = await response.json()

            # Once the Celery worker completes, the status becomes
            # SUCCESS or FAILURE. We stop polling and return.
            task_status = data.get("status")
            if task_status in ("SUCCESS", "FAILURE"):
                return {
                    "status": task_status,
                    "latency": time.time() - start_poll,
                    "data": data,
                }

        # No result yet -- wait before polling again
        await asyncio.sleep(POLL_INTERVAL)


async def fire_and_poll(
    session: aiohttp.ClientSession,
    payload: dict,
    vector_name: str,
    metrics: dict,
) -> None:
    """
    Fires a single POST /predict request, then polls until the task finishes.

    There are two possible paths:
        1. The hypervisor routes to the HEURISTIC_FALLBACK (budget <= 0):
           The response is immediate (no Celery task_id returned).
        2. The hypervisor routes to the BASE or LoRA model:
           A Celery task_id is returned, and we must poll for completion.

    Args:
        session:     The shared aiohttp ClientSession.
        payload:     The JSON body for the POST /predict request.
        vector_name: Name of the test vector for metrics grouping.
        metrics:     Shared dict tracking success/fail/latency per vector.
    """
    queue_start = time.time()

    try:
        # STEP 1: Fire the POST /predict request
        async with session.post(
            PREDICT_URL, json=payload, headers=HEADERS
        ) as response:
            # If the API rejects the request, count it as a failure
            if response.status not in (200, 201, 202):
                metrics[vector_name]["failed"] += 1
                return

            # Parse the response to extract the Celery task_id
            post_data = await response.json()
            task_id = post_data.get("task_id")

            # If there is no task_id, the hypervisor chose the synchronous
            # HEURISTIC_FALLBACK path. The response IS the final result.
            if not task_id:
                metrics[vector_name]["success"] += 1
                metrics[vector_name]["latencies"].append(
                    time.time() - queue_start
                )
                return

        # STEP 2: Poll the Celery task status until it completes
        task_result = await poll_task(session, task_id)

        if task_result["status"] == "SUCCESS":
            metrics[vector_name]["success"] += 1
            metrics[vector_name]["latencies"].append(task_result["latency"])
        else:
            metrics[vector_name]["failed"] += 1

    except Exception:
        # Any network error, timeout, or parsing failure
        metrics[vector_name]["failed"] += 1


async def run_attack_vector(
    session: aiohttp.ClientSession,
    vector_name: str,
    payloads: list,
    metrics: dict,
) -> None:
    """
    Executes a batch of payloads concurrently and prints the results.

    Args:
        session:     The shared aiohttp ClientSession.
        vector_name: Human-readable label (e.g., "Vector A [LoRA Thrashing]").
        payloads:    List of dict payloads to POST concurrently.
        metrics:     Shared dict updated by each fire_and_poll call.
    """
    print(f"\nInitiating {vector_name} ...")
    metrics[vector_name] = {"success": 0, "failed": 0, "latencies": []}

    start_time = time.time()

    # Create one fire_and_poll task per payload and run them concurrently
    tasks = [
        fire_and_poll(session, payload, vector_name, metrics)
        for payload in payloads
    ]
    await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    avg_latency = (
        sum(metrics[vector_name]["latencies"])
        / len(metrics[vector_name]["latencies"])
        if metrics[vector_name]["latencies"]
        else 0.0
    )

    print(f"  Success: {metrics[vector_name]['success']}")
    print(f"  Failed: {metrics[vector_name]['failed']}")
    print(f"  Avg latency: {avg_latency:.2f}s")
    print(f"  Total time: {total_time:.2f}s")


async def main() -> None:
    """Main entry point: generates payloads and runs all three attack vectors."""

    # ------------------------------------------------------------------
    # Vector A: LoRA Thrashing
    # REQUESTS_PER_VECTOR requests, each with a DIFFERENT supplier_id
    # (cycling through the 7 real suppliers).
    # This forces the orchestrator to constantly swap LoRA adapters,
    # exercising the asyncio.Lock() around load_adapter().
    # ------------------------------------------------------------------
    payloads_a = [
        {
            "module_id": "demand_forecast",
            "supplier_id": SUPPLIERS[i % len(SUPPLIERS)],
            "sku_id": "TEST",
            "route_id": "R1",
            "compute_budget": 15.0,
        }
        for i in range(REQUESTS_PER_VECTOR)
    ]

    # ------------------------------------------------------------------
    # Vector B: Mutex Race Lock
    # REQUESTS_PER_VECTOR requests, ALL using the SAME supplier_id.
    # This tests whether the asyncio.Lock() correctly serialises adapter
    # access when multiple requests arrive simultaneously.
    # ------------------------------------------------------------------
    payloads_b = [
        {
            "module_id": "demand_forecast",
            "supplier_id": "NVIDIA",
            "sku_id": "TEST",
            "route_id": "R1",
            "compute_budget": 15.0,
        }
        for _ in range(REQUESTS_PER_VECTOR)
    ]

    # ------------------------------------------------------------------
    # Vector C: Budget Starvation
    # REQUESTS_PER_VECTOR requests with compute_budget = -1.0 (exhausted).
    # The hypervisor should immediately route ALL of these to the
    # zero-cost HEURISTIC_FALLBACK, bypassing Celery entirely.
    # These should return significantly faster than Vectors A and B.
    # ------------------------------------------------------------------
    payloads_c = [
        {
            "module_id": "demand_forecast",
            "supplier_id": SUPPLIERS[i % len(SUPPLIERS)],
            "sku_id": "TEST",
            "route_id": "R1",
            "compute_budget": -1.0,
        }
        for i in range(REQUESTS_PER_VECTOR)
    ]

    metrics = {}

    # Use a single ClientSession for connection pooling across all vectors
    async with aiohttp.ClientSession() as session:
        await run_attack_vector(
            session, "Vector A [LoRA Thrashing]", payloads_a, metrics
        )
        await run_attack_vector(
            session, "Vector B [Mutex Race Lock]", payloads_b, metrics
        )
        await run_attack_vector(
            session, "Vector C [Budget Starvation]", payloads_c, metrics
        )


if __name__ == "__main__":
    asyncio.run(main())
