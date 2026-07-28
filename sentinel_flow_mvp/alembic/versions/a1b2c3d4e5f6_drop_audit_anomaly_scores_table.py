"""drop audit_anomaly_scores table (FraudDetectionModel removed)

Removes the audit_anomaly_scores table that was created to store
Isolation Forest fraud detection results. The FraudDetectionModel
and all its associated code (Celery worker, API endpoints, schemas)
have been removed from the application, so this table is no longer
needed.

This migration is SAFE to run — it only drops a table that no
active code references.

Revision ID: a1b2c3d4e5f6
Revises: e6e434893d67
Create Date: 2026-07-28 18:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e6e434893d67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the audit_anomaly_scores table — it was only used to store
    # Isolation Forest fraud detection results from the now-removed
    # FraudDetectionModel. No active code references this table.
    op.drop_table("audit_anomaly_scores")


def downgrade() -> None:
    # Recreate the table in case we need to roll back.
    # This matches the original DDL from init_db.sql.
    op.create_table(
        "audit_anomaly_scores",
        sa.Column("event_id", sa.String(255), primary_key=True, nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
