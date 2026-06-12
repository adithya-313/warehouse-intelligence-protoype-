"""Mathematical Data Synthesis Engine.

Generates highly correlated, mathematically realistic supply chain history for 20 suppliers
over 365 days. Inserts using bulk operations for performance.
"""

import time
import logging
from datetime import datetime, timedelta, timezone
import uuid
import sys
import os

import numpy as np
import scipy.stats as stats

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure app is in path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import SupplierModel, TelemetryModel
from sqlalchemy.exc import SQLAlchemyError


def generate_data():
    session = SessionLocal()
    
    try:
        start_time = time.time()
        
        # Step 3.2: Generate Supplier Entities
        logger.info("Generating Supplier Entities...")
        num_suppliers = 20
        suppliers = []
        reliability_profiles = {}
        
        for i in range(1, num_suppliers + 1):
            supplier_id = f"Supplier_{i:02d}"
            # Reliability profiles: scale from 0.5 (highly reliable) to 3.0 (erratic)
            reliability = np.random.uniform(0.5, 3.0)
            reliability_profiles[supplier_id] = reliability
            
            suppliers.append({
                "supplier_id": supplier_id,
                "system_origin": "SYNTHETIC_GEN",
                "industry_vertical": "MIXED",
                "industry_specific_metadata": {"reliability_score": reliability},
                "created_at": datetime.now(timezone.utc)
            })
        
        # Insert suppliers using bulk insert
        session.bulk_insert_mappings(SupplierModel, suppliers)
        session.commit()
        
        # Step 3.3: Generate Time-Series Telemetry
        logger.info("Generating Telemetry Data...")
        days = 365
        base_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        telemetry_records = []
        
        for supplier_id in reliability_profiles:
            profile = reliability_profiles[supplier_id]
            
            # Base Demand setup
            base_demand = np.random.uniform(100, 1000)
            amplitude = base_demand * np.random.uniform(0.1, 0.4) # 10% to 40% seasonality
            
            # AR(1) noise setup
            noise = 0
            rho = 0.7 # Autoregressive coefficient
            
            max_capacity = base_demand * 3
            unit_cost = np.random.uniform(10, 50)
            
            for t in range(days):
                record_date = base_date + timedelta(days=t)
                
                # AR(1) noise
                noise = rho * noise + np.random.normal(0, base_demand * 0.1)
                
                # Demand(t) = Base + Amp * sin(2*pi * t/365) + Noise
                # This creates realistic seasonal peaks across a year
                demand = max(0, base_demand + amplitude * np.sin(2 * np.pi * t / 365) + noise)
                
                # Inventory Count: Inversely correlated to demand
                # If demand spikes, inventory drops. Bound between 0 and Max Capacity
                inventory_count = int(max(0, min(max_capacity, max_capacity - demand * np.random.uniform(0.8, 1.2))))
                
                # Delivery Delay: Gamma distribution modified by reliability
                # Most delays are 0-1 days, but with a long right tail
                # shape=2.0, scale=1.0 * profile creates the long tail
                delay = stats.gamma.rvs(a=2.0, scale=1.0 * profile)
                delivery_delay_days = int(np.round(delay))
                
                # Invoice Amount (Computed but not in DB schema yet): Unit Cost * Demand + baseline inflation drift
                # Inflation drift adds a slight upward trend over 365 days
                inflation_factor = 1.0 + (t / 365) * 0.05
                invoice_amount = demand * unit_cost * inflation_factor
                
                telemetry_records.append({
                    "recorded_at": record_date,
                    "supplier_id": supplier_id,
                    "tracking_id": str(uuid.uuid4()),
                    "inventory_count": inventory_count,
                    "delivery_delay_days": delivery_delay_days,
                    "predicted_stockout_probability": None,  # Will be populated by ML later
                    "is_critical_risk": False
                })

        # Step 3.4: Inject Fraud / Anomalies
        logger.info("Injecting Fraud / Anomalies...")
        for i in range(len(telemetry_records)):
            # 0.5% probability of being a Fraud Event
            if np.random.rand() < 0.005:
                anomaly_type = np.random.choice(["impossible_inventory", "extreme_delay"])
                if anomaly_type == "impossible_inventory":
                    # Inject impossible inventory count (massive physically impossible value)
                    telemetry_records[i]["inventory_count"] = 9999999
                elif anomaly_type == "extreme_delay":
                    # Massive delay anomaly
                    telemetry_records[i]["delivery_delay_days"] += 50
                    
        # Step 3.5: Execute Bulk Inserts
        logger.info(f"Executing bulk insert for {len(telemetry_records)} telemetry records...")
        
        # Use bulk_insert_mappings for performance instead of row-by-row .add()
        session.bulk_insert_mappings(TelemetryModel, telemetry_records)
        session.commit()
        
        end_time = time.time()
        logger.info(f"Successfully generated {num_suppliers} suppliers and {len(telemetry_records)} telemetry records.")
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
    generate_data()
