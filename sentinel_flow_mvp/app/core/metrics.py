"""Prometheus Metrics Registry for Sentinel-Flow.

This module initializes global Prometheus metrics for monitoring
model drift, prediction latency, and system health.

Metrics are instantiated at module load time to ensure thread-safe
registration and prevent multiprocess metric corruption.
"""

from prometheus_client import Counter, Gauge, make_asgi_app

# Gauge metric for tracking the Population Stability Index (PSI)
# PSI measures the drift between predicted and actual distributions
# A PSI > 0.2 indicates significant drift requiring investigation
model_drift_psi = Gauge(
    "model_drift_psi",
    "Population Stability Index of stockout predictions",
    ["supplier_id"],
)

# Counter metric for tracking the total number of drift alerts triggered
# Incremented each time PSI exceeds the critical threshold (0.2)
drift_alerts_total = Counter(
    "drift_alerts_total",
    "Total number of drift alerts triggered",
)

# Counter metric for tracking total predictions processed
# Useful for calculating prediction throughput and error rates
predictions_processed_total = Counter(
    "predictions_processed_total",
    "Total number of ML predictions processed",
)

# Gauge metric for tracking the current number of active Celery workers
# Helps monitor worker pool health and scaling needs
active_worker_count = Gauge(
    "active_worker_count",
    "Current number of active Celery worker processes",
)

# Alert Gauges - 1.0 = triggered, 0.0 = safe
# These binary gauges provide instant visibility into system health

# Model Drift Alert - triggered when PSI exceeds 0.2
model_drift_alert = Gauge(
    "model_drift_alert",
    "Model drift alert status (1.0 = triggered, 0.0 = safe)",
)

# Supplier Risk Alert - triggered when actual delivery delays exceed predictions by 2+ days
supplier_risk_alert = Gauge(
    "supplier_risk_alert",
    "Supplier risk alert status (1.0 = triggered, 0.0 = safe)",
)

# Inventory Anomaly Alert - triggered when actual inventory is 0 but predicted was > 50
inventory_anomaly_alert = Gauge(
    "inventory_anomaly_alert",
    "Inventory anomaly alert status (1.0 = triggered, 0.0 = safe)",
)

# Throughput Degradation Alert - triggered when processed batch size falls below baseline
throughput_degradation_alert = Gauge(
    "throughput_degradation_alert",
    "Throughput degradation alert status (1.0 = triggered, 0.0 = safe)",
)


def get_metrics_app():
    """Create and return the Prometheus metrics ASGI application.

    This function returns a FastAPI-compatible ASGI app that serves
    the /metrics endpoint for Prometheus scraping.

    Returns:
        An ASGI application that exposes Prometheus metrics.
    """
    return make_asgi_app()
