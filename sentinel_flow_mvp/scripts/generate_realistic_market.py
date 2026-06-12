import time
import logging
from datetime import datetime, timedelta, timezone
import uuid
import sys
import os
import math

import numpy as np

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.database import SessionLocal, engine
from app.infrastructure.models import SupplierModel, TelemetryModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

def generate_realistic_market():
    session = SessionLocal()
    
    try:
        start_time = time.time()
        
        # Step 1: Truncate existing telemetry
        logger.info("Wiping existing dummy telemetry...")
        session.execute(text("TRUNCATE TABLE inventory_telemetry CASCADE;"))
        session.commit()
        logger.info("[DATA WIPED] Old dummy data successfully truncated.")
        
        # Ensure the 4 specific suppliers exist
        suppliers = [
            {"supplier_id": "NVIDIA Corporation", "system_origin": "REALISTIC_GEN", "industry_vertical": "SEMICONDUCTOR", "created_at": datetime.now(timezone.utc)},
            {"supplier_id": "Intel Corp", "system_origin": "REALISTIC_GEN", "industry_vertical": "SEMICONDUCTOR", "created_at": datetime.now(timezone.utc)},
            {"supplier_id": "AMD Inc", "system_origin": "REALISTIC_GEN", "industry_vertical": "SEMICONDUCTOR", "created_at": datetime.now(timezone.utc)},
            {"supplier_id": "Corsair Components", "system_origin": "REALISTIC_GEN", "industry_vertical": "HARDWARE", "created_at": datetime.now(timezone.utc)},
        ]
        
        for s in suppliers:
            existing = session.query(SupplierModel).filter_by(supplier_id=s["supplier_id"]).first()
            if not existing:
                new_supplier = SupplierModel(**s)
                session.add(new_supplier)
        session.commit()

        # Step 2: Set date range
        end_date = datetime.now(timezone.utc) - timedelta(days=1)
        start_date = datetime.now(timezone.utc) - timedelta(days=3*365)
        days = (end_date - start_date).days
        
        telemetry_records = []
        
        logger.info(f"Generating data for {days} days...")
        
        for t in range(days):
            record_date = start_date + timedelta(days=t)
            days_ago = days - t
            
            # NVIDIA | SKU-NV-AI900 (The Viral Spike)
            # Baseline 50. 6 months ago (180 days ago), exponential multiplier to ~400
            nv_demand = 50 + np.random.normal(0, 5)
            if days_ago <= 180:
                # Exponential curve from 50 to 400 over 180 days
                # y = 50 * e^(k * x) => 400 = 50 * e^(k * 180) => 8 = e^(k*180) => k = ln(8)/180
                k = math.log(8) / 180
                days_since_boom = 180 - days_ago
                nv_demand = 50 * math.exp(k * days_since_boom) + np.random.normal(0, 10)
            
            nv_inv = max(0, 500 - nv_demand * 1.1)
            
            telemetry_records.append({
                "recorded_at": record_date,
                "supplier_id": "NVIDIA Corporation",
                "sku_id": "SKU-NV-AI900",
                "tracking_id": str(uuid.uuid4()),
                "inventory_count": int(max(0, nv_inv)),
                "delivery_delay_days": int(np.random.gamma(2.0, 1.0)),
                "is_critical_risk": False
            })
            
            # Intel | SKU-IN-CORE-i9 (The Seasonal Beast)
            # Sine wave to create spikes every Nov/Dec and Jul/Aug
            # Using month of the year to create specific spikes
            month = record_date.month
            if month in [11, 12, 7, 8]:
                in_demand = 300 + np.random.normal(0, 30)
            else:
                in_demand = 80 + np.random.normal(0, 10)
            
            in_inv = max(0, 400 - in_demand * 1.0)
            
            telemetry_records.append({
                "recorded_at": record_date,
                "supplier_id": "Intel Corp",
                "sku_id": "SKU-IN-CORE-i9",
                "tracking_id": str(uuid.uuid4()),
                "inventory_count": int(max(0, in_inv)),
                "delivery_delay_days": int(np.random.gamma(2.0, 1.0)),
                "is_critical_risk": False
            })
            
            # AMD | SKU-AMD-LEGACY (The Phasing Out)
            # Linear negative slope starting at 200 3 years ago, decaying to 0
            amd_demand = 200 * (days_ago / days) + np.random.normal(0, 5)
            amd_inv = max(0, 250 - amd_demand * 1.0)
            
            telemetry_records.append({
                "recorded_at": record_date,
                "supplier_id": "AMD Inc",
                "sku_id": "SKU-AMD-LEGACY",
                "tracking_id": str(uuid.uuid4()),
                "inventory_count": int(max(0, amd_inv)),
                "delivery_delay_days": int(np.random.gamma(2.0, 1.0)),
                "is_critical_risk": False
            })
            
            # Corsair | SKU-CR-RAM (The Supply Chain Shock)
            # Stable demand of 100 with heavy noise.
            # Middle of dataset: spike delivery_delay_days massively for 3 months
            cr_demand = 100 + np.random.normal(0, 20)
            cr_delay = int(np.random.gamma(2.0, 1.0))
            
            # 3-year = ~1095 days. Middle = day 547. 3-month window = 90 days.
            if 500 <= t <= 590:
                cr_delay = int(np.random.uniform(15, 45)) # Massive shipping crisis
                
            if cr_delay > 10:
                cr_inv = 0  # Hits 0 frequently during crisis
            else:
                cr_inv = max(0, 200 - cr_demand)
                
            telemetry_records.append({
                "recorded_at": record_date,
                "supplier_id": "Corsair Components",
                "sku_id": "SKU-CR-RAM",
                "tracking_id": str(uuid.uuid4()),
                "inventory_count": int(max(0, cr_inv)),
                "delivery_delay_days": cr_delay,
                "is_critical_risk": False
            })
            
        logger.info(f"Executing bulk insert for {len(telemetry_records)} telemetry records...")
        
        # Use bulk_insert_mappings for performance
        session.bulk_insert_mappings(TelemetryModel, telemetry_records)
        session.commit()
        
        end_time = time.time()
        logger.info(f"[RECORDS GENERATED] Successfully inserted {len(telemetry_records)} rows into TimescaleDB.")
        logger.info(f"[EDGE CASES APPLIED] The 4 SKU mathematical profiles (NVIDIA, Intel, AMD, Corsair) were successfully generated.")
        logger.info(f"Total generation time: {end_time - start_time:.2f} seconds.")
        
    except SQLAlchemyError as db_err:
        session.rollback()
        logger.error(f"Database insertion failed. Rolled back transaction. Error: {str(db_err)}")
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"An unexpected error occurred: {str(e)}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    generate_realistic_market()
