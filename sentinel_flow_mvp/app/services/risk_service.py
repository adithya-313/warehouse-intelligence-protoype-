"""Risk dashboard service for supply chain threat detection.

Queries the inventory telemetry and supplier tables to produce
a live risk overlay of stockouts, dead stock, and anomalies.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import Float, cast, func
from sqlalchemy.orm import Session

from app.infrastructure.models import SupplierModel, TelemetryModel

logger = logging.getLogger(__name__)


def get_risk_dashboard(database_session: Session, tenant_id: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """Build the risk dashboard response from live telemetry.

    Returns:
        A dict with three keys (stockouts, dead_stock, anomalies)
        each containing a list of risk items.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    latest_telemetry = (
        database_session.query(
            TelemetryModel.supplier_id,
            TelemetryModel.inventory_count,
            TelemetryModel.delivery_delay_days,
            TelemetryModel.predicted_stockout_probability,
            TelemetryModel.is_critical_risk,
            TelemetryModel.recorded_at,
            SupplierModel.industry_vertical,
        )
        .join(SupplierModel, TelemetryModel.supplier_id == SupplierModel.supplier_id)
        .filter(TelemetryModel.recorded_at >= cutoff)
        .filter(TelemetryModel.tenant_id == tenant_id)
        .order_by(TelemetryModel.recorded_at.desc())
        .all()
    )

    stockouts: List[Dict[str, Any]] = []
    dead_stock: List[Dict[str, Any]] = []
    anomalies: List[Dict[str, Any]] = []

    seen: set = set()
    for row in latest_telemetry:
        if row.supplier_id in seen:
            continue
        seen.add(row.supplier_id)

        supplier_id = row.supplier_id
        inventory = row.inventory_count
        delay = row.delivery_delay_days
        prob = row.predicted_stockout_probability or 0.0
        critical = row.is_critical_risk or False

        if critical or prob > 0.7:
            stockouts.append({
                "supplier_id": supplier_id,
                "metric": f"Stockout probability: {prob:.0%}",
                "value": f"{inventory} units",
                "severity": "critical" if critical else "warning",
            })

        if inventory == 0 and delay > 14:
            dead_stock.append({
                "supplier_id": supplier_id,
                "metric": f"No inventory for {delay} days",
                "value": f"{delay}d stale",
                "severity": "warning" if delay < 30 else "critical",
            })

        if delay > 7 and prob > 0.3:
            anomalies.append({
                "supplier_id": supplier_id,
                "metric": f"Delay ({delay}d) + elevated risk",
                "value": f"{prob:.0%} risk",
                "severity": "critical" if delay > 20 else "warning",
            })

    if not stockouts and not dead_stock and not anomalies:
        stockouts.append({
            "supplier_id": "system",
            "metric": "No critical stockouts detected",
            "value": "nominal",
            "severity": "info",
        })

    return {
        "stockouts": stockouts,
        "dead_stock": dead_stock,
        "anomalies": anomalies,
    }
