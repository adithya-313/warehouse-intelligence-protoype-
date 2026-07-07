from datetime import datetime, timezone
from sentinel_flow_mvp.app.infrastructure.database import SessionLocal
from sentinel_flow_mvp.app.infrastructure.models import ExogenousCovariateModel, Tenant

def simulate_disease_wave():
    db = SessionLocal()
    try:
        # 1. Get an active pincode
        tenant = db.query(Tenant).first()
        pincode = tenant.pincode if tenant and tenant.pincode else "560001"

        # 2. Inject a critical trend score (> 70.0)
        threat = ExogenousCovariateModel(
            pincode=pincode,
            timestamp=datetime.now(timezone.utc),
            humidity_percent=92.5,
            symptom_keyword="viral fever treatments",
            trend_score=95.0  # THIS TRIGGERS THE UI BANNER
        )
        db.add(threat)
        db.commit()
        print(f"SUCCESS: Synthetic disease wave injected for pincode {pincode} with Trend Score 95.0")
    except Exception as e:
        print(f"FAILED: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    simulate_disease_wave()