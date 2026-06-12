import sys
import os

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import LoRAAdapterRegistry

def main():
    db = SessionLocal()
    try:
        try:
            db.execute(text("ALTER TABLE lora_adapter_registry ADD COLUMN supplier_id VARCHAR;"))
            db.commit()
            print("Added supplier_id column")
        except Exception as e:
            db.rollback()
            print(f"Column might exist: {e}")

        adapters = db.query(LoRAAdapterRegistry).all()
        count = 0
        for a in adapters:
            if getattr(a, "status", None) == "VALIDATING":
                a.status = "ACTIVE"
                count += 1
        db.commit()
        print(f"Successfully promoted {count} adapters.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
