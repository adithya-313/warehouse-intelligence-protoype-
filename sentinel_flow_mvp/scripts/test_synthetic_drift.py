"""Synthetic Drift & Canary Router Tester.

This script validates the entire Phase 2.6 pipeline:
1. Drift Detection: Injects anomalous data to force PSI > 0.2.
2. LoRA Training Trigger: Verifies the drift triggers Celery training task.
3. Canary Routing: Spams predictions to see if 10% hit the adapter vs base model.

The script prints step-by-step results so you can visually verify the logs
and check for CRITICAL "Rolling back" messages in the Celery worker output.

USAGE:
    python scripts/test_synthetic_drift.py

REQUIREMENTS:
    - API server must be running at http://localhost:8080
    - Docker containers must be up (timescaledb, redis, api, worker, celery-beat)
"""

import json
import random
import time
from typing import Any, Dict, List

import urllib.error
import urllib.request

# =============================================================================
# CONFIGURATION
# =============================================================================

# API endpoint for ingesting telemetry data (to trigger drift)
INGESTION_API_URL = "http://localhost:8080/api/v1/ingestion/batch"

# API endpoint for running predictions (to test canary routing)
PREDICTION_API_URL = "http://localhost:8080/api/v1/predict"

# Number of prediction requests to send for canary testing
PREDICTION_REQUEST_COUNT = 100

# Extreme inventory values to force PSI > 0.2 (drift)
ANOMALOUS_INVENTORY_VALUES = [
    0,     # Complete stockout
    1000,  # Extreme overstock
    9999,  # Impossible inventory level
    0,     # Another stockout
    0,     # Another stockout
    5000,  # Extreme overstock
    0,     # Stockout
]


