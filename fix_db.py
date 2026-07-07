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
    Base.metadata.create_all(bind=engine)
    print("Created missing tables.")

if __name__ == '__main__':
    fix()
