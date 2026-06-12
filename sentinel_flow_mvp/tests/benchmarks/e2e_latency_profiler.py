"""
E2E LATENCY PROFILER — measures p50/p95/p99 across all system arteries.

Runs 200 concurrent requests per route and computes percentiles from
the sorted latency distribution.
"""

import asyncio
import aiohttp
import json
import time

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

BASE_URL = "http://localhost:8080/api/v1"
REQUESTS_PER_ROUTE = 200
CONCURRENCY = 20  # Must stay under DB pool (size=20, overflow=10) to avoid QueuePool exhaustion

API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

STREAM_PAYLOAD = {
    "records": [
        {
            "entity_id": "TEST-1",
            "entity_type": "robot",
            "node_id": "A1",
            "timestamp": "2024-01-01T00:00:00Z",
        }
    ]
}

PREDICT_PAYLOAD = {
    "module_id": "demand_forecast",
    "supplier_id": "NVIDIA",
    "sku_id": "SKU-1",
    "route_id": "R1",
    "compute_budget": 100.0,
}

ROUTE_PAYLOAD = {
    "source_id": "ZONE-A",
    "target_id": "ZONE-B",
    "entity_type": "robot",
}


def calculate_percentiles(latencies: list) -> tuple:
    """Calculate p50, p95, p99 latencies from a list of times in seconds."""
    if not latencies:
        return 0.0, 0.0, 0.0
    s = sorted(latencies)
    n = len(s)
    p50 = s[int(n * 0.5)]
    p95 = s[int(n * 0.95)]
    p99 = s[int(n * 0.99)]
    return p50, p95, p99


async def benchmark_route(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    name: str,
    method: str,
    url: str,
    payload: dict = None,
) -> dict:
    """Fire concurrent requests at a specific endpoint to measure latency."""
    latencies = []
    errors = 0

    async def make_request() -> None:
        nonlocal errors
        start_time = time.time()
        async with semaphore:
            try:
                if method == "GET":
                    async with session.get(url, headers=HEADERS, timeout=30) as resp:
                        if resp.status >= 400 and resp.status != 422:
                            errors += 1
                else:
                    async with session.post(
                        url, json=payload, headers=HEADERS, timeout=30
                    ) as resp:
                        if resp.status >= 400 and resp.status != 422:
                            errors += 1
            except Exception:
                errors += 1
        latencies.append(time.time() - start_time)

    tasks = [make_request() for _ in range(REQUESTS_PER_ROUTE)]
    await asyncio.gather(*tasks)

    p50_s, p95_s, p99_s = calculate_percentiles(latencies)
    return {
        "route_name": name,
        "p50_ms": round(p50_s * 1000, 2),
        "p95_ms": round(p95_s * 1000, 2),
        "p99_ms": round(p99_s * 1000, 2),
        "error_rate_percent": round((errors / REQUESTS_PER_ROUTE) * 100, 2),
    }


async def warm_up(session: aiohttp.ClientSession) -> None:
    """Fire a single request to each endpoint to trigger cold-start imports."""
    print("Warming up endpoints (cold-start imports)...")
    for method, url, payload in [
        ("GET", f"{BASE_URL}/risk/dashboard", None),
        ("POST", f"{BASE_URL}/stream/telemetry", STREAM_PAYLOAD),
        ("POST", f"{BASE_URL}/warehouse/route", ROUTE_PAYLOAD),
        ("POST", f"{BASE_URL}/predict", PREDICT_PAYLOAD),
    ]:
        try:
            if method == "GET":
                await session.get(url, headers=HEADERS, timeout=30)
            else:
                await session.post(url, json=payload, headers=HEADERS, timeout=30)
        except Exception:
            pass  # Warm-up may fail on some endpoints; that's fine
    print("Warm-up complete.")


async def main() -> None:
    print("INITIATING E2E SYSTEM LATENCY PROFILING...")
    semaphore = asyncio.Semaphore(CONCURRENCY)

    results = []
    async with aiohttp.ClientSession() as session:
        await warm_up(session)
        r1 = await benchmark_route(
            session,
            semaphore,
            "Read-Heavy (Dashboard)",
            "GET",
            f"{BASE_URL}/risk/dashboard",
        )
        results.append(r1)

        r2 = await benchmark_route(
            session,
            semaphore,
            "Write-Heavy (Stream Ingest)",
            "POST",
            f"{BASE_URL}/stream/telemetry",
            STREAM_PAYLOAD,
        )
        results.append(r2)

        r3 = await benchmark_route(
            session,
            semaphore,
            "CPU-Bound (Graph Route)",
            "POST",
            f"{BASE_URL}/warehouse/route",
            ROUTE_PAYLOAD,
        )
        results.append(r3)

        r4 = await benchmark_route(
            session,
            semaphore,
            "Broker-Bound (Predict Queue)",
            "POST",
            f"{BASE_URL}/predict",
            PREDICT_PAYLOAD,
        )
        results.append(r4)

    print("\n--- LATENCY PROFILING RESULTS ---")
    for r in results:
        print(f"  {r['route_name']}")
        print(f"    P50: {r['p50_ms']} ms | P95: {r['p95_ms']} ms | P99: {r['p99_ms']} ms | Errors: {r['error_rate_percent']}%")

    with open("latency_report.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw report written to latency_report.json")


if __name__ == "__main__":
    asyncio.run(main())
