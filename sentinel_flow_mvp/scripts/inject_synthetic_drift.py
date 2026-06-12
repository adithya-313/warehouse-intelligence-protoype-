"""Synthetic Drift Injector for Sentinel-Flow.

This script generates synthetic data to test the drift monitoring system.
It creates two phases of data:
- Phase A: 100 baseline records representing healthy operations
- Phase B: 50 failure records representing a total system collapse

After injection, it triggers the drift detection and verifies all alerts fire.

USAGE:
    python scripts/inject_synthetic_drift.py

REQUIREMENTS:
    - Docker containers must be running (timescaledb, redis, api, worker)
    - Database must be initialized with the migration script
"""

import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import uuid4

from sqlalchemy.orm import Session

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import MLPredictionLog, TelemetryModel
from app.services.drift_service import detect_stockout_drift

# Configure logging for clear output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# API endpoint for fetching Prometheus metrics
METRICS_ENDPOINT_URL = "http://localhost:8080/metrics"

# Baseline constants for healthy operations
BASELINE_PREDICTED_PROBABILITY = 0.1  # Low stockout probability = healthy
BASELINE_INVENTORY_COUNT = 100  # Healthy inventory level
BASELINE_DELIVERY_DELAY = 1  # Normal delivery delay in days


def generate_tracking_id() -> str:
    """Generate a unique tracking ID for a prediction/actual pair.

    Returns:
        A UUID string for tracking.
    """
    return str(uuid4())


def insert_baseline_records(
    database_session: Session,
    record_count: int,
) -> List[str]:
    """Insert healthy baseline records into the database.

    Phase A: Generates records representing normal operations where
    predictions match actuals closely.

    Args:
        database_session: An active SQLAlchemy database session.
        record_count: Number of baseline records to generate.

    Returns:
        A list of tracking IDs for the inserted records.
    """
    logger.info(f"Phase A: Generating {record_count} baseline (healthy) records...")

    tracking_ids = []
    current_time = datetime.now(timezone.utc)

    for index in range(record_count):
        # Generate a unique tracking ID for this record pair
        tracking_id = generate_tracking_id()
        tracking_ids.append(tracking_id)

        # Calculate timestamp - spread records over the last hour
        time_offset_seconds = index * 36  # 3600 seconds / 100 records = 36 seconds apart
        record_timestamp = current_time - timedelta(seconds=time_offset_seconds)

        # Create the ML prediction log entry
        # Baseline: Low predicted stockout probability (0.1) = model predicts healthy inventory
        prediction_log = MLPredictionLog(
            tracking_id=tracking_id,
            predicted_stockout_probability=BASELINE_PREDICTED_PROBABILITY,
            predicted_at=record_timestamp,
        )
        database_session.add(prediction_log)

        # Create the telemetry actual entry
        # Baseline: High actual inventory (100), low delivery delay (1 day)
        # This matches the prediction - model was correct
        telemetry_record = TelemetryModel(
            recorded_at=record_timestamp,
            supplier_id=f"BASELINE_SUPPLIER_{index % 10}",  # Rotate through 10 suppliers
            tracking_id=tracking_id,
            inventory_count=BASELINE_INVENTORY_COUNT,
            delivery_delay_days=BASELINE_DELIVERY_DELAY,
            predicted_stockout_probability=BASELINE_PREDICTED_PROBABILITY,
            is_critical_risk=False,
        )
        database_session.add(telemetry_record)

    # Commit all baseline records to the database
    database_session.commit()
    logger.info(f"Phase A complete: {record_count} baseline records inserted.")

    return tracking_ids


