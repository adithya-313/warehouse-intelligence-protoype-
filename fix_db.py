dockimport os
from sqlalchemy import text
from sentinel_flow_mvp.app.infrastructure.database import engine
from sentinel_flow_mvp.app.infrastructure.models import Base

def fix():
    with engine.begin() as conn:
        try:
            conn.execute(text('ALTER TABLE tenants ADD COLUMN IF NOT EXISTS pincode VARCHAR'))
            print("Added pincode to tenants")
        except Exception as e:
            print("Error altering tenants:", e)
    # NOTE: This is a dev-only convenience script. In real deployments,
    # the database schema is created and updated by Alembic migrations
    # (see the migrations/versions/ folder), NOT by this create_all() call.
    # If you're trying to add or change a table, write a new Alembic
    # migration instead of relying on this script.
    Base.metadata.create_all(bind=engine)
    print("Created missing tables.")

if __name__ == '__main__':
    fix()
