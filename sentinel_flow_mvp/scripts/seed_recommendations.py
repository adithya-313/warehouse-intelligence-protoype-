"""
[STORY: THE SEED OF INTELLIGENCE]
A recommendation engine is only as smart as its data. 
We need to give our system two things: 
1. "Siblings" - Medications with the exact same Active Pharmaceutical Ingredients (APIs) but different margins.
2. "Experience" - Ghost transactions showing that two items are frequently bought together.
"""

import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import (
    MedicationModel, MedicationBatchModel,
    SaleReceiptModel, SaleLineItemModel, Tenant
)


def seed_intelligence():
    db: Session = SessionLocal()

    try:
        tenant = db.query(Tenant).first()
        if not tenant:
            print("No tenant found. Please run core seeders first.")
            return

        print("🌱 Injecting Recommendation Intelligence...")

        # ================================================================
        # Chapter 1: The Generic Siblings (High-Margin Triggers)
        # They both share the exact same API: "Pantoprazole".
        # ================================================================

        brand_sku = "PAN40-BRAND"
        generic_sku = "PAN40-GENERIC"
        antibiotic_sku = "AMOX500"
        needs_meds_commit = False

        # 1A. The Expensive Brand (Low profit margin)
        if not db.query(MedicationModel).filter_by(sku_id=brand_sku).first():
            db.add(MedicationModel(
                sku_id=brand_sku,
                apis=["Pantoprazole"],
                therapeutic_classes=["Antacid"],
                cdsco_schedule="OTC",
                pregnancy_category="C",
                pediatric_age_threshold_months=0,
                is_approved_by_curator=True,
            ))
            needs_meds_commit = True

        # 1B. The Profitable Generic (High profit margin)
        if not db.query(MedicationModel).filter_by(sku_id=generic_sku).first():
            db.add(MedicationModel(
                sku_id=generic_sku,
                apis=["Pantoprazole"],
                therapeutic_classes=["Antacid"],
                cdsco_schedule="OTC",
                pregnancy_category="C",
                pediatric_age_threshold_months=0,
                is_approved_by_curator=True,
            ))
            needs_meds_commit = True

        # Antibiotic for cross-sell
        if not db.query(MedicationModel).filter_by(sku_id=antibiotic_sku).first():
            db.add(MedicationModel(
                sku_id=antibiotic_sku,
                apis=["Amoxicillin"],
                therapeutic_classes=["Antibiotic"],
                cdsco_schedule="Schedule H",
                pregnancy_category="B",
                pediatric_age_threshold_months=0,
                is_approved_by_curator=True,
            ))
            needs_meds_commit = True

        # Flush medications so FK constraints are satisfied for batches
        if needs_meds_commit:
            db.commit()
            print("  ✓ Medications created")

        # ================================================================
        # Chapter 2: Inventory Batches for the new SKUs
        # ================================================================

        needs_batch_commit = False

        if not db.query(MedicationBatchModel).filter_by(batch_id=f"{brand_sku}-B1").first():
            db.add(MedicationBatchModel(
                batch_id=f"{brand_sku}-B1",
                sku_id=brand_sku,
                tenant_id=tenant.tenant_id,
                available_quantity=100,
                expiry_date=datetime.now().date() + timedelta(days=365),
                cost_price=100.00,
                max_retail_price=110.00,
            ))
            needs_batch_commit = True

        if not db.query(MedicationBatchModel).filter_by(batch_id=f"{generic_sku}-B1").first():
            db.add(MedicationBatchModel(
                batch_id=f"{generic_sku}-B1",
                sku_id=generic_sku,
                tenant_id=tenant.tenant_id,
                available_quantity=500,
                expiry_date=datetime.now().date() + timedelta(days=365),
                cost_price=10.00,
                max_retail_price=50.00,
            ))
            needs_batch_commit = True

        if not db.query(MedicationBatchModel).filter_by(batch_id=f"{antibiotic_sku}-B1").first():
            db.add(MedicationBatchModel(
                batch_id=f"{antibiotic_sku}-B1",
                sku_id=antibiotic_sku,
                tenant_id=tenant.tenant_id,
                available_quantity=200,
                expiry_date=datetime.now().date() + timedelta(days=365),
                cost_price=40.00,
                max_retail_price=60.00,
            ))
            needs_batch_commit = True

        if needs_batch_commit:
            db.commit()
            print("  ✓ Batches created")

        # ================================================================
        # Chapter 3: The Ghost Transactions (Cross-Sell Triggers)
        # 5 receipts where AMOX500 was bought with PAN40-BRAND.
        # ================================================================

        existing = db.query(SaleReceiptModel).join(
            SaleLineItemModel, SaleReceiptModel.id == SaleLineItemModel.receipt_id
        ).filter(
            SaleLineItemModel.batch_id == f"{antibiotic_sku}-B1"
        ).count()

        if existing == 0:
            print("  📜 Forging historical cross-sell transactions...")
            for i in range(5):
                receipt_id = str(uuid.uuid4())
                db.add(SaleReceiptModel(
                    id=receipt_id,
                    tenant_id=tenant.tenant_id,
                    total_amount_inr=170.00,
                    payment_method="CASH",
                    timestamp=datetime.now() - timedelta(days=30 - i),
                ))

                db.add(SaleLineItemModel(
                    receipt_id=receipt_id,
                    batch_id=f"{antibiotic_sku}-B1",
                    tenant_id=tenant.tenant_id,
                    quantity_sold=1,
                    price_per_unit=60.00,
                ))

                db.add(SaleLineItemModel(
                    receipt_id=receipt_id,
                    batch_id=f"{brand_sku}-B1",
                    tenant_id=tenant.tenant_id,
                    quantity_sold=1,
                    price_per_unit=110.00,
                ))

            db.commit()
            print("  ✓ Ghost transactions created")
        else:
            print("  ✓ Ghost transactions already exist")

        print("✅ DATA LAYER SEEDED")

    except Exception as e:
        db.rollback()
        print(f"❌ Database error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_intelligence()
