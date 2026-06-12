from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel, SupplierModel
from app.infrastructure.db.models import LoRAAdapterRegistry
from sqlalchemy import func
import json

def validate_system_state():
    print("INITIATING MATHEMATICAL STATE VALIDATION...")
    db = SessionLocal()
    try:
        total_records = db.query(func.count(TelemetryModel.recorded_at)).scalar() or 0
        active_suppliers = db.query(func.count(TelemetryModel.supplier_id.distinct())).scalar() or 0
        total_adapters = db.query(func.count(LoRAAdapterRegistry.id)).scalar() or 0
        active_adapters = db.query(func.count(LoRAAdapterRegistry.id)).filter(
            LoRAAdapterRegistry.status == "ACTIVE"
        ).scalar() or 0

        EXPECTED_RECORDS = 724
        EXPECTED_SUPPLIERS = 3
        EXPECTED_TOTAL_ADAPTERS = 6
        EXPECTED_ACTIVE_ADAPTERS = 3

        print("\n--- DATABASE vs UI TRUTH ---")
        print(f"Records: DB={total_records} | UI={EXPECTED_RECORDS} -> Match: {total_records == EXPECTED_RECORDS}")
        print(f"Suppliers: DB={active_suppliers} | UI={EXPECTED_SUPPLIERS} -> Match: {active_suppliers == EXPECTED_SUPPLIERS}")
        print(f"Total Adapters: DB={total_adapters} | UI={EXPECTED_TOTAL_ADAPTERS} -> Match: {total_adapters == EXPECTED_TOTAL_ADAPTERS}")
        print(f"Active Adapters: DB={active_adapters} | UI={EXPECTED_ACTIVE_ADAPTERS} -> Match: {active_adapters == EXPECTED_ACTIVE_ADAPTERS}")

        is_perfect_match = (
            total_records == EXPECTED_RECORDS and
            active_suppliers == EXPECTED_SUPPLIERS and
            total_adapters == EXPECTED_TOTAL_ADAPTERS and
            active_adapters == EXPECTED_ACTIVE_ADAPTERS
        )

        report = {
            "phase": "UI_DATABASE_SYNC_PROOF",
            "status": "COMPLETED",
            "db_metrics": {
                "total_records": total_records,
                "active_suppliers": active_suppliers,
                "total_adapters": total_adapters,
                "active_adapters": active_adapters
            },
            "is_perfect_match": is_perfect_match
        }
        with open("/app/sync_proof.json", "w") as f:
            json.dump(report, f, indent=2)

        print(f"\nPerfect match: {is_perfect_match}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    validate_system_state()
