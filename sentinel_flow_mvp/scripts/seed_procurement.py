"""
[STORY: THE PROCUREMENT LEDGER]
We are forging the history of three suppliers to test our dynamic Trust Engine.
SUPP-001: Flawless delivery (TRUSTED)
SUPP-002: Occasional delays and missing items (WARNING)
SUPP-003: Consistent failure and financial leakage (HIGH RISK)
"""

from datetime import datetime, timedelta
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel, PurchaseOrderModel, Tenant


def seed_procurement():
    db: SessionLocal = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        if not tenant:
            print("No tenant found. Aborting.")
            return

        print("Injecting Procurement History...")
        now = datetime.now()

        # Chapter 1: The Three Suppliers
        suppliers = [
            {"id": "SUPP-001", "name": "MediCorp Global"},
            {"id": "SUPP-002", "name": "Relief Logistics"},
            {"id": "SUPP-003", "name": "Apex Pharma"},
        ]

        for s in suppliers:
            if not db.query(SupplierModel).filter_by(supplier_id=s["id"]).first():
                db.add(SupplierModel(
                    supplier_id=s["id"],
                    system_origin="MANUAL",
                    industry_vertical="PHARMACEUTICALS",
                    industry_specific_metadata={"name": s["name"]},
                ))

        db.commit()
        print("  Suppliers created")

        # Chapter 2: Purchase Orders — Digital Contracts
        # SUPP-001: 2 orders, both flawless → trust = 100, TRUSTED
        for i in range(2):
            if not db.query(PurchaseOrderModel).filter_by(po_id=f"PO-MED-{i}").first():
                db.add(PurchaseOrderModel(
                    po_id=f"PO-MED-{i}", tenant_id=tenant.tenant_id, supplier_id="SUPP-001", sku_id="PAN40-BRAND",
                    ordered_qty=100, delivered_qty=100, cost_price=100.0, expected_mrp=110.0,
                    order_date=now - timedelta(days=10), expected_delivery_date=now - timedelta(days=5),
                    actual_delivery_date=now - timedelta(days=6),
                    status="FULFILLED",
                ))

        # SUPP-002: 3 orders, 2 failures (late + short) → trust = 100 - 30 = 70, WARNING
        for i in range(3):
            if not db.query(PurchaseOrderModel).filter_by(po_id=f"PO-REL-{i}").first():
                is_failure = i < 2
                db.add(PurchaseOrderModel(
                    po_id=f"PO-REL-{i}", tenant_id=tenant.tenant_id, supplier_id="SUPP-002", sku_id="AMOX500",
                    ordered_qty=200, delivered_qty=150 if is_failure else 200,
                    cost_price=40.0, expected_mrp=60.0,
                    order_date=now - timedelta(days=15), expected_delivery_date=now - timedelta(days=10),
                    actual_delivery_date=now - timedelta(days=8 if not is_failure else 12),
                    status="FULFILLED",
                ))

        # SUPP-003: 4 orders, all failures → trust = 100 - 60 = 40, HIGH RISK
        for i in range(4):
            if not db.query(PurchaseOrderModel).filter_by(po_id=f"PO-APX-{i}").first():
                db.add(PurchaseOrderModel(
                    po_id=f"PO-APX-{i}", tenant_id=tenant.tenant_id, supplier_id="SUPP-003", sku_id="PAN40-GENERIC",
                    ordered_qty=500, delivered_qty=300,
                    cost_price=10.0, expected_mrp=50.0,
                    order_date=now - timedelta(days=20), expected_delivery_date=now - timedelta(days=18),
                    actual_delivery_date=now - timedelta(days=10),
                    status="FULFILLED",
                ))

        db.commit()
        print("  Purchase orders created")
        print("Procurement Ledger Seeded Successfully.")

    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_procurement()
