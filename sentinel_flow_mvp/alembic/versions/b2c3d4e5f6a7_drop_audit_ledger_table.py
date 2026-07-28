"""drop audit_ledger table (orphaned — FraudDetectionModel removed)

Removes the audit_ledger table that was created to store immutable
financial/inventory events for fraud analysis. The FraudDetectionModel
and all associated code (Celery worker, API endpoints, schemas, ORM
models) have already been removed. This table is now dead schema with
no reads or writes from any active code.

The associated trigger (trg_prevent_audit_tampering) and function
(prevent_audit_tampering) are also dropped since they only existed
to enforce immutability on this table.

This migration is SAFE to run — no active code references this table.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28 18:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the trigger first, then the function, then the table.
    # The trigger depends on the function and the table; the function
    # is standalone but only existed for this table.
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_tampering ON audit_ledger")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_tampering()")
    op.drop_table("audit_ledger")


def downgrade() -> None:
    # Recreate the table, function, trigger, and indexes
    # to allow rollback if needed.
    op.create_table(
        "audit_ledger",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("sku_id", sa.String(255), nullable=True),
        sa.Column("amount_value", sa.Float(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )
    op.create_index(
        "ix_audit_ledger_event_type", "audit_ledger", ["event_type"]
    )
    op.create_index(
        "idx_unique_transaction",
        "audit_ledger",
        [sa.text("(event_metadata->>'transaction_id')"), "timestamp"],
        postgresql_where=sa.text("event_metadata->>'transaction_id' IS NOT NULL"),
        unique=True,
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_tampering()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Audit ledger is immutable. UPDATE and DELETE are prohibited.';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_prevent_audit_tampering
            BEFORE UPDATE OR DELETE ON audit_ledger
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_tampering()
    """)
