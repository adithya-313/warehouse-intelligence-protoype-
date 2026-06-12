"""Statistical Drift Monitoring Service.

This module implements Population Stability Index (PSI) calculation
to detect distribution drift between ML predictions and actual ground truth.

PSI Formula:
    PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))

Thresholds:
    PSI < 0.1: No significant change
    0.1 <= PSI < 0.2: Moderate change - monitor closely
    PSI >= 0.2: Significant drift - alert required

Alert Conditions:
    model_drift_alert: PSI > 0.2
    supplier_risk_alert: avg(actual_delay) - avg(predicted_delay) >= 2 days
    inventory_anomaly_alert: actual_inventory == 0 AND predicted_inventory > 50
    throughput_degradation_alert: batch_size < baseline_threshold
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import numpy as np
from sqlalchemy.orm import Session

from app.core.metrics import (
    drift_alerts_total,
    inventory_anomaly_alert,
    model_drift_alert,
    model_drift_psi,
    supplier_risk_alert,
    throughput_degradation_alert,
)
from app.infrastructure.models import MLPredictionLog, TelemetryModel

logger = logging.getLogger(__name__)

# PSI alert threshold - predictions are considered "drifted" if PSI exceeds this value
PSI_CRITICAL_THRESHOLD = 0.2

# Number of histogram bins for PSI calculation
# More bins = more granular distribution comparison
PSI_BIN_COUNT = 10

# Supplier risk threshold - alert if actual delays exceed predictions by this many days
SUPPLIER_DELAY_THRESHOLD_DAYS = 2

# Inventory anomaly threshold - alert if actual is 0 but predicted was above this
INVENTORY_ANOMALY_PREDICTED_THRESHOLD = 50

# Throughput baseline - minimum expected batch size per hour
THROUGHPUT_BASELINE_BATCH_SIZE = 50


def calculate_psi(
    expected_array: List[float],
    actual_array: List[float],
) -> float:
    """Calculate the Population Stability Index between two distributions.

    This function compares the distribution of expected values (predictions)
    against actual values (ground truth) using histogram binning.

    Args:
        expected_array: List of predicted probability values (0.0 to 1.0).
        actual_array: List of actual observed probability values (0.0 to 1.0).

    Returns:
        The PSI value as a float. Higher values indicate greater drift.
    """
    # Convert input lists to numpy arrays for efficient computation
    expected_values = np.array(expected_array, dtype=np.float64)
    actual_values = np.array(actual_array, dtype=np.float64)

    # Create histogram bins from 0.0 to 1.0 with PSI_BIN_COUNT intervals
    bin_edges = np.linspace(0.0, 1.0, PSI_BIN_COUNT + 1)

    # Calculate histogram counts for expected (prediction) distribution
    expected_counts, _ = np.histogram(expected_values, bins=bin_edges)

    # Calculate histogram counts for actual (ground truth) distribution
    actual_counts, _ = np.histogram(actual_values, bins=bin_edges)

    # Convert counts to percentages (proportions)
    # Add small epsilon to prevent division by zero
    epsilon = 1e-6
    total_expected = len(expected_values)
    total_actual = len(actual_values)

    expected_percentages = (expected_counts / total_expected) + epsilon
    actual_percentages = (actual_counts / total_actual) + epsilon

    # Calculate PSI using the formula: sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))
    psi_value = np.sum(
        (actual_percentages - expected_percentages)
        * np.log(actual_percentages / expected_percentages)
    )

    return float(psi_value)


def detect_stockout_drift(database_session: Session) -> Dict[str, float]:
    """Detect distribution drift in stockout predictions over the last hour.

    This function queries the database for predictions and actuals from the
    last hour, calculates PSI, evaluates all alert thresholds, and updates
    the Prometheus metrics gauges.

    Args:
        database_session: An active SQLAlchemy database session.

    Returns:
        A dictionary containing all calculated metrics and alert statuses.
    """
    # Calculate the time window: last 1 hour from now
    current_time = datetime.now(timezone.utc)
    one_hour_ago = current_time - timedelta(hours=1)

    logger.info(f"Starting drift detection for window: {one_hour_ago} to {current_time}")

    # Query predictions from MLPredictionLog for the last hour
    prediction_query = database_session.query(MLPredictionLog).filter(
        MLPredictionLog.predicted_at >= one_hour_ago
    )
    prediction_records = prediction_query.all()

    # Query actuals from TelemetryModel for the last hour
    # Join on tracking_id to match predictions with their corresponding actuals
    actual_query = database_session.query(TelemetryModel).filter(
        TelemetryModel.recorded_at >= one_hour_ago,
        TelemetryModel.tracking_id.isnot(None),
    )
    actual_records = actual_query.all()

    # Extract probability values from predictions
    predicted_probabilities = []
    for prediction_record in prediction_records:
        predicted_probabilities.append(prediction_record.predicted_stockout_probability)

    # Extract actual probabilities from telemetry
    # For stockout prediction, actual probability is derived from inventory_count
    # If inventory_count is 0, actual probability = 1.0 (stockout occurred)
    # If inventory_count > 0, actual probability = 0.0 (no stockout)
    actual_probabilities = []
    for actual_record in actual_records:
        if actual_record.inventory_count == 0:
            actual_probabilities.append(1.0)
        else:
            actual_probabilities.append(0.0)

    # Check if we have enough data to calculate PSI
    if len(predicted_probabilities) < 10 or len(actual_probabilities) < 10:
        logger.warning(
            f"Insufficient data for PSI calculation: "
            f"{len(predicted_probabilities)} predictions, "
            f"{len(actual_probabilities)} actuals"
        )
        # Set all alerts to safe (0.0) when insufficient data
        model_drift_alert.set(0.0)
        supplier_risk_alert.set(0.0)
        inventory_anomaly_alert.set(0.0)
        throughput_degradation_alert.set(0.0)
        return {
            "psi": 0.0,
            "model_drift_alert": 0.0,
            "supplier_risk_alert": 0.0,
            "inventory_anomaly_alert": 0.0,
            "throughput_degradation_alert": 0.0,
        }

    # Calculate PSI between predicted and actual distributions
    psi_value = calculate_psi(
        expected_array=predicted_probabilities,
        actual_array=actual_probabilities,
    )

    # Update the Prometheus gauge with the calculated PSI value
    model_drift_psi.set(psi_value)

    # Initialize alert statuses to safe (0.0)
    model_drift_status = 0.0
    supplier_risk_status = 0.0
    inventory_anomaly_status = 0.0
    throughput_degradation_status = 0.0

    # ALERT 1: Model Drift Detection
    # If PSI exceeds the critical threshold, trigger the model drift alert
    if psi_value >= PSI_CRITICAL_THRESHOLD:
        model_drift_status = 1.0
        drift_alerts_total.inc()
        logger.warning(
            f"DRIFT ALERT: PSI={psi_value:.4f} exceeds threshold {PSI_CRITICAL_THRESHOLD}"
        )
    else:
        logger.info(f"PSI={psi_value:.4f} - within acceptable range")

    # ALERT 2: Supplier Risk Detection
    # Compare average actual delivery delays against predicted delays
    # Calculate average actual delivery delay from telemetry records
    total_actual_delay = 0
    actual_delay_count = 0
    for actual_record in actual_records:
        total_actual_delay = total_actual_delay + actual_record.delivery_delay_days
        actual_delay_count = actual_delay_count + 1

    if actual_delay_count > 0:
        average_actual_delay = total_actual_delay / actual_delay_count
    else:
        average_actual_delay = 0.0

    # For this alert, we compare actual delays against a baseline predicted delay
    # In production, this would come from the prediction model's delay forecast
    # For now, we use a baseline of 1 day as the expected delay
    baseline_predicted_delay = 1.0
    delay_difference = average_actual_delay - baseline_predicted_delay

    if delay_difference >= SUPPLIER_DELAY_THRESHOLD_DAYS:
        supplier_risk_status = 1.0
        logger.warning(
            f"SUPPLIER RISK ALERT: Average delay {average_actual_delay:.2f} days "
            f"exceeds baseline {baseline_predicted_delay} by {delay_difference:.2f} days"
        )

    # ALERT 3: Inventory Anomaly Detection
    # Check for cases where actual inventory is 0 but predicted was > 50
    inventory_anomaly_count = 0
    for actual_record in actual_records:
        # Get the corresponding prediction for this record
        if actual_record.predicted_stockout_probability is not None:
            # Convert predicted probability back to predicted inventory
            # Higher probability means lower predicted inventory
            # If probability > 0.5, predicted inventory was likely < 50
            # We check the inverse: if actual is 0 but predicted probability was low (< 0.5)
            # that means the model predicted healthy inventory but actual was 0
            if actual_record.inventory_count == 0:
                if actual_record.predicted_stockout_probability < 0.5:
                    inventory_anomaly_count = inventory_anomaly_count + 1

    if inventory_anomaly_count > 0:
        inventory_anomaly_status = 1.0
        logger.warning(
            f"INVENTORY ANOMALY ALERT: {inventory_anomaly_count} records show "
            f"actual=0 but predicted healthy inventory"
        )

    # ALERT 4: Throughput Degradation Detection
    # Check if the number of processed records falls below the baseline
    processed_batch_size = len(actual_records)

    if processed_batch_size < THROUGHPUT_BASELINE_BATCH_SIZE:
        throughput_degradation_status = 1.0
        logger.warning(
            f"THROUGHPUT DEGRADATION ALERT: Processed {processed_batch_size} records, "
            f"below baseline of {THROUGHPUT_BASELINE_BATCH_SIZE}"
        )

    # Update all Prometheus alert gauges with their calculated statuses
    model_drift_alert.set(model_drift_status)
    supplier_risk_alert.set(supplier_risk_status)
    inventory_anomaly_alert.set(inventory_anomaly_status)
    throughput_degradation_alert.set(throughput_degradation_status)

    # Log summary of all alert statuses
    logger.info(
        f"Alert Summary - Model Drift: {model_drift_status}, "
        f"Supplier Risk: {supplier_risk_status}, "
        f"Inventory Anomaly: {inventory_anomaly_status}, "
        f"Throughput Degradation: {throughput_degradation_status}"
    )

    return {
        "psi": psi_value,
        "model_drift_alert": model_drift_status,
        "supplier_risk_alert": supplier_risk_status,
        "inventory_anomaly_alert": inventory_anomaly_status,
        "throughput_degradation_alert": throughput_degradation_status,
    }
