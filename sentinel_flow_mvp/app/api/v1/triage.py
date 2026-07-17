"""
Inventory Triage Dashboard — Aggregation & Urgency Classifier.

Beginner Note: A pharmacist cannot read 10,000 rows of individual batches.
They need to know what is dying (expiring) and what is empty (out of stock).
This endpoint aggregates all batches by medication (SKU), calculates the total
capital at risk, and sorts the entire pharmacy into actionable swimlanes.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date, timedelta
import logging

from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationBatchModel

logger = logging.getLogger("sentinel.inventory.triage")

router = APIRouter()

@router.get("/triage")
async def get_inventory_triage_dashboard(
    db: Session = Depends(get_database_session)
):
    """
    Returns aggregated inventory intelligence sorted by urgency.

    Response shape:
      {
        "metrics": {
          "total_value_inr": float,
          "capital_at_risk_inr": float,
          "out_of_stock_skus": int
        },
        "items": [
          {
            "sku_id": str,
            "total_stock": int,
            "closest_expiry": str (isoformat),
            "urgency_level": "CRITICAL" | "WARNING" | "HEALTHY"
          }
        ]
      }
    """
    logger.info("Executing Triage Dashboard Aggregation")

    today = date.today()
    critical_date = today + timedelta(days=30)

    batches = db.query(MedicationBatchModel).all()

    intelligence = {}
    total_value_on_shelves = 0.0
    capital_at_risk = 0.0
    out_of_stock_count = 0

    for batch in batches:
        sku = batch.sku_id
        if sku not in intelligence:
            intelligence[sku] = {
                "sku_id": sku,
                "total_stock": 0,
                "closest_expiry": batch.expiry_date,
                "urgency_level": "HEALTHY",
            }

        intelligence[sku]["total_stock"] += batch.available_quantity
        batch_value = float(batch.cost_price * batch.available_quantity)
        total_value_on_shelves += batch_value

        if batch.expiry_date < intelligence[sku]["closest_expiry"]:
            intelligence[sku]["closest_expiry"] = batch.expiry_date

        if batch.expiry_date <= critical_date:
            capital_at_risk += batch_value

    for sku, data in intelligence.items():
        if data["total_stock"] == 0:
            data["urgency_level"] = "CRITICAL"
            out_of_stock_count += 1
        elif data["closest_expiry"] <= critical_date:
            data["urgency_level"] = "CRITICAL"
        elif data["total_stock"] <= 50:
            data["urgency_level"] = "WARNING"

    sorted_items = sorted(
        list(intelligence.values()),
        key=lambda x: (
            x["urgency_level"] != "CRITICAL",
            x["urgency_level"] != "WARNING",
            x["total_stock"],
        ),
    )

    # Convert dates to iso strings for JSON serialization
    for item in sorted_items:
        if hasattr(item["closest_expiry"], "isoformat"):
            item["closest_expiry"] = item["closest_expiry"].isoformat()

    return {
        "metrics": {
            "total_value_inr": round(total_value_on_shelves, 2),
            "capital_at_risk_inr": round(capital_at_risk, 2),
            "out_of_stock_skus": out_of_stock_count,
        },
        "items": sorted_items,
    }
