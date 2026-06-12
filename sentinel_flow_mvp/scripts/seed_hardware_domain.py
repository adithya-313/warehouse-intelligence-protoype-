"""Database Purge and Seed for Hardware Domain.

This script cleans the database and populates it with realistic time-series
inventory data for a Computer Hardware Distribution enterprise.
"""
import sys
import os
import random
import uuid
import json
import numpy as np
from datetime import datetime, timedelta, timezone

# Add the project root to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.core.config import get_application_settings

def seed_database():
    print("Starting database purge and hardware domain seed...")
    settings = get_application_settings()
    engine = create_engine(settings.database_url)
    
    with engine.connect() as conn:
        print("Ensuring columns exist...")
        conn.execute(text("ALTER TABLE inventory_telemetry ADD COLUMN IF NOT EXISTS sku_id VARCHAR(255);"))
        conn.execute(text("ALTER TABLE inventory_telemetry ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(255);"))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS route_telemetry (
                recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                route_id VARCHAR(255) NOT NULL,
                route_distance_km DOUBLE PRECISION,
                vehicle_efficiency DOUBLE PRECISION
            );
        """))
        conn.execute(text("SELECT create_hypertable('route_telemetry', 'recorded_at', if_not_exists => TRUE);"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asset_telemetry (
                recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                asset_id VARCHAR(255) NOT NULL,
                equipment_age_days INTEGER,
                vibration_index DOUBLE PRECISION
            );
        """))
        conn.execute(text("SELECT create_hypertable('asset_telemetry', 'recorded_at', if_not_exists => TRUE);"))
        
        conn.commit()

        print("Purging existing telemetry and supplier data...")
        conn.execute(text("TRUNCATE TABLE route_telemetry CASCADE;"))
        conn.execute(text("TRUNCATE TABLE asset_telemetry CASCADE;"))
        conn.execute(text("TRUNCATE TABLE inventory_telemetry CASCADE;"))
        conn.execute(text("TRUNCATE TABLE suppliers CASCADE;"))
        
        print("Inserting Hardware Suppliers...")
        suppliers = [
            {"id": "NVIDIA Corporation", "system": "SAP", "vertical": "HARDWARE"},
            {"id": "ASUS Global", "system": "SAP", "vertical": "HARDWARE"},
            {"id": "Intel Corp", "system": "ORACLE", "vertical": "HARDWARE"}
        ]
        for sup in suppliers:
            conn.execute(text(
                "INSERT INTO suppliers (supplier_id, system_origin, industry_vertical, industry_specific_metadata) "
                "VALUES (:id, :sys, :vert, :meta)"
            ), {"id": sup["id"], "sys": sup["system"], "vert": sup["vertical"], "meta": json.dumps({"tier": "premium"})})
        
        print("Inserting 180 days of continuous inventory telemetry for SKUs...")
        skus = [
            ("SKU-NV-5090", "NVIDIA Corporation", 100),
            ("SKU-NV-4070S", "NVIDIA Corporation", 500),
            ("SKU-AS-Z890", "ASUS Global", 200),
            ("SKU-IN-285K", "Intel Corp", 300)
        ]
        
        now = datetime.now(timezone.utc)
        for sku_id, supplier_id, base_inventory in skus:
            tenant_id = "tenant_alpha" if "NV" in sku_id else "tenant_beta"
            spike_day = random.randint(100, 140) if sku_id == "SKU-NV-5090" else None
            for day in range(180, -1, -1):
                timestamp = now - timedelta(days=day)
                
                # Base volume + Seasonality + Gaussian Noise
                seasonality = np.sin(day / 7.0 * 2 * np.pi) * (base_inventory * 0.1)
                noise = np.random.normal(loc=0, scale=base_inventory * 0.05)
                current_inv = base_inventory + seasonality + noise
                
                # The Hype Spike for SKU-NV-5090
                if spike_day and day <= spike_day:
                    decay_days = spike_day - day
                    current_inv += 400 * np.exp(-decay_days / 10.0)
                        
                current_inv = max(0, int(current_inv))
                conn.execute(text(
                    "INSERT INTO inventory_telemetry (recorded_at, supplier_id, tracking_id, sku_id, tenant_id, inventory_count, delivery_delay_days) "
                    "VALUES (:rec, :sup, :trk, :sku, :tenant, :inv, :delay)"
                ), {
                    "rec": timestamp,
                    "sup": supplier_id,
                    "trk": str(uuid.uuid4()),
                    "sku": sku_id,
                    "tenant": tenant_id,
                    "inv": current_inv,
                    "delay": random.randint(3, 14)
                })
        
        print("Inserting mock Route telemetry for the new routes...")
        routes = ['Taiwan -> Kochi Port', 'Hong Kong -> Bengaluru Air Cargo']
        for route_id in routes:
            conn.execute(text(
                "INSERT INTO route_telemetry (recorded_at, route_id, route_distance_km, vehicle_efficiency) "
                "VALUES (:rec, :route, :dist, :eff)"
            ), {
                "rec": now,
                "route": route_id,
                "dist": 5000.0 if "Taiwan" in route_id else 4000.0,
                "eff": random.uniform(0.7, 0.95)
            })

        print("Inserting mock Asset telemetry...")
        assets = ['Forklift #4', 'Conveyor Belt B', 'HVAC System 1']
        for asset_id in assets:
            conn.execute(text(
                "INSERT INTO asset_telemetry (recorded_at, asset_id, equipment_age_days, vibration_index) "
                "VALUES (:rec, :asset, :age, :vib)"
            ), {
                "rec": now,
                "asset": asset_id,
                "age": random.randint(100, 1000),
                "vib": random.uniform(0.1, 0.5)
            })
        
        print("Inserting mock LoRA adapter registry...")
        conn.execute(text("TRUNCATE TABLE lora_adapter_registry CASCADE;"))
        conn.execute(text(
            "INSERT INTO lora_adapter_registry (id, module_name, supplier_id, base_model_version, adapter_weights_path, status, created_at) "
            "VALUES (:id, :mod, :sup, :base, :path, :status, :created)"
        ), {
            "id": str(uuid.uuid4()),
            "mod": "demand_forecast",
            "sup": "NVIDIA Corporation",
            "base": "chronos_base_v1",
            "path": "/dummy/path/to/adapter",
            "status": "ACTIVE",
            "created": now
        })
        
        conn.commit()
    print("Database purge and hardware domain seed completed successfully!")

if __name__ == "__main__":
    seed_database()
