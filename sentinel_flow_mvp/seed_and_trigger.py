import os
import sys
from datetime import datetime, timezone

# Ensure the app is in the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from sentinel_flow_mvp.app.infrastructure.database import SessionLocal
    from sentinel_flow_mvp.app.infrastructure.models import (
        Tenant, SupplierModel, MedicationModel, ExogenousCovariateModel
    )
except ModuleNotFoundError:
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.models import (
        Tenant, SupplierModel, MedicationModel, ExogenousCovariateModel
    )

def seed_and_trigger():
    db = SessionLocal()
    try:
        print("1. Checking Tenant...")
        tenant = db.query(Tenant).first()
        if not tenant:
            tenant = Tenant(tenant_id="system_admin", name="Default Pharmacy", pincode="560001", is_active=True)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        
        pincode = tenant.pincode or "560001"

        print("2. Checking Supplier...")
        supplier = db.query(SupplierModel).first()
        if not supplier:
            supplier = SupplierModel(
                supplier_id="SUPP-001", 
                system_origin="ERP", 
                industry_vertical="PHARMA",
                industry_specific_metadata={"name": "Apex Pharma Distributors"}
            )
            db.add(supplier)
            db.commit()

        print("3. Checking Medication...")
        med = db.query(MedicationModel).filter(MedicationModel.sku_id.ilike("%para%")).first()
        if not med:
            med = MedicationModel(
                sku_id="SKU-PARA-500",
                apis=["Paracetamol"],
                therapeutic_classes=["Analgesic"],
                cdsco_schedule="OTC"
            )
            db.add(med)
            db.commit()

        print("4. Injecting Disease Wave Covariate...")
        threat = ExogenousCovariateModel(
            pincode=pincode,
            timestamp=datetime.now(timezone.utc),
            humidity_percent=92.5,
            symptom_keyword="viral fever treatments",
            trend_score=95.0  # > 70.0 triggers the UI
        )
        db.add(threat)
        db.commit()
        
        print(f"SUCCESS: Database seeded. Disease wave injected for pincode {pincode}.")
        print("ACTION REQUIRED: Refresh your frontend at http://localhost:3000/pos")

    except Exception as e:
        print(f"FAILED: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_and_trigger()
