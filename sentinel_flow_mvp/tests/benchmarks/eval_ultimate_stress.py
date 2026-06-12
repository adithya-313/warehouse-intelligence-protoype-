import asyncio
import aiohttp
import time
import uuid
import json

# --- CONFIGURATION ---
BASE_URL = "http://localhost:8080/api/v1"
CONCURRENCY_LIMIT = 200
TOTAL_STREAM_BATCHES = 500  # 500 batches of 50 records = 25,000 telemetry points
TOTAL_PREDICTIONS = 500     # 500 concurrent ML requests
API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

metrics = {
    "stream_success": 0, "stream_failed": 0, "stream_latencies": [],
    "predict_success": 0, "predict_failed": 0, "predict_latencies": []
}

def generate_telemetry_batch():
    return {
        "records": [{
            "entity_id": f"SENSOR-{uuid.uuid4().hex[:6]}",
            "entity_type": "gpu_shipment",
            "node_id": "NVIDIA-TAIWAN",
            "timestamp": "2024-01-01T00:00:00Z"
        } for _ in range(50)]
    }

def generate_predict_request():
    return {
        "module_id": "demand_forecast",
        "supplier_id": "NVIDIA",
        "sku_id": "SKU-NV-5090",
        "route_id": "GLOBAL-1",
        "compute_budget": 50.0 
    }

async def flood_stream(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
    payload = generate_telemetry_batch()
    start = time.time()
    async with semaphore:
        try:
            async with session.post(f"{BASE_URL}/stream/telemetry", json=payload, headers=HEADERS) as resp:
                if resp.status in (200, 201, 202):
                    metrics["stream_success"] += 1
                else:
                    metrics["stream_failed"] += 1
        except Exception:
            metrics["stream_failed"] += 1
    metrics["stream_latencies"].append(time.time() - start)

async def flood_predict(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore):
    payload = generate_predict_request()
    start = time.time()
    async with semaphore:
        try:
            async with session.post(f"{BASE_URL}/predict", json=payload, headers=HEADERS) as resp:
                if resp.status in (200, 201, 202):
                    metrics["predict_success"] += 1
                else:
                    metrics["predict_failed"] += 1
        except Exception:
            metrics["predict_failed"] += 1
    metrics["predict_latencies"].append(time.time() - start)

def calc_p95(latencies):
    if not latencies: return 0
    return sorted(latencies)[int(len(latencies) * 0.95)] * 1000

async def main():
    print("INITIATING EVAL PHASE 4: THE HYPERSCALE HARDWARE FLOOD")
    print(f"Targeting: 25,000 Telemetry Points + {TOTAL_PREDICTIONS} ML Inferences")
    
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    start_time = time.time()
    
    # Custom TCP connector to prevent client-side port exhaustion during the flood
    connector = aiohttp.TCPConnector(limit=CONCURRENCY_LIMIT)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        tasks.extend([flood_stream(session, semaphore) for _ in range(TOTAL_STREAM_BATCHES)])
        tasks.extend([flood_predict(session, semaphore) for _ in range(TOTAL_PREDICTIONS)])
        
        await asyncio.gather(*tasks)
        
    duration = time.time() - start_time
    total_requests = TOTAL_STREAM_BATCHES + TOTAL_PREDICTIONS
    tps = total_requests / duration if duration > 0 else 0
    
    print("\n--- ULTIMATE SCALABILITY REPORT ---")
    print(f"Total Time: {duration:.2f}s | TPS: {tps:.2f} req/sec")
    
    stream_p95 = calc_p95(metrics['stream_latencies'])
    predict_p95 = calc_p95(metrics['predict_latencies'])
    
    print(f"Stream Ingestion -> Success: {metrics['stream_success']} | Failed: {metrics['stream_failed']} | P95 Latency: {stream_p95:.2f}ms")
    print(f"ML Prediction -> Success: {metrics['predict_success']} | Failed: {metrics['predict_failed']} | P95 Latency: {predict_p95:.2f}ms")
    
    report = {
        "phase": "EVAL_PHASE_4_ULTIMATE_STRESS",
        "status": "COMPLETED",
        "duration_sec": round(duration, 2),
        "requests_per_second": round(tps, 2),
        "stream_p95_ms": round(stream_p95, 2),
        "predict_p95_ms": round(predict_p95, 2),
        "total_failures": metrics['stream_failed'] + metrics['predict_failed']
    }
    with open("ultimate_stress_report.json", "w") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
