import sys
import os

# Ensure the app module can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel, TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry
from sqlalchemy import not_, select

ALLOWED_HARDWARE_SUPPLIERS = ["NVIDIA", "Intel", "AMD", "ASUS", "TSMC", "NVIDIA Corporation", "ASUS Global"]

def enforce_hardware_domain():
    print("INITIATING DOMAIN ENFORCEMENT PURGE...")
    db = SessionLocal()
    
    try:
        # First, find IDs of suppliers that are NOT in the whitelist
        invalid_suppliers = db.scalars(
            select(SupplierModel.supplier_id).where(not_(SupplierModel.supplier_id.in_(ALLOWED_HARDWARE_SUPPLIERS)))
        ).all()
        
        if not invalid_suppliers:
            print("Database is already compliant. No generic suppliers found.")
            return

        print(f"Found {len(invalid_suppliers)} generic suppliers to purge.")

        # Delete dependent records first to satisfy foreign key constraints
        # Delete from LoRAAdapterRegistry
        deleted_lora = db.query(LoRAAdapterRegistry).filter(
            LoRAAdapterRegistry.supplier_id.in_(invalid_suppliers)
        ).delete(synchronize_session=False)
        print(f"  -> Deleted {deleted_lora} LoRA adapter records.")

        # Delete from TelemetryModel
        deleted_telemetry = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id.in_(invalid_suppliers)
        ).delete(synchronize_session=False)
        print(f"  -> Deleted {deleted_telemetry} telemetry records.")

        # Delete from SupplierModel
        deleted_suppliers = db.query(SupplierModel).filter(
            SupplierModel.supplier_id.in_(invalid_suppliers)
        ).delete(synchronize_session=False)
        print(f"  -> Deleted {deleted_suppliers} supplier records.")

        db.commit()
        print("DOMAIN ENFORCEMENT COMPLETE. Database is now strictly Hardware Supply Chain.")
        
    except Exception as e:
        db.rollback()
        print(f"Error during purge: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    enforce_hardware_domain()
