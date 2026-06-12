import asyncio
import aiohttp
import time
import json

URL = "http://localhost:8080/api/v1/predict"
HEADERS = {"X-API-Key": "my_super_secret_key_123", "Content-Type": "application/json"}
PAYLOAD = {
    "module_id": "demand_forecast",
    "supplier_id": "NVIDIA Corporation",
    "sku_id": "SKU-NV-5090",
    "route_id": "Taiwan -> Kochi Port",
    "compute_budget": 50.0
}

async def fetch(session, idx):
    start = time.perf_counter()
    try:
        async with session.post(URL, headers=HEADERS, json=PAYLOAD, timeout=20) as response:
            status = response.status
            await response.read()
            latency = (time.perf_counter() - start) * 1000
            return status, latency
    except Exception as e:
        print(f"Error in fetch: {e}")
        latency = (time.perf_counter() - start) * 1000
        return 500, latency

async def load_test():
    print("--- 1. API STRESS TEST (50 CONCURRENT) ---")
    async with aiohttp.ClientSession() as session:
        start_total = time.perf_counter()
        tasks = [fetch(session, i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        total_time = (time.perf_counter() - start_total) * 1000
        
        successes = [r for r in results if r[0] == 202]
        latencies = [r[1] for r in results]
        
        success_rate = len(successes) / 50 * 100
        avg_latency = sum(latencies) / len(latencies)
        
        print(f"Total Execution Time (ms): {total_time:.2f}")
        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Average Latency (ms): {avg_latency:.2f}")
        
        return success_rate, avg_latency

async def geo_test():
    print("\n--- 2. GEO-ROUTER VERIFICATION ---")
    regions = ['US', 'DE', 'IN']
    pass_fail = True
    async with aiohttp.ClientSession() as session:
        for r in regions:
            headers = {**HEADERS, "CF-IPCountry": r, "X-Forwarded-For": "8.8.8.8"}
            try:
                async with session.post(URL, headers=headers, json=PAYLOAD, timeout=5) as resp:
                    status = resp.status
                    text = await resp.text()
                    print(f"Region {r} -> HTTP {status}")
                    if status != 202:
                        pass_fail = False
            except Exception as e:
                print(f"Region {r} -> Failed: {e}")
                pass_fail = False
    return pass_fail

async def main():
    success_rate, avg_latency = await load_test()
    geo_pass = await geo_test()
    
    print("\n")
    print("| Metric | Value |")
    print("|---|---|")
    print("| Total Requests Sent | 50 |")
    print(f"| Success Rate (%) | {success_rate:.1f} |")
    print(f"| Avg Latency Under Load (ms) | {avg_latency:.2f} |")
    print(f"| Geo-Router Verification | {'Pass' if geo_pass else 'Fail'} |")
    
if __name__ == "__main__":
    asyncio.run(main())
