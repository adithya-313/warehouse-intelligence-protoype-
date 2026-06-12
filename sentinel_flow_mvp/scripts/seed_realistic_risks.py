"""Deterministic Threat Injection for Risk Dashboard.

This script inserts mathematically perfect threat conditions into the
inventory_telemetry table so the Risk Dashboard UI displays real data.

Why this script exists:
    The ML inference pipeline (Chronos-T5 + LoRA) is not yet writing results
    back to the predicted_stockout_probability and is_critical_risk columns.
    Rather than waiting for that pipeline, we inject the "end state" that the
    ML pipeline would eventually produce. This lets us test the full frontend
    stack immediately.

What it does:
    - SKU-NV-5090 (NVIDIA): Critical stockout  (inventory=5, prob=0.95, critical=True)
    - SKU-AS-Z890  (ASUS):   Dead stock          (inventory=0, delay=21)
    - SKU-AMD-9950X (AMD):   Anomaly             (delay=8, prob=0.45)

Foreign key safety:
    The script creates any missing parent Supplier rows before inserting
    telemetry, so it never violates the suppliers FK constraint.
"""

import sys
import os
import uuid
from datetime import datetime, timezone

# Add the project root to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import get_application_settings


def seed_realistic_risks():
    """Insert controlled risk scenarios into inventory_telemetry."""
    print("Starting deterministic risk injection...")

    # Load the database URL from our application settings.
    # This reads DATABASE_URL from the .env file automatically.
    settings = get_application_settings()
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        # ------------------------------------------------------------------
        # STEP 1: Ensure parent Supplier rows exist for all three targets.
        # The inventory_telemetry table has a foreign key constraint
        # referencing suppliers(supplier_id), so we must insert the
        # supplier before we can insert telemetry for it.
        # We use ON CONFLICT DO NOTHING so this is safe to re-run.
        # ------------------------------------------------------------------
        print("Ensuring supplier records exist (UPSERT)...")

        # Define the three suppliers we need. Note: AMD is NOT in the
        # original seed_hardware_domain.py, so we create it here.
        suppliers = [
            {"id": "NVIDIA Corporation", "system": "SAP", "vertical": "HARDWARE"},
            {"id": "ASUS Global",        "system": "SAP", "vertical": "HARDWARE"},
            {"id": "AMD",                "system": "SAP", "vertical": "HARDWARE"},
        ]

        for supplier in suppliers:
            conn.execute(
                text("""
                    INSERT INTO suppliers (supplier_id, system_origin, industry_vertical)
                    VALUES (:id, :sys, :vert)
                    ON CONFLICT (supplier_id) DO NOTHING
                """),
                {"id": supplier["id"], "sys": supplier["system"], "vert": supplier["vertical"]}
            )
        print("  -> Supplier records ready.")

        # ------------------------------------------------------------------
        # STEP 2: Inject telemetry records with precisely crafted risk values.
        #
        # Each record targets a different risk category:
        #   Stockout  → high probability + critical flag
        #   Dead stock→ zero inventory + extended delay
        #   Anomaly   → moderate delay + elevated probability
        #
        # We use recent timestamps so the 30-day filter in risk_service.py
        # will include them.
        # ------------------------------------------------------------------
        now = datetime.now(timezone.utc)

        # We insert one record per risk type for clarity.
        # Each gets a unique tracking_id so the ML prediction log is linkable.
        telemetry_rows = [
            # --- Critical Stockout: SKU-NV-5090 (NVIDIA) ---
            # inventory_count=5 is well below typical demand.
            # predicted_stockout_probability=0.95 means the model is highly confident.
            # is_critical_risk=True triggers the red "critical" badge in the UI.
            {
                "recorded_at": now,
                "supplier_id": "NVIDIA Corporation",
                "tracking_id": str(uuid.uuid4()),
                "sku_id": "SKU-NV-5090",
                "inventory_count": 5,
                "delivery_delay_days": 3,
                "predicted_stockout_probability": 0.95,
                "is_critical_risk": True,
            },
            # --- Dead Stock: SKU-AS-Z890 (ASUS) ---
            # inventory_count=0 means there is no stock moving.
            # delivery_delay_days=21 (>14 threshold) flags it as dead stock.
            # No predicted probability needed — dead stock is purely inventory-driven.
            {
                "recorded_at": now,
                "supplier_id": "ASUS Global",
                "tracking_id": str(uuid.uuid4()),
                "sku_id": "SKU-AS-Z890",
                "inventory_count": 0,
                "delivery_delay_days": 21,
                "predicted_stockout_probability": None,
                "is_critical_risk": False,
            },
            # --- Anomaly: SKU-AMD-9950X (AMD) ---
            # delivery_delay_days=8 (>7 threshold) combined with
            # predicted_stockout_probability=0.45 (>0.3 threshold) triggers
            # the anomaly category. The UI will show a "warning" badge
            # because delay < 20 and prob < 0.7.
            {
                "recorded_at": now,
                "supplier_id": "AMD",
                "tracking_id": str(uuid.uuid4()),
                "sku_id": "SKU-AMD-9950X",
                "inventory_count": 150,
                "delivery_delay_days": 8,
                "predicted_stockout_probability": 0.45,
                "is_critical_risk": False,
            },
        ]

        for row in telemetry_rows:
            conn.execute(
                text("""
                    INSERT INTO inventory_telemetry
                        (recorded_at, supplier_id, tracking_id, sku_id,
                         inventory_count, delivery_delay_days,
                         predicted_stockout_probability, is_critical_risk)
                    VALUES
                        (:recorded_at, :supplier_id, :tracking_id, :sku_id,
                         :inventory_count, :delivery_delay_days,
                         :predicted_stockout_probability, :is_critical_risk)
                """),
                row
            )

        conn.commit()

    print("Risk injection complete.")
    print("  -> NVIDIA / SKU-NV-5090  → Critical Stockout  (inventory=5, prob=0.95, critical=True)")
    print("  -> ASUS   / SKU-AS-Z890  → Dead Stock         (inventory=0, delay=21d)")
    print("  -> AMD    / SKU-AMD-9950X → Anomaly            (delay=8d, prob=0.45)")
    print("Refresh the Global Risk Matrix in the browser to see results.")


if __name__ == "__main__":
    seed_realistic_risks()
