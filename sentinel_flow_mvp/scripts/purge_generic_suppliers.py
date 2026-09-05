import sys
import os
import argparse

# Ensure the app module can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel, TelemetryModel
from app.infrastructure.db.models import LoRAAdapterRegistry
from sqlalchemy import not_, select

# This guard prevents accidental execution against production databases.
# This script deletes supplier and telemetry records not on a hardcoded
# whitelist and should only be run against local dev databases.
def check_safety():
    parser = argparse.ArgumentParser(
        description="Delete suppliers and related data not on a hardware whitelist. "
                    "This deletes records from multiple tables and should only run "
                    "against a local dev database."
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Required flag to confirm you understand this deletes supplier and telemetry records."
    )
    args = parser.parse_args()

    if not args.i_know_what_im_doing:
        print("WARNING: This script deletes supplier and related telemetry records.")
        print("It should ONLY be run against a local dev database.")
        print("To proceed, re-run with: python purge_generic_suppliers.py --i-know-what-im-doing")
        sys.exit(1)

    # Check DATABASE_URL doesn't look like production
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            host_part = db_url.split("@")[-1].split("/")[0]
            hostname = host_part.split(":")[0]
            allowed_hosts = ["localhost", "127.0.0.1", "timescaledb"]
            if hostname not in allowed_hosts:
                print(f"ERROR: DATABASE_URL hostname '{hostname}' is not a local/dev host.")
                print(f"Allowed hosts: {allowed_hosts}")
                print("This script should only run against local dev databases.")
                sys.exit(1)
        except Exception:
            pass

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
    check_safety()
    enforce_hardware_domain()
