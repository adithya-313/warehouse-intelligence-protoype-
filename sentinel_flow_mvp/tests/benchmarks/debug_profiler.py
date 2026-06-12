"""Quick debug: test each route individually."""

import asyncio
import aiohttp
import time

BASE_URL = "http://localhost:8080/api/v1"
API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}
N = 5  # small sample

async def test_route(name, method, url, payload=None):
    print(f"\n--- {name} ---")
    async with aiohttp.ClientSession() as s:
        t0 = time.time()
        try:
            if method == "GET":
                async with s.get(url, headers=HEADERS, timeout=30) as r:
                    body = await r.read()
                    print(f"  Status: {r.status}, Time: {time.time()-t0:.2f}s, Body: {len(body)} bytes")
            else:
                async with s.post(url, json=payload, headers=HEADERS, timeout=30) as r:
                    body = await r.read()
                    print(f"  Status: {r.status}, Time: {time.time()-t0:.2f}s, Body: {len(body)} bytes")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")

async def main():
    await test_route("Risk Dashboard", "GET", f"{BASE_URL}/risk/dashboard")
    await test_route("Stream Ingest", "POST", f"{BASE_URL}/stream/telemetry", {"records": [{"entity_id": "TEST-1", "entity_type": "robot", "node_id": "A1", "timestamp": "2024-01-01T00:00:00Z"}]})
    await test_route("Warehouse Route", "POST", f"{BASE_URL}/warehouse/route", {"source_id": "ZONE-A", "target_id": "ZONE-B", "entity_type": "robot"})
    await test_route("Predict Queue", "POST", f"{BASE_URL}/predict", {"module_id": "demand_forecast", "supplier_id": "NVIDIA", "sku_id": "SKU-1", "route_id": "R1", "compute_budget": 100.0})

asyncio.run(main())
