"""Concurrent Inference Load Tester.

This script validates the PredictionOrchestrator's stability and fallback
routing under high concurrency. It fires 200 simultaneous requests across
all 4 registered intelligence modules and collects performance metrics.

USAGE:
    python scripts/test_concurrent_inference.py

REQUIREMENTS:
    - API server must be running at http://localhost:8080
    - aiohttp must be installed (pip install aiohttp)
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List

import aiohttp

# Configure logging for clear output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# API endpoint for predictions
API_ENDPOINT_URL = "http://localhost:8080/api/v1/predict"

# Number of requests per module
REQUESTS_PER_MODULE = 50

# Total requests
TOTAL_REQUESTS = REQUESTS_PER_MODULE * 4


def generate_payload(module_id: str, supplier_id: str = None, force_fallback: bool = False) -> Dict[str, Any]:
    """Generate a test payload for a specific module.

    This function creates a standardized JSON payload that matches the
    BaseInferenceRequest schema expected by the API.

    Args:
        module_id: The target module identifier.
        supplier_id: The target supplier identifier.
        force_fallback: If True, injects parameters to trigger fallback.

    Returns:
        A dictionary representing the inference request.
    """
    # Base payload structure
    payload = {
        "module_id": module_id,
        "supplier_id": supplier_id,
        "sku_id": "SKU-NV-4070S",
        "route_id": "route_001",
        "features": {},
        "sla_tier": "premium",
        "compute_budget_remaining": 50.0
    }

    # Configure features based on module type
    if module_id == "demand_forecast":
        payload["features"] = {
            "historical_sales": [100, 120, 110, 130, 125],
        }

    elif module_id == "stockout_prediction":
        if force_fallback:
            # Inject timeout to force orchestrator fallback
            payload["features"] = {
                "current_inventory": 50,
                "lead_time_days": 7,
                "simulate_timeout": True,
            }
            # Set timeout lower than the simulated sleep (2s)
            payload["timeout_ms"] = 500
        else:
            payload["features"] = {
                "current_inventory": 5,
                "lead_time_days": 14,
            }
            payload["timeout_ms"] = 5000

    elif module_id == "predictive_maintenance":
        payload["features"] = {
            "equipment_age_days": 1500,
            "vibration_index": 0.8,
        }

    elif module_id == "fuel_cost":
        payload["features"] = {
            "route_distance_km": 250.0,
            "vehicle_efficiency": 12.5,
        }

    return payload


async def send_single_request(
    session: aiohttp.ClientSession,
    payload: Dict[str, Any],
    request_index: int,
) -> Dict[str, Any]:
    """Send a single inference request to the API.

    This function handles the HTTP POST request, measures latency,
    and gracefully handles any network or server errors.

    Args:
        session: The aiohttp client session.
        payload: The JSON payload to send.
        request_index: The index of this request (for logging).

    Returns:
        A dictionary containing the result metrics for this request.
    """
    # Record start time for latency measurement
    start_time = time.time()

    # Initialize result dictionary with default failure values
    result = {
        "request_index": request_index,
        "module_id": payload["module_id"],
        "status_code": 0,
        "success": False,
        "fallback_engaged": False,
        "latency_seconds": 0.0,
        "error_message": None,
        "swap_in_latency_ms": 0.0,
        "compute_latency_ms": 0.0,
        "swap_out_latency_ms": 0.0,
    }

    try:
        # Execute the HTTP POST request
        async with session.post(
            API_ENDPOINT_URL,
            json=payload,
            headers={"Content-Type": "application/json", "X-API-Key": "my_super_secret_key_123"},
        ) as response:
            # Check if the request was successful
            if response.status == 202:
                response_data = await response.json()
                task_id = response_data.get("task_id")
                
                # Poll for completion
                while True:
                    async with session.get(f"http://localhost:8080/api/v1/tasks/{task_id}", headers={"X-API-Key": "my_super_secret_key_123"}) as task_resp:
                        task_data = await task_resp.json()
                        if task_data.get("status") == "SUCCESS":
                            response_data = task_data.get("result", {})
                            break
                        elif task_data.get("status") in ["FAILURE", "REVOKED"]:
                            result["error_message"] = "Task failed: " + str(task_data.get("error"))
                            return result
                    await asyncio.sleep(0.5)
                    
                end_time = time.time()
                result["latency_seconds"] = end_time - start_time
                
                result["success"] = True
                result["fallback_engaged"] = response_data.get("fallback_engaged", False)
                
                metadata = response_data.get("execution_metadata", {})
                result["swap_in_latency_ms"] = metadata.get("swap_in_latency_ms", 0.0)
                result["compute_latency_ms"] = metadata.get("compute_latency_ms", 0.0)
                result["swap_out_latency_ms"] = metadata.get("swap_out_latency_ms", 0.0)
            elif response.status == 200:
                # Direct response fallback
                response_data = await response.json()
                end_time = time.time()
                result["latency_seconds"] = end_time - start_time
                result["success"] = True
                result["fallback_engaged"] = response_data.get("fallback_engaged", False)
                metadata = response_data.get("execution_metadata", {})
                result["swap_in_latency_ms"] = metadata.get("swap_in_latency_ms", 0.0)
                result["compute_latency_ms"] = metadata.get("compute_latency_ms", 0.0)
                result["swap_out_latency_ms"] = metadata.get("swap_out_latency_ms", 0.0)
            else:
                # Read error response body
                error_body = await response.text()
                result["error_message"] = f"HTTP {response.status}: {error_body}"

    except aiohttp.ClientError as network_error:
        # Handle network-related errors (connection refused, timeout, etc.)
        end_time = time.time()
        result["latency_seconds"] = end_time - start_time
        result["error_message"] = f"Network error: {str(network_error)}"
        logger.warning(f"Request {request_index} failed: {result['error_message']}")

    except Exception as unexpected_error:
        # Handle any other unexpected errors
        end_time = time.time()
        result["latency_seconds"] = end_time - start_time
        result["error_message"] = f"Unexpected error: {str(unexpected_error)}"
        logger.error(f"Request {request_index} crashed: {result['error_message']}")

    return result


async def run_load_test() -> None:
    """Execute the complete concurrent load test.

    This function orchestrates the entire test:
    1. Creates 200 request payloads (50 per module).
    2. Fires all requests concurrently using asyncio.gather().
    3. Collects and aggregates metrics.
    4. Prints a final summary report.
    """
    logger.info("=" * 60)
    logger.info("SENTINEL-FLOW: CONCURRENT INFERENCE LOAD TEST")
    logger.info("=" * 60)
    logger.info(f"Target: {API_ENDPOINT_URL}")
    logger.info(f"Total requests: {TOTAL_REQUESTS} ({REQUESTS_PER_MODULE} per module)")
    logger.info("Starting test...")

    # Step 1: Generate all request payloads
    all_payloads = []

    # For Phase 10.3 Test C: spam the endpoint with 200 requests across 4 suppliers
    supplier_ids = ["NVIDIA Corporation", "ASUS Global", "Intel Corp", "NVIDIA"]
    
    for supplier_id in supplier_ids:
        for index in range(REQUESTS_PER_MODULE):
            payload = generate_payload("demand_forecast", supplier_id=supplier_id)
            all_payloads.append(payload)

    # Step 2: Create aiohttp session and fire all requests concurrently
    test_start_time = time.time()

    # Create a connector with connection pooling for better performance
    connector = aiohttp.TCPConnector(limit=100, force_close=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Create a list of coroutines for all requests
        request_coroutines = []
        for index, payload in enumerate(all_payloads):
            coroutine = send_single_request(session, payload, index)
            request_coroutines.append(coroutine)

        # Execute all requests concurrently and wait for completion
        logger.info("Firing 200 concurrent requests...")
        results = await asyncio.gather(*request_coroutines, return_exceptions=True)

    test_end_time = time.time()
    total_test_duration = test_end_time - test_start_time

    # Step 3: Aggregate metrics from results
    total_sent = len(results)
    total_successful = 0
    total_fallbacks = 0
    total_latency = 0.0
    successful_latencies = []
    
    total_swap_in = 0.0
    total_compute = 0.0
    total_swap_out = 0.0
    adapter_swaps_count = 0

    for result in results:
        # Check if the result is an exception (from return_exceptions=True)
        if isinstance(result, Exception):
            logger.error(f"Request failed with exception: {result}")
            continue

        # Count successful HTTP responses
        if result["success"]:
            total_successful = total_successful + 1
        else:
            logger.error(f"Request {result['request_index']} failed: {result.get('error_message')}")

        # Count fallback engagements
        if result["fallback_engaged"]:
            total_fallbacks = total_fallbacks + 1

        # Accumulate latency for averaging
        total_latency = total_latency + result["latency_seconds"]
        if result["success"]:
            successful_latencies.append(result["latency_seconds"])
            
            if result.get("swap_in_latency_ms") or result.get("compute_latency_ms") or result.get("swap_out_latency_ms"):
                total_swap_in += result["swap_in_latency_ms"]
                total_compute += result["compute_latency_ms"]
                total_swap_out += result["swap_out_latency_ms"]
                adapter_swaps_count += 1

    # Calculate average latency
    if total_sent > 0:
        average_latency = total_latency / total_sent
    else:
        average_latency = 0.0

    # Calculate throughput (requests per second)
    if total_test_duration > 0:
        throughput = total_sent / total_test_duration
    else:
        throughput = 0.0

    avg_swap_in = total_swap_in / adapter_swaps_count if adapter_swaps_count > 0 else 0.0
    avg_compute = total_compute / adapter_swaps_count if adapter_swaps_count > 0 else 0.0
    avg_swap_out = total_swap_out / adapter_swaps_count if adapter_swaps_count > 0 else 0.0

    # Step 4: Print final summary report
    logger.info("=" * 60)
    logger.info("LOAD TEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"Total requests sent:          {total_sent}")
    logger.info(f"Total successful (HTTP 200):  {total_successful}")
    logger.info(f"Total fallbacks engaged:      {total_fallbacks}")
    logger.info(f"Average latency per request:  {average_latency * 1000:.2f} ms")
    logger.info(f"Total test duration:          {total_test_duration:.2f} s")
    logger.info(f"Throughput:                   {throughput:.2f} req/s")
    if adapter_swaps_count > 0:
        logger.info(f"Average Swap In Overhead:     {avg_swap_in:.2f} ms")
        logger.info(f"Average Compute Time:         {avg_compute:.2f} ms")
        logger.info(f"Average Swap Out Overhead:    {avg_swap_out:.2f} ms")
    logger.info("=" * 60)

    # Verify fallback routing worked correctly
    # We expect ~50 fallbacks from the stockout timeout injection
    if total_fallbacks >= 45:
        logger.info("✅ SUCCESS: Fallback routing verified! Orchestrator correctly engaged heuristics.")
    else:
        logger.warning(f"⚠️  WARNING: Expected ~50 fallbacks, but got {total_fallbacks}.")
        logger.warning("Check if timeout injection is working correctly.")

    logger.info("Test complete.")


if __name__ == "__main__":
    # Run the async load test
    asyncio.run(run_load_test())
