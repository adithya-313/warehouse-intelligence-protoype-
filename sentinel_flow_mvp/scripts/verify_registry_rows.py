from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import LoRAAdapterRegistry
import json

def verify_registry_rows():
    print("INITIATING ROW-LEVEL DATABASE AUDIT...")
    db = SessionLocal()
    try:
        adapters = db.query(LoRAAdapterRegistry).order_by(LoRAAdapterRegistry.created_at.desc()).all()

        print(f"\nFound {len(adapters)} total adapter records in PostgreSQL:\n")
        print(f"{'MODULE':<18} | {'STATUS':<18} | {'WEIGHTS PATH'}")
        print("-" * 80)

        for adapter in adapters:
            print(f"{adapter.module_name:<18} | {adapter.status:<18} | {adapter.adapter_weights_path}")

        report = {
            "phase": "UI_ROW_LEVEL_SYNC_PROOF",
            "status": "COMPLETED",
            "db_row_count": len(adapters),
            "statuses_found": [a.status for a in adapters]
        }
        with open("/app/row_sync_proof.json", "w") as f:
            json.dump(report, f, indent=2)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    verify_registry_rows()
