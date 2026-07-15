"""
Seed Inventory — Populate medication_batches from medications table.
"""

import uuid
import logging
from datetime import date, timedelta
from app.infrastructure.database import SessionLocal, engine
from app.infrastructure.models import MedicationModel, MedicationBatchModel, Tenant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Price mapping per SKU — realistic MRP and cost for Indian generics
SKU_PRICES = {
    "ALLEGRA120":  (95.00, 75.00),
    "AMLOK5":      (65.00, 50.00),
    "AUGMENTIN625":(180.00, 140.00),
    "AZITH500":    (120.00, 95.00),
    "CALPOL650":   (35.00, 28.00),
    "GLYCOMET500": (55.00, 42.00),
    "PAN40":       (135.00, 105.00),
    "RISO20":      (250.00, 195.00),
    "TELMA40":     (110.00, 85.00),
    "THYRO50":     (45.00, 35.00),
    "ZIFI200":     (175.00, 135.00),
}

TENANT_ID = "PHARM-001"
BATCH_COUNT_PER_SKU = 2
SHELF_LOCATIONS = ["A-01", "A-02", "B-01", "B-02", "C-01"]


def seed_inventory():
    db = SessionLocal()
    try:
        # 1. Ensure the default tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == TENANT_ID).first()
        if not tenant:
            tenant = Tenant(
                tenant_id=TENANT_ID,
                name="Pharm-001 Pharmacy",
                upi_id="pharm001@upi",
                is_active=True,
                pincode="110001",
            )
            db.add(tenant)
            db.commit()
            logger.info(f"Created tenant {TENANT_ID}")

        # 2. Fetch all medications
        meds = db.query(MedicationModel).all()
        logger.info(f"Found {len(meds)} medications in DB")

        created = 0
        for med in meds:
            sku = med.sku_id
            mrp, cost = SKU_PRICES.get(sku, (100.0, 75.0))

            for i in range(BATCH_COUNT_PER_SKU):
                batch_id = f"{sku}-BATCH-{i+1}"
                existing = db.query(MedicationBatchModel).filter(
                    MedicationBatchModel.batch_id == batch_id
                ).first()
                if existing:
                    continue

                batch = MedicationBatchModel(
                    batch_id=batch_id,
                    sku_id=sku,
                    tenant_id=TENANT_ID,
                    expiry_date=date.today() + timedelta(days=365 + i * 180),
                    cost_price=cost,
                    max_retail_price=mrp,
                    available_quantity=50 + i * 100,
                    shelf_location=SHELF_LOCATIONS[created % len(SHELF_LOCATIONS)],
                )
                db.add(batch)
                created += 1

        db.commit()
        logger.info(f"Created {created} new batch records")

        # 3. Verify
        total = db.query(MedicationBatchModel).count()
        logger.info(f"medication_batches total: {total}")

    finally:
        db.close()


if __name__ == "__main__":
    seed_inventory()
