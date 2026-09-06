"""create audit_logs table

Adds the audit_logs table to provide an immutable audit trail for all
mutating actions in the system. Every CREATE, UPDATE, and DELETE on
business-critical tables (purchase orders, medication batches, etc.)
should write a row here before committing, so administrators can later
review who did what, when, and what the data looked like before and after.

The table stores JSON snapshots of old_value and new_value so the full
history of each change is preserved without requiring complex database
triggers.

Revision ID: c5d6e7f8a9b0
Revises: f4b903e0ae0f
Create Date: 2026-09-05 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "f4b903e0ae0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey("tenants.tenant_id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
    )
    # Indexes matching the model definition — speed up common audit queries:
    # "show me all events for tenant X", "show me all changes to entity Y",
    # "show me everything that happened recently".
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
