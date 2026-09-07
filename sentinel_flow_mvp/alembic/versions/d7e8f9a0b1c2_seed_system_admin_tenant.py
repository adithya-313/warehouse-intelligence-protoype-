"""seed system_admin tenant for global audit events

The audit_logs table has a foreign key constraint on tenant_id that
references the tenants table.  Supplier records are global (not scoped
to any single pharmacy), so supplier audit events use the synthetic
tenant_id "system_admin".  This tenant must exist in the tenants table
before any supplier audit rows can be inserted.

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-09-07 12:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO tenants (tenant_id, name, is_active, health_risk_enabled) "
            "VALUES ('system_admin', 'System Administrator', true, false) "
            "ON CONFLICT (tenant_id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM tenants WHERE tenant_id = 'system_admin'")
    )
