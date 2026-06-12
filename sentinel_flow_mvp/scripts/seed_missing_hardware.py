import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel, TelemetryModel
from datetime import datetime, timezone, timedelta
import random

def seed_missing_hardware():
    db = SessionLocal()
    try:
        suppliers = [
            {"id": "Intel", "sku": "SKU-IN-CORE-i9"},
            {"id": "AMD", "sku": "SKU-AMD-RYZEN9"},
            {"id": "ASUS Global", "sku": "SKU-AS-Z890"}
        ]
        
        now = datetime.now(timezone.utc)
        
        for s in suppliers:
            # Ensure supplier exists
            db.merge(SupplierModel(
                supplier_id=s["id"], 
                system_origin="SEEDER", 
                industry_vertical="HARDWARE", 
                created_at=now
            ))
            
            # Generate 90 days of telemetry
            for i in range(90):
                record_time = now - timedelta(days=(90 - i))
                inventory = int(500 + (random.uniform(-50, 50)) + (i * 2)) # Slight upward trend
                
                db.merge(TelemetryModel(
                    recorded_at=record_time,
                    supplier_id=s["id"],
                    sku_id=s["sku"],
                    inventory_count=inventory,
                    delivery_delay_days=random.randint(0, 5)
                ))
        db.commit()
        print("Missing hardware telemetry successfully injected.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_missing_hardware()
