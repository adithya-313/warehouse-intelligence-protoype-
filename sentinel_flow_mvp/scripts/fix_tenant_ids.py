from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel

def repair_tenant_isolation():
    print("REPAIRING TENANT SECURITY BADGES...")
    db = SessionLocal()
    try:
        nv_telemetry = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id == "NVIDIA Corporation"
        ).update({"tenant_id": "tenant_alpha"}, synchronize_session="fetch")

        beta_telemetry = db.query(TelemetryModel).filter(
            TelemetryModel.supplier_id != "NVIDIA Corporation"
        ).update({"tenant_id": "tenant_beta"}, synchronize_session="fetch")

        db.commit()
        print(f"Assigned {nv_telemetry} records to tenant_alpha (NVIDIA).")
        print(f"Assigned {beta_telemetry} records to tenant_beta (Others).")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    repair_tenant_isolation()