def insert_failure_records(
    database_session: Session,
    record_count: int,
) -> List[str]:
    """Insert failure records that simulate a total system collapse.

    Phase B: Generates records designed to trigger ALL FOUR alerts:
    1. Model Drift Alert: Extreme shift in predicted vs actual stockouts
    2. Supplier Risk Alert: Actual delays far exceed predictions
    3. Inventory Anomaly Alert: Actual inventory = 0 but predicted was healthy
    4. Throughput Degradation Alert: Low batch size relative to baseline

    Args:
        database_session: An active SQLAlchemy database session.
        record_count: Number of failure records to generate.

    Returns:
        A list of tracking IDs for the inserted records.
    """
    logger.info(f"Phase B: Generating {record_count} failure (collapse) records...")
    logger.info("  - Model Drift: Predicted 0.1, Actual 1.0 (extreme shift)")
    logger.info("  - Supplier Risk: Predicted 1 day delay, Actual 5 days")
    logger.info("  - Inventory Anomaly: Predicted healthy (100), Actual 0")
    logger.info("  - Throughput: Only 50 records (below baseline of 50)")

    tracking_ids = []
    current_time = datetime.now(timezone.utc)

    for index in range(record_count):
        # Generate a unique tracking ID for this record pair
        tracking_id = generate_tracking_id()
        tracking_ids.append(tracking_id)

        # Calculate timestamp - spread records over the last 30 minutes
        time_offset_seconds = index * 36  # 1800 seconds / 50 records = 36 seconds apart
        record_timestamp = current_time - timedelta(seconds=time_offset_seconds)

        # FAILURE INJECTION 1: Model Drift
        # Model predicts LOW stockout probability (0.1 = healthy)
        # But actual outcome is HIGH stockout (inventory = 0)
        # This creates a massive distribution shift -> high PSI
        predicted_probability = 0.1  # Model says "everything is fine"

        # Create the ML prediction log entry
        prediction_log = MLPredictionLog(
            tracking_id=tracking_id,
            predicted_stockout_probability=predicted_probability,
            predicted_at=record_timestamp,
        )
        database_session.add(prediction_log)

        # FAILURE INJECTION 2: Supplier Risk
        # Actual delivery delay is 5 days, but model predicted 1 day
        # Difference = 4 days, which exceeds the 2-day threshold
        actual_delivery_delay = 5  # Severe delay

        # FAILURE INJECTION 3: Inventory Anomaly
        # Actual inventory is 0 (stockout occurred)
        # But model predicted probability was 0.1 (< 0.5 threshold)
        # This means model predicted healthy inventory but actual was 0
        actual_inventory = 0  # Complete stockout

        # Create the telemetry actual entry with all failure conditions
        telemetry_record = TelemetryModel(
            recorded_at=record_timestamp,
            supplier_id=f"FAILURE_SUPPLIER_{index % 5}",  # Rotate through 5 failing suppliers
            tracking_id=tracking_id,
            inventory_count=actual_inventory,
            delivery_delay_days=actual_delivery_delay,
            predicted_stockout_probability=predicted_probability,
            is_critical_risk=True,
        )
        database_session.add(telemetry_record)

    # Commit all failure records to the database
    database_session.commit()
    logger.info(f"Phase B complete: {record_count} failure records inserted.")

    return tracking_ids


def fetch_and_parse_metrics() -> Dict[str, float]:
    """Fetch Prometheus metrics from the API and parse alert values.

    This function makes an HTTP GET request to the /metrics endpoint
    and extracts the values of the four alert gauges.

    Returns:
        A dictionary mapping metric names to their current values.
    """
    logger.info(f"Fetching metrics from {METRICS_ENDPOINT_URL}...")

    try:
        # Create the HTTP GET request
        request_object = urllib.request.Request(METRICS_ENDPOINT_URL)

        # Execute the network call
        with urllib.request.urlopen(request_object) as response:
            metrics_text = response.read().decode("utf-8")

        # Parse the metrics text to extract alert gauge values
        parsed_metrics = {}

        # Split the metrics text into lines
        metric_lines = metrics_text.split("\n")

        # Look for each alert metric line
        for metric_line in metric_lines:
            # Check for model_drift_alert
            if metric_line.startswith("model_drift_alert "):
                # The format is: metric_name{labels} value
                # We need to extract the value at the end
                parts = metric_line.split(" ")
                if len(parts) >= 2:
                    parsed_metrics["model_drift_alert"] = float(parts[-1])

            # Check for supplier_risk_alert
            elif metric_line.startswith("supplier_risk_alert "):
                parts = metric_line.split(" ")
                if len(parts) >= 2:
                    parsed_metrics["supplier_risk_alert"] = float(parts[-1])

            # Check for inventory_anomaly_alert
            elif metric_line.startswith("inventory_anomaly_alert "):
                parts = metric_line.split(" ")
                if len(parts) >= 2:
                    parsed_metrics["inventory_anomaly_alert"] = float(parts[-1])

            # Check for throughput_degradation_alert
            elif metric_line.startswith("throughput_degradation_alert "):
                parts = metric_line.split(" ")
                if len(parts) >= 2:
                    parsed_metrics["throughput_degradation_alert"] = float(parts[-1])

        logger.info(f"Successfully parsed {len(parsed_metrics)} alert metrics.")
        return parsed_metrics

    except urllib.error.HTTPError as http_error:
        logger.error(f"HTTP Error fetching metrics: {http_error.code}")
        logger.error(f"Response: {http_error.read().decode('utf-8')}")
        return {}
    except urllib.error.URLError as connection_error:
        logger.error(f"Network Error fetching metrics: {connection_error.reason}")
        logger.error("Is the API container running? Check with: docker ps")
        return {}
    except Exception as general_error:
        logger.error(f"Unexpected error fetching metrics: {str(general_error)}")
        return {}


