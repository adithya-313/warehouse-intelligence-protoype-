import sys
import os

# Add parent directory to path so 'app' can be resolved
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set a fallback connection string for local execution if not running inside docker
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/sentinel_db")

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel

def seed_supplier():
    # 1. Connect to the database
    db = SessionLocal()
    try:
        # 2. Check if the supplier SUPP-001 already exists
        supplier = db.query(SupplierModel).filter(SupplierModel.supplier_id == "SUPP-001").first()
        
        # 3. If the supplier does not exist, we create and insert it
        if not supplier:
            print("Supplier 'SUPP-001' not found. Seeding now...")
            new_supplier = SupplierModel(
                supplier_id="SUPP-001",
                system_origin="MANUAL_SEED",
                industry_vertical="PHARMACY",
                industry_specific_metadata={"name": "MediCorp Global", "contact_info": "admin@medicorp.com"}
            )
            db.add(new_supplier)
            db.commit()
            print("Successfully seeded foundational supplier record (SUPP-001).")
        else:
            print("Supplier 'SUPP-001' already exists in the database. No action taken.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding supplier: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_supplier()
