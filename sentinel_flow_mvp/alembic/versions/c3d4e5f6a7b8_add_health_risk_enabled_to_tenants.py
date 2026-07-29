"""add health_risk_enabled column to tenants table

Adds a per-pharmacy feature flag for the health_risk scoring module.
The column defaults to False (opt-in) so no existing tenant is affected
until explicitly enabled.

This column is paired with the global HEALTH_RISK_ENABLED setting in
app/core/config.py — both must be True for scoring to run. The two-gate
system allows safe pilot rollout: the tenant flag enables individual
pharmacies, the global flag acts as an emergency stop for all.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-29 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add a non-nullable boolean column with a server default of FALSE so
    # existing rows are automatically set to False (no health_risk scoring
    # for any tenant until the pharmacy-level flag is explicitly enabled).
    op.add_column(
        "tenants",
        sa.Column(
            "health_risk_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Per-pharmacy opt-in for the health_risk scoring module.",
        ),
    )


def downgrade() -> None:
    # Remove the column cleanly. Any per-pharmacy settings are lost on
    # downgrade; this is acceptable because the feature has no production
    # data yet (the module is not wired to any live code path).
    op.drop_column("tenants", "health_risk_enabled")