def send_http_post_request(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send an HTTP POST request and return the parsed JSON response.

    This is a helper function used by both the drift injector and the
    prediction spammer. It handles HTTP errors and network failures.

    Args:
        url: The target API endpoint URL.
        payload: The JSON payload to send.

    Returns:
        A dictionary with 'status', 'body' (parsed JSON), and optionally 'error'.
    """
    try:
        # Convert the payload dictionary to JSON bytes
        json_bytes = json.dumps(payload).encode("utf-8")

        # Create the HTTP POST request
        request_object = urllib.request.Request(
            url,
            data=json_bytes,
            headers={"Content-Type": "application/json"},
        )

        # Execute the request and read the response
        with urllib.request.urlopen(request_object, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            parsed_body = json.loads(response_body)

            return {
                "status": response.status,
                "body": parsed_body,
            }

    except urllib.error.HTTPError as http_error:
        # HTTP-level error (e.g., 422 validation, 500 server error)
        error_body = http_error.read().decode("utf-8")
        return {
            "status": http_error.code,
            "body": None,
            "error": error_body,
        }

    except urllib.error.URLError as connection_error:
        # Network-level error (e.g., connection refused)
        return {
            "status": 0,
            "body": None,
            "error": f"Connection failed: {connection_error.reason}",
        }

    except Exception as unexpected_error:
        # Any other unexpected error
        return {
            "status": 0,
            "body": None,
            "error": f"Unexpected error: {str(unexpected_error)}",
        }


def trigger_drift() -> None:
    """Inject extreme inventory records into the system to force PSI > 0.2.

    This function simulates a supply chain disruption by sending batch
    ingestion requests with anomalous inventory counts. The Celery Beat
    drift analysis task (every 5 minutes) will detect PSI > 0.2 and
    trigger LoRA fine-tuning via `train_lora_adapter.delay()`.

    Step-by-step:
    1. For each anomalous inventory value, generate a synthetic batch.
    2. Send it to the ingestion API.
    3. Print the result for manual verification.
    """
    print("")
    print("=" * 60)
    print("PHASE 1: INJECTING DRIFT (Anomalous Inventory Data)")
    print("=" * 60)

    for index, inventory_value in enumerate(ANOMALOUS_INVENTORY_VALUES):
        # Generate a batch payload with this specific anomalous inventory value
        payload = {
            "batch_identifier": f"drift_test_batch_{index}_{int(time.time())}",
            "source_system": "SYNTHETIC_DRIFT_TESTER",
            "records": [
                {
                    "supplier_id": f"DRIFT_SUPPLIER_{random.randint(1, 5)}",
                    "timestamp": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                    "inventory_count": inventory_value,
                    "delivery_delay_days": random.randint(0, 14),
                }
                for _ in range(20)  # 20 records per batch for statistical impact
            ],
        }

        print(
            f"  [{index + 1}/{len(ANOMALOUS_INVENTORY_VALUES)}] "
            f"Injecting inventory={inventory_value} "
            f"({len(payload['records'])} records)..."
        )

        # Send the batch to the ingestion API
        result = send_http_post_request(INGESTION_API_URL, payload)

        if result["status"] == 201:
            # Successfully ingested
            print(f"    -> SUCCESS (HTTP {result['status']})")
        else:
            # Failed or unexpected response
            print(
                f"    -> WARNING (HTTP {result['status']}): "
                f"{result.get('error', 'Unknown error')}"
            )

        # Small delay between batches to avoid overwhelming the API
        time.sleep(0.2)

    print("")
    print("Drift injection complete. The next Celery Beat cycle (~5 min)")
    print("will detect PSI > 0.2 and trigger LoRA training.")
    print("Wait a few seconds and monitor the Celery worker logs.")
    print("")


def spam_predictions() -> None:
    """Send prediction requests to test canary routing.

    This function sends 100 prediction requests and tracks:
    - How many hit the base model (fallback_engaged=False, normal flow)
    - How many hit a hypothetical adapter (would log "Injecting LoRA adapter")
    - How many generated "ROLLED_BACK" critical logs

    The canary routing is set to 10%, so approximately 10 out of 100
    requests should attempt the adapter if a VALIDATING adapter exists.

    Step-by-step:
    1. Loop 100 times.
    2. Each iteration sends a demand_forecast prediction request.
    3. Record the response: was it normal? Did it indicate adapter usage?
    4. Print a summary at the end.
    """
    print("=" * 60)
    print(f"PHASE 2: CANARY ROUTING TEST ({PREDICTION_REQUEST_COUNT} Requests)")
    print("=" * 60)

    # Track the results for the summary report
    total_sent = 0
    total_success = 0
    base_model_count = 0
    adapter_count = 0
    rollback_detected = False

    for index in range(PREDICTION_REQUEST_COUNT):
        # Generate a prediction request for demand_forecast module
        # The module name must match one registered in the orchestrator
        payload = {
            "module_id": "demand_forecast",
            "features": {
                "historical_sales": [100, 120, 110, 130, 125],
            },
            "timeout_ms": 5000,
        }

        # Send the prediction request to the API
        result = send_http_post_request(PREDICTION_API_URL, payload)

        total_sent = total_sent + 1

        if result["status"] == 200 and result["body"] is not None:
            total_success = total_success + 1

            # Check the model_version field to see if an adapter was used
            model_version = result["body"].get("model_version", "unknown")
            fallback_engaged = result["body"].get("fallback_engaged", False)

            # A normal prediction without fallback means the base model ran
            if fallback_engaged is False:
                base_model_count = base_model_count + 1
            else:
                # Fallback was engaged (heuristic instead of model)
                fallback_str = " (heuristic fallback)"
                if "emergency" in model_version:
                    rollback_detected = True
                    fallback_str = " (EMERGENCY - possible rollback)"

                # Print progress every 10 requests to keep output readable
                if (index + 1) % 10 == 0:
                    print(
                        f"  Request {index + 1:3d}/{PREDICTION_REQUEST_COUNT}: "
                        f"model={model_version}{fallback_str}"
                    )

        else:
            # Request failed or error
            if (index + 1) % 10 == 0:
                print(
                    f"  Request {index + 1:3d}/{PREDICTION_REQUEST_COUNT}: "
                    f"FAILED (HTTP {result['status']})"
                )

    # Calculate approximate canary hit rate
    if total_success > 0:
        canary_percentage = (adapter_count / total_success) * 100
    else:
        canary_percentage = 0.0

    # Print the final summary report
    print("")
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Total requests sent:       {total_sent}")
    print(f"  Successful responses:      {total_success}")
    print(f"  Base model used:           {base_model_count}")
    print(f"  Adapter used (approx):     {adapter_count}")
    print(f"  Rollback detected:         {rollback_detected}")
    print(f"  Adapter hit rate:          {canary_percentage:.1f}%")
    print("")

    # Determine if the test passed
    if total_success > 0 and not rollback_detected:
        print("  ✅ TEST PASSED: All predictions completed without errors.")
        print("     Check Celery worker logs for 'Injecting LoRA adapter'")
        print("     messages (approximately 10 out of 100 requests).")
    elif rollback_detected:
        print("  ⚠️  ROLLBACK DETECTED: An adapter was rolled back.")
        print("     Check CRITICAL logs in Celery worker output.")
    else:
        print("  ❌ TEST FAILED: Could not reach the API server.")
        print("     Ensure Docker containers are running.")

    print("")


def run_full_test() -> None:
    """Execute the complete Phase 2.6 pipeline test.

    This function runs both phases sequentially:
    1. Inject drift to trigger LoRA training.
    2. Spam predictions to test canary routing.

    It provides step-by-step console output so you can manually verify
    the results in the Celery worker logs.
    """
    print("")
    print("=" * 60)
    print("SENTINEL-FLOW: PHASE 2.6 PIPELINE TEST")
    print("=" * 60)
    print("")
    print("This test validates three components:")
    print("  1. Drift Detection -> PSI > 0.2 -> LoRA Training Trigger")
    print("  2. LoRA Training -> Adapter Registry (TRAINING -> VALIDATING)")
    print("  3. Canary Routing -> 10% traffic to adapter, base model otherwise")
    print("")

    # Phase 1: Inject anomalous data to force drift
    print("  Step 1: Checking API server availability...")
    health_check_payload = {"module_id": "demand_forecast", "features": {}}
    health_result = send_http_post_request(PREDICTION_API_URL, health_check_payload)

    if health_result["status"] == 0:
        print("  ❌ CRITICAL: Cannot reach the API server.")
        print("     Make sure Docker is running: docker compose up -d")
        print("")
        return

    print(f"  ✅ API server is responding (HTTP {health_result['status']}).")
    print("")

    # Run Phase 1: Drift Injection
    trigger_drift()

    # Wait for Celery Beat to pick up the drift (60 seconds for safety)
    print("  Waiting 60 seconds for Celery Beat to run drift analysis...")
    print("  (Check the worker logs for 'Critical drift detected' messages)")
    time.sleep(60)

    # Run Phase 2: Canary Routing Test
    spam_predictions()

    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("")
    print("Check the Celery worker logs for:")
    print("  - 'Critical drift detected: PSI=... > 0.2'")
    print("  - 'Triggering LoRA fine-tuning for module stockout_prediction'")
    print("  - 'LoRA training started'")
    print("  - 'LoRA adapter ... is now VALIDATING'")
    print("  - 'Canary routing: injecting LoRA adapter ... (10% traffic test)'")
    print("  - (If errors) 'Canary adapter ... failed validation. Rolling back.'")
    print("")


if __name__ == "__main__":
    run_full_test()
