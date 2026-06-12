"""
ML ACCURACY & ECONOMICS PROFILER — measures Chronos-T5 vs Heuristic tradeoffs.

Forces the hypervisor down two paths:
    Premium budget (100.0) → Celery worker → Chronos-T5 / LoRA model
    Micro budget (0.5)     → HEURISTIC_FALLBACK route (instant math)
Compares latency, prediction output, and speed delta.
"""

import asyncio
import aiohttp
import json
import time

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

PREDICT_URL = "http://localhost:8080/api/v1/predict"
TASK_URL = "http://localhost:8080/api/v1/tasks"

API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

# Premium budget forces GPU/CPU to load the ML Tensor (Chronos-T5 / LoRA).
# Micro budget forces the Hypervisor to use lightweight Math (heuristic fallback).
PREMIUM_PAYLOAD = {
    "module_id": "demand_forecast",
    "supplier_id": "NVIDIA",
    "sku_id": "SKU-1",
    "route_id": "R1",
    "compute_budget": 100.0,
}

MICRO_PAYLOAD = {
    "module_id": "demand_forecast",
    "supplier_id": "NVIDIA",
    "sku_id": "SKU-1",
    "route_id": "R1",
    "compute_budget": 0.5,
}

POLL_INTERVAL = 0.2


async def poll_celery_task(
    session: aiohttp.ClientSession,
    task_id: str,
) -> dict:
    """Continuously poll the background worker until ML inference is complete."""
    start = time.time()
    while True:
        async with session.get(
            f"{TASK_URL}/{task_id}", headers=HEADERS
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "SUCCESS":
                    return {
                        "result": data.get("result"),
                        "processing_time": time.time() - start,
                    }
        await asyncio.sleep(POLL_INTERVAL)


async def evaluate_engine() -> None:
    """Run the ML vs Heuristic comparison and report results."""
    print("INITIATING EVAL PHASE 2: ML ACCURACY & ECONOMICS...")

    async with aiohttp.ClientSession() as session:
        # ------------------------------------------------------------------
        # 1. Test the Heavy ML Engine
        # ------------------------------------------------------------------
        print("\nTriggering Heavy ML Model (Chronos-T5 / LoRA)...")
        ml_start = time.time()
        async with session.post(
            PREDICT_URL, json=PREMIUM_PAYLOAD, headers=HEADERS
        ) as resp:
            ml_data = await resp.json()

        ml_result = await poll_celery_task(session, ml_data["task_id"])
        ml_total_time = time.time() - ml_start
        ml_prediction = ml_result["result"]["prediction_value"]

        # ------------------------------------------------------------------
        # 2. Test the Heuristic Fallback
        # ------------------------------------------------------------------
        print("Triggering Heuristic Fallback (Math)...")
        math_start = time.time()
        async with session.post(
            PREDICT_URL, json=MICRO_PAYLOAD, headers=HEADERS
        ) as resp:
            math_data = await resp.json()

        # If the hypervisor routes to HEURISTIC_FALLBACK (budget <= threshold),
        # it may return inline or via Celery depending on the route.
        if "task_id" in math_data:
            math_result = await poll_celery_task(
                session, math_data["task_id"]
            )
            math_prediction = math_result["result"]["prediction_value"]
        else:
            math_prediction = math_data.get("prediction_value", 0)

        math_total_time = time.time() - math_start

    # ------------------------------------------------------------------
    # 3. Calculate Economics
    # ------------------------------------------------------------------
    variance = abs(ml_prediction - math_prediction)
    speed_delta = (
        ml_total_time / math_total_time if math_total_time > 0 else 0
    )

    print("\n--- ML ECONOMICS REPORT ---")
    print(f"  Heavy ML Engine Latency : {ml_total_time:.3f}s")
    print(f"  Heavy ML Engine Prediction : {ml_prediction:.4f}")
    print(f"  Heuristic Math Latency  : {math_total_time:.3f}s")
    print(f"  Heuristic Math Prediction : {math_prediction:.4f}")
    print(f"  Output Variance (Error) : {variance:.4f}")
    print(f"  Speed Tradeoff : Heuristic is {speed_delta:.1f}x faster than full ML.")

    report = {
        "phase": "EVAL_PHASE_2_ML_ECONOMICS",
        "status": "COMPLETED",
        "ml_latency_sec": round(ml_total_time, 3),
        "math_latency_sec": round(math_total_time, 3),
        "prediction_variance": round(variance, 4),
        "speed_multiplier": round(speed_delta, 1),
    }

    with open("ml_economics_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\nReport written to ml_economics_report.json")


if __name__ == "__main__":
    asyncio.run(evaluate_engine())
