import os
import sys
import datetime
from sqlalchemy import create_engine

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.database import engine, SessionLocal
from app.infrastructure.models import Base as ModelsBase
from app.infrastructure.db.models import Base as DBModelsBase
from app.infrastructure.db.models import AssetTelemetryModel, RouteTelemetryModel

def setup_context_db():
    print("Creating new tables...")
    # NOTE: This is a dev-only convenience script. In real deployments,
    # the database schema is created and updated by Alembic migrations
    # (see the migrations/versions/ folder), NOT by this create_all() call.
    # If you're trying to add or change a table, write a new Alembic
    # migration instead of relying on this script.
    # This will create any missing tables defined in the metadata
    DBModelsBase.metadata.create_all(bind=engine)
    ModelsBase.metadata.create_all(bind=engine)
    print("Tables created/verified.")

    print("Inserting mock data...")
    session = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Assets
        assets = [
            ("Forklift #4", 1200, 0.8),
            ("Conveyor Belt B", 400, 0.2),
            ("HVAC System 1", 3000, 0.95),
        ]
        for aid, age, vib in assets:
            record = AssetTelemetryModel(
                recorded_at=now,
                asset_id=aid,
                equipment_age_days=age,
                vibration_index=vib
            )
            session.merge(record)

        # Routes
        routes = [
            ("Mumbai -> Kochi", 1350.0, 8.5),
            ("Delhi -> Chennai", 2200.0, 7.2),
            ("Bangalore -> Pune", 840.0, 9.1),
        ]
        for rid, dist, eff in routes:
            record = RouteTelemetryModel(
                recorded_at=now,
                route_id=rid,
                route_distance_km=dist,
                vehicle_efficiency=eff
            )
            session.merge(record)

        session.commit()
        print("Mock data inserted successfully.")
    except Exception as e:
        session.rollback()
        print(f"Failed to insert mock data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    setup_context_db()
