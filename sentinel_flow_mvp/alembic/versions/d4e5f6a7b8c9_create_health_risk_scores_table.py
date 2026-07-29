"""create health_risk_scores table

Creates the physical database table for HealthRiskScoreModel. This table
stores one computed risk score per disease, per pincode, per computation
cycle, and is written by the ingestion_service pipeline.

The unique constraint on (pincode, disease_category, computed_at) prevents
accidental double-insertions from duplicate Celery task invocations.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-30 03:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the health_risk_scores table with all columns matching
    # the HealthRiskScoreModel definition in db_models.py.
    op.create_table(
        "health_risk_scores",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("pincode", sa.String(), index=True, nullable=False),
        sa.Column("disease_category", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contributing_factors", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "pincode", "disease_category", "computed_at",
            name="uix_health_risk_score_pincode_disease_time",
        ),
    )


def downgrade() -> None:
    # Drop the table cleanly. Any computed scores are lost on downgrade;
    # this is acceptable because the health_risk module has no production
    # data yet (it is behind a feature flag that defaults to False).
    op.drop_table("health_risk_scores")
