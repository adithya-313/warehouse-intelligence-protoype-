"""Initial schema state from SQL genesis

This is a STAMPING migration only. All tables were created at runtime
via Base.metadata.create_all() and the raw SQL init_db.sql script.

We do NOT attempt to drop legacy tables (warehouse_nodes, warehouse_edges,
movement_telemetry) because the production database is already populated.

Revision ID: 133abb3230f0
Revises: 
Create Date: 2026-07-11 15:40:16.164183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '133abb3230f0'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    This migration is intentionally empty.
    The database schema was bootstrapped via:
      1. app/infrastructure/init_db.sql (legacy tables)
      2. Base.metadata.create_all() at application startup (ORM tables)

    No DDL changes are needed — we are simply stamping the Alembic
    version table so future migrations have a known starting point.
    """
    pass


def downgrade() -> None:
    """
    Downgrade is intentionally empty.
    Rolling back to a pre-Alembic state is not supported.
    """
    pass
