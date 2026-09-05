import os
import sys
import argparse
from sqlalchemy import text
from sentinel_flow_mvp.app.infrastructure.database import engine
from sentinel_flow_mvp.app.infrastructure.models import Base

# This guard prevents accidental execution against production databases.
# This script modifies the schema directly (bypassing Alembic) and should
# only be run against local dev databases by someone who knows the risks.
def check_safety():
    parser = argparse.ArgumentParser(
        description="Dev-only script: adds missing columns and creates tables. "
                    "This bypasses Alembic migrations and should only run against "
                    "a local dev database."
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Required flag to confirm you understand this modifies the database schema."
    )
    args = parser.parse_args()

    if not args.i_know_what_im_doing:
        print("WARNING: This script modifies database schema directly (bypassing Alembic).")
        print("It should ONLY be run against a local dev database.")
        print("To proceed, re-run with: python fix_db.py --i-know-what-im-doing")
        sys.exit(1)

    # Check DATABASE_URL doesn't look like production
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        # Extract hostname from DATABASE_URL (format: postgresql://user:pass@host:port/db)
        try:
            # Simple parsing: split on @ to get host part
            host_part = db_url.split("@")[-1].split("/")[0]
            hostname = host_part.split(":")[0]
            # Allow only local/dev hostnames
            allowed_hosts = ["localhost", "127.0.0.1", "timescaledb"]
            if hostname not in allowed_hosts:
                print(f"ERROR: DATABASE_URL hostname '{hostname}' is not a local/dev host.")
                print(f"Allowed hosts: {allowed_hosts}")
                print("This script should only run against local dev databases.")
                sys.exit(1)
        except Exception:
            pass  # If we can't parse, let it proceed (user may know better)

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
    check_safety()
    fix()