def verify_all_alerts_triggered(metrics: Dict[str, float]) -> bool:
    """Verify that all four alerts have been triggered (value = 1.0).

    Args:
        metrics: Dictionary of parsed metric values.

    Returns:
        True if all alerts are 1.0, False otherwise.
    """
    logger.info("Verifying alert trigger status...")

    expected_alerts = [
        "model_drift_alert",
        "supplier_risk_alert",
        "inventory_anomaly_alert",
        "throughput_degradation_alert",
    ]

    all_triggered = True

    for alert_name in expected_alerts:
        alert_value = metrics.get(alert_name, -1.0)

        if alert_value == 1.0:
            logger.info(f"  ✅ {alert_name}: {alert_value} (TRIGGERED)")
        else:
            logger.warning(f"   {alert_name}: {alert_value} (NOT TRIGGERED)")
            all_triggered = False

    return all_triggered


def run_drift_injection_test() -> None:
    """Execute the complete drift injection test.

    This function orchestrates the entire test:
    1. Connect to the database
    2. Insert baseline records (Phase A)
    3. Insert failure records (Phase B)
    4. Trigger drift detection
    5. Fetch and verify metrics
    """
    logger.info("=" * 60)
    logger.info("SENTINEL-FLOW: SYNTHETIC DRIFT INJECTION TEST")
    logger.info("=" * 60)

    # Initialize database session
    database_session: Session = SessionLocal()

    try:
        # Phase A: Insert baseline (healthy) records
        baseline_ids = insert_baseline_records(
            database_session=database_session,
            record_count=100,
        )
        logger.info(f"Baseline tracking IDs sample: {baseline_ids[:3]}...")

        # Phase B: Insert failure (collapse) records
        failure_ids = insert_failure_records(
            database_session=database_session,
            record_count=50,
        )
        logger.info(f"Failure tracking IDs sample: {failure_ids[:3]}...")

        # Trigger drift detection
        logger.info("Triggering drift detection analysis...")
        drift_results = detect_stockout_drift(database_session=database_session)

        logger.info(f"Drift Detection Results:")
        logger.info(f"  PSI Value: {drift_results['psi']:.4f}")
        logger.info(f"  Model Drift Alert: {drift_results['model_drift_alert']}")
        logger.info(f"  Supplier Risk Alert: {drift_results['supplier_risk_alert']}")
        logger.info(f"  Inventory Anomaly Alert: {drift_results['inventory_anomaly_alert']}")
        logger.info(f"  Throughput Degradation Alert: {drift_results['throughput_degradation_alert']}")

        # Small delay to ensure metrics are flushed to Prometheus
        logger.info("Waiting 2 seconds for metrics propagation...")
        time.sleep(2)

        # Fetch metrics from the API
        parsed_metrics = fetch_and_parse_metrics()

        # Verify all alerts triggered
        all_triggered = verify_all_alerts_triggered(parsed_metrics)

        # Final summary
        logger.info("=" * 60)
        if all_triggered:
            logger.info("✅ SUCCESS: All four alerts triggered correctly!")
            logger.info("The drift monitoring system is functioning as expected.")
        else:
            logger.warning("⚠️ PARTIAL SUCCESS: Some alerts did not trigger.")
            logger.warning("Review the failure injection logic and thresholds.")
        logger.info("=" * 60)

    except Exception as execution_error:
        logger.error(f"Drift injection test failed: {str(execution_error)}")
        raise

    finally:
        # Always close the database session to prevent connection leaks
        database_session.close()
        logger.info("Database session closed.")


if __name__ == "__main__":
    run_drift_injection_test()
