"""Phase 1: Multi-Tenant Isolation + Clinical Master Index + Regulatory Diff Ledger

Beginner Note:
    This migration does THREE things in a specific order:

    1. TENANT ISOLATION — We add a ``tenant_id`` column to four tables
       that currently have NO tenant awareness. Each gets a foreign key
       constraint pointing to ``tenants.tenant_id`` and a composite
       performance index on ``(tenant_id, <primary_key>)`` so that
       multi-tenant queries (WHERE tenant_id = ?) are fast.

    2. CLINICAL MASTER INDEX — We add four columns to the ``medications``
       table that store pregnancy safety categories, pediatric age
       thresholds, drug interaction matrices, and a curator approval
       flag. These are the structured fields that power the clinical
       safety checking system.

    3. REGULATORY DIFF LEDGER — We create a brand new table
       ``regulatory_diff_log`` that records every change the mock
       government scraper detects in the CDSCO / FDA drug master list.
       This table is append-only (immutable) so the audit trail is
       never erased.

    Why manual?
        Alembic's ``--autogenerate`` flag compares your ORM models against
        the LIVE database. Since this development environment cannot reach
        the ``timescaledb`` PostgreSQL host, we write this migration by hand
        using the exact column definitions from our ORM models.

Revision ID: f7e8d9c0b1a2
Revises: 31763ac860b3
Create Date: 2026-07-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "f7e8d9c0b1a2"
down_revision: Union[str, None] = "31763ac860b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the Phase 1 changes to the database schema.

    Beginner Note:
        The upgrade() function is what runs when you type
        ``alembic upgrade head``. Every operation is structured so that
        if something fails halfway through, the transaction is rolled
        back and the database is left unchanged (Alembic wraps each
        migration in a database transaction automatically).
    """

    # ==================================================================
    # PART A: TENANT ISOLATION
    # ==================================================================
    # We add ``tenant_id`` to four tables. Each column:
    #   - Uses the same type as ``tenants.tenant_id`` (String)
    #   - Has a NOT NULL constraint (every row must belong to a tenant)
    #   - Has a FOREIGN KEY pointing to ``tenants(tenant_id)``
    #   - Has a regular INDEX for single-column lookups
    #
    # We also create a COMPOSITE INDEX on ``(tenant_id, <primary_key>)``
    # for each table to speed up the most common multi-tenant query
    # pattern: "give me all rows for tenant X, ordered by ID."
    #
    # Order: We add columns to the SMALLEST tables first (fewest rows
    # to scan) to keep the migration fast.
    # ==================================================================

    # Step 1: medication_batches — the core inventory tracking table.
    # This is the largest table of the four, so we process it last.
    # Actually, for readability, we process in alphabetical order.

    # --- 1a. Add tenant_id to medication_batches ---
    op.add_column(
        "medication_batches",
        sa.Column(
            "tenant_id",
            sa.String(),          # Matches tenants.tenant_id data type
            sa.ForeignKey(
                "tenants.tenant_id",
                name="fk_medication_batches_tenant_id",
            ),
            nullable=False,       # Every batch must belong to a tenant
            index=True,           # Single-column index for fast filtering
        ),
    )

    # Create the composite index (tenant_id, batch_id) for multi-tenant lookups
    op.create_index(
        "idx_tenant_batch",
        "medication_batches",
        ["tenant_id", "batch_id"],
    )

    # --- 1b. Add tenant_id to purchase_orders ---
    op.add_column(
        "purchase_orders",
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey(
                "tenants.tenant_id",
                name="fk_purchase_orders_tenant_id",
            ),
            nullable=False,
            index=True,
        ),
    )

    # Create the composite index (tenant_id, po_id)
    op.create_index(
        "idx_tenant_po",
        "purchase_orders",
        ["tenant_id", "po_id"],
    )

    # --- 1c. Add tenant_id to sale_receipts ---
    op.add_column(
        "sale_receipts",
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey(
                "tenants.tenant_id",
                name="fk_sale_receipts_tenant_id",
            ),
            nullable=False,
            index=True,
        ),
    )

    # Create the composite index (tenant_id, id)
    op.create_index(
        "idx_tenant_receipt",
        "sale_receipts",
        ["tenant_id", "id"],
    )

    # --- 1d. Add tenant_id to sale_line_items ---
    op.add_column(
        "sale_line_items",
        sa.Column(
            "tenant_id",
            sa.String(),
            sa.ForeignKey(
                "tenants.tenant_id",
                name="fk_sale_line_items_tenant_id",
            ),
            nullable=False,
            index=True,
        ),
    )

    # Create the composite index (tenant_id, id)
    op.create_index(
        "idx_tenant_line_item",
        "sale_line_items",
        ["tenant_id", "id"],
    )

    # ==================================================================
    # PART B: CLINICAL MASTER INDEX FIELDS (medications table)
    # ==================================================================
    # We add four columns to the ``medications`` table. These are all
    # global-layer fields (not tenant-specific) because the medication
    # catalogue is shared across all tenants. A drug's pregnancy safety
    # category does not change from one pharmacy to another.
    #
    # All four columns are added in a single batch of add_column calls.
    # ==================================================================

    # Step 2a: pregnancy_category — FDA/CDSCO pregnancy safety rating
    # Valid values: 'A', 'B', 'C', 'D', 'X'
    # Nullable because not all drugs have a rating yet.
    op.add_column(
        "medications",
        sa.Column(
            "pregnancy_category",
            sa.String(2),         # Exactly 1 or 2 characters ('A' through 'X')
            nullable=True,        # Not all drugs are classified
        ),
    )

    # Step 2b: pediatric_age_threshold_months — minimum patient age
    # Nullable because many drugs have no age restriction.
    op.add_column(
        "medications",
        sa.Column(
            "pediatric_age_threshold_months",
            sa.Integer(),
            nullable=True,
        ),
    )

    # Step 2c: interaction_matrix — drug-to-drug contraindication map
    # Stored as JSONB so we can query individual keys with the ``?``
    # operator (e.g., "does this drug interact with nitrates?").
    op.add_column(
        "medications",
        sa.Column(
            "interaction_matrix",
            JSONB(),              # PostgreSQL native JSON binary format
            nullable=True,
        ),
    )

    # Step 2d: is_approved_by_curator — human review gate
    # Default is FALSE so that new or modified entries from the
    # government scraper start in the "pending review" state.
    op.add_column(
        "medications",
        sa.Column(
            "is_approved_by_curator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ==================================================================
    # PART C: REGULATORY DIFF LEDGER (new table)
    # ==================================================================
    # We create the ``regulatory_diff_log`` table from scratch.
    # This is an append-only audit table. The mock government scraper
    # inserts a new row every time it detects a regulatory change.
    #
    # Constraints:
    #   - ``product_id`` is a foreign key to ``medications.sku_id``
    #   - ``id`` is an auto-incrementing BIGINT primary key
    #   - All columns except ``curator_id`` are NOT NULL
    # ==================================================================

    op.create_table(
        "regulatory_diff_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "medications.sku_id",
                name="fk_regulatory_diff_log_product_id",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("old_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("source_gov_url", sa.Text(), nullable=False),
        sa.Column("curator_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_regulatory_diff_log"),
    )


def downgrade() -> None:
    """Reverse the Phase 1 changes.

    Beginner Note:
        The downgrade() function is what runs when you type
        ``alembic downgrade -1``. We reverse every change we made
        in the upgrade() function, in reverse order. This way, the
        database returns to exactly the state it was in before
        this migration was applied.

        IMPORTANT SAFETY WARNING:
        Running ``downgrade`` will PERMANENTLY DELETE all data in
        the ``regulatory_diff_log`` table and DROP the four new
        columns from the tenant-isolated tables. Any data stored
        in those columns will be lost.
    """

    # ==================================================================
    # Reverse PART C: Drop the regulatory_diff_log table
    # ==================================================================
    op.drop_table("regulatory_diff_log")

    # ==================================================================
    # Reverse PART B: Remove the clinical master index fields
    # ==================================================================
    op.drop_column("medications", "is_approved_by_curator")
    op.drop_column("medications", "interaction_matrix")
    op.drop_column("medications", "pediatric_age_threshold_months")
    op.drop_column("medications", "pregnancy_category")

    # ==================================================================
    # Reverse PART A: Remove tenant isolation columns + indexes
    # ==================================================================

    # Drop composite indexes first (PostgreSQL requires this before
    # dropping the columns that the index references).
    op.drop_index("idx_tenant_line_item", table_name="sale_line_items")
    op.drop_index("idx_tenant_receipt", table_name="sale_receipts")
    op.drop_index("idx_tenant_po", table_name="purchase_orders")
    op.drop_index("idx_tenant_batch", table_name="medication_batches")

    # Now drop the columns. PostgreSQL automatically drops the
    # foreign key constraints when the column is dropped.
    op.drop_column("sale_line_items", "tenant_id")
    op.drop_column("sale_receipts", "tenant_id")
    op.drop_column("purchase_orders", "tenant_id")
    op.drop_column("medication_batches", "tenant_id")
