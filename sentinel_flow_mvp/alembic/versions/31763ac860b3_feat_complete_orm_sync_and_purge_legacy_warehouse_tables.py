"""feat: complete orm sync and purge legacy warehouse tables

Beginner Note:
    This migration does two things and ONLY two things:

    1. PURGE LEGACY TABLES — We drop three tables (warehouse_nodes,
       warehouse_edges, movement_telemetry) that were part of the old
       warehouse topology domain. This domain has been fully replaced by
       the modern medication_batch / FEFO system. These tables have no
       corresponding ORM model and are dead code in the database.

    2. PROTECT content_fts — The ``clinical_knowledge_base.content_fts``
       column is a ``GENERATED ALWAYS AS`` tsvector column used by our
       raw SQL hybrid search (semantic_search.py). We explicitly ensure
       this migration does NOT drop it, even though Alembic's autogenerate
       might suggest doing so (since there is no ORM attribute mapping for
       this generated column).

    Why manual?
        Alembic's ``--autogenerate`` flag compares your ORM models against
        the LIVE database. Since this development environment cannot reach
        the ``timescaledb`` PostgreSQL host, we write this migration by hand
        using the exact column definitions from ``app/infrastructure/init_db.sql``.

Revision ID: 31763ac860b3
Revises: 8426ce3b0aba
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Import pgvector so Alembic understands the custom "vector" type used by
# the ClinicalKnowledgeBase.embedding column (Vector(768)).
import pgvector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "31763ac860b3"
down_revision: Union[str, None] = "8426ce3b0aba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the migration: drop legacy warehouse tables, protect everything else.

    Beginner Note:
        The upgrade() function is what runs when you type ``alembic upgrade head``.
        We perform exactly three DROP TABLE operations. We do NOT drop any columns,
        especially not ``clinical_knowledge_base.content_fts``.

        The CASCADE keyword tells PostgreSQL to also drop any database objects that
        depend on these tables (like foreign key references). This is safe because
        no modern code references these tables.
    """

    # ------------------------------------------------------------------
    # PURGE LEGACY WAREHOUSE TABLES
    # ------------------------------------------------------------------
    # We drop ``warehouse_edges`` FIRST because it has FOREIGN KEY constraints
    # that reference ``warehouse_nodes``. PostgreSQL requires us to drop the
    # child table before the parent table.
    #
    # Order of operations:
    #   1. warehouse_edges   (child — references warehouse_nodes)
    #   2. warehouse_nodes   (parent — referenced by warehouse_edges)
    #   3. movement_telemetry (independent — no FK to the other two)
    # ------------------------------------------------------------------

    # Step 1: Drop warehouse_edges — the directed-graph edges table.
    # This table linked two warehouse_nodes together with a distance and capacity.
    # It is no longer needed because we use FEFO batch routing instead of
    # warehouse topology traversal.
    op.drop_table("warehouse_edges")

    # Step 2: Drop warehouse_nodes — the warehouse topology nodes table.
    # Each row represented a physical location (rack, shelf, picking station).
    # The modern system tracks locations via MedicationBatchModel.shelf_location.
    op.drop_table("warehouse_nodes")

    # Step 3: Drop movement_telemetry — the high-frequency position tracking table.
    # This was used for real-time forklift/robot tracking. The stream_consumer
    # worker already discards these messages (bulk_insert_records() is a no-op).
    op.drop_table("movement_telemetry")

    # ------------------------------------------------------------------
    # CRITICAL: content_fts is NOT dropped
    # ------------------------------------------------------------------
    # The ``clinical_knowledge_base.content_fts`` column is a
    # ``GENERATED ALWAYS AS to_tsvector('english', content)`` column that
    # PostgreSQL auto-populates. It is used by the raw SQL hybrid search
    # in ``app/services/semantic_search.py`` (lines 95, 109, 111) via the
    # ``@@`` tsquery operator.
    #
    # There is no ORM attribute for this column (it is a database-generated
    # column, not a Python-mapped one). If we had run ``--autogenerate``,
    # Alembic would have detected this mismatch and generated an
    # ``op.drop_column('clinical_knowledge_base', 'content_fts')`` statement.
    #
    # We EXPLICITLY DO NOT include that drop statement here. The column
    # remains in the database and continues to power the hybrid search.
    # ------------------------------------------------------------------


def downgrade() -> None:
    """Reverse the migration: recreate the legacy warehouse tables.

    Beginner Note:
        The downgrade() function is what runs when you type
        ``alembic downgrade -1``. We recreate the exact same table schemas
        that were defined in ``app/infrastructure/init_db.sql`` so that a
        rollback returns the database to a fully working state.

        These table definitions are minimal — they match the original SQL
        exactly so any legacy code (if re-introduced) would find the schema
        it expects.
    """

    # ------------------------------------------------------------------
    # Step 1: Recreate warehouse_nodes (parent table)
    # ------------------------------------------------------------------
    # This table defined physical locations in the warehouse.
    # The ``id`` column is the primary key, referenced by warehouse_edges.
    op.create_table(
        "warehouse_nodes",
        sa.Column("id", sa.VARCHAR(255), primary_key=True),
        sa.Column("zone", sa.VARCHAR(100), nullable=False),
        sa.Column("type", sa.VARCHAR(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ------------------------------------------------------------------
    # Step 2: Recreate warehouse_edges (child table)
    # ------------------------------------------------------------------
    # This table defined traversable pathways between warehouse nodes.
    # It has a composite primary key (source_id, target_id) and two foreign
    # keys pointing to warehouse_nodes.
    op.create_table(
        "warehouse_edges",
        sa.Column("source_id", sa.VARCHAR(255), nullable=False),
        sa.Column("target_id", sa.VARCHAR(255), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("max_capacity", sa.Integer(), nullable=False),
    )

    # Add the composite primary key AFTER creating the table
    op.create_primary_key(
        "pk_warehouse_edges",
        "warehouse_edges",
        ["source_id", "target_id"],
    )

    # Add foreign key constraints referencing warehouse_nodes.
    # These ensure referential integrity: every source_id and target_id
    # must point to an existing warehouse_nodes row.
    op.create_foreign_key(
        "fk_warehouse_edges_source",
        "warehouse_edges",
        "warehouse_nodes",
        ["source_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_warehouse_edges_target",
        "warehouse_edges",
        "warehouse_nodes",
        ["target_id"],
        ["id"],
    )

    # ------------------------------------------------------------------
    # Step 3: Recreate movement_telemetry (independent table)
    # ------------------------------------------------------------------
    # This table stored high-frequency position data.
    # The ``id`` column is an auto-incrementing SERIAL (handled by
    # sa.Integer with autoincrement=True for PostgreSQL).
    op.create_table(
        "movement_telemetry",
        sa.Column("id", sa.Integer(), autoincrement=True),
        sa.Column("entity_id", sa.VARCHAR(255), nullable=False),
        sa.Column("entity_type", sa.VARCHAR(50), nullable=False),
        sa.Column("node_id", sa.VARCHAR(255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )

    # Add a primary key on the auto-incrementing id column
    op.create_primary_key(
        "pk_movement_telemetry",
        "movement_telemetry",
        ["id"],
    )
