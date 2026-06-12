"""Synthetic ERP Load Generator.

Simulates a high-throughput data dump from an ERP system to validate the ingestion gateway,
Aegis validation, and asynchronous worker pipeline.
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import urllib.error
import urllib.request
from dotenv import load_dotenv

load_dotenv()

API_ENDPOINT_URL = "http://localhost:8080/api/v1/ingestion/batch"




def generate_synthetic_batch(record_count: int) -> Dict[str, Any]:
    """Generates a mock payload mathematically conforming to the IngestionPayload schema.

    Args:
        record_count: The number of synthetic supplier records to generate.

    Returns:
        A dictionary representing the exact JSON payload expected by the API.
    """
    record_list = []

    for index in range(record_count):
        synthetic_record = {
            "supplier_id": f"SUPPLIER_{random.randint(1000, 9999)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "inventory_count": random.randint(0, 200),
            "delivery_delay_days": random.randint(0, 14),
        }
        record_list.append(synthetic_record)

    synthetic_payload = {
        "batch_identifier": str(uuid.uuid4()),
        "source_system": "SYNTHETIC_ERP_SIMULATOR",
        "records": record_list,
    }

    return synthetic_payload


def execute_load_test(record_count: int) -> None:
    """Sends the synthetic data to the local FastAPI server and logs the response.

    Args:
        record_count: Number of records to inject into the system.
    """
    print(f"Generating synthetic payload with {record_count} records...")
    payload_dictionary = generate_synthetic_batch(record_count=record_count)

    json_bytes = json.dumps(payload_dictionary).encode("utf-8")

    request_object = urllib.request.Request(
        API_ENDPOINT_URL,
        data=json_bytes,
        headers={"Content-Type": "application/json"},
    )

    print(f"Transmitting to API Gateway at {API_ENDPOINT_URL}...")
    start_time = time.time()

    try:
        with urllib.request.urlopen(request_object) as response:
            response_body = response.read().decode("utf-8")
            end_time = time.time()

            print(f"SUCCESS: API responded with status code {response.status}")
            print(f"API Latency: {(end_time - start_time) * 1000:.2f} milliseconds")
            print(f"API Response: {response_body}")
            print(
                "Check your Docker terminal to watch the Celery worker process the batch in the background."
            )

    except urllib.error.HTTPError as http_error:
        print(f"CRITICAL FAILURE: API rejected payload with status {http_error.code}")
        print(f"Error Details: {http_error.read().decode('utf-8')}")
    except urllib.error.URLError as connection_error:
        print(
            f"NETWORK FAILURE: Could not connect to API. Is Docker running? Error: {connection_error.reason}"
        )


if __name__ == "__main__":
    execute_load_test(record_count=500)