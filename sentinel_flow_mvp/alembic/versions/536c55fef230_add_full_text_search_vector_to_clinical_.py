"""Add full text search vector to clinical_knowledge_base

Creates a tsvector column (content_fts) that is automatically updated
whenever the 'content' field changes, plus a GIN index for fast
full-text keyword search.

Beginner Note: PostgreSQL tsvector is a built-in text search format.
The GENERATED ALWAYS AS ... STORED clause means the database maintains
this column automatically — we never write to it directly. Whenever
someone inserts or updates a row, PostgreSQL re-tokenizes the English
text and stores the search tokens.

The GIN (Generalized Inverted Index) is what makes keyword queries
against this column blazing fast — it's the same technology search
engines use.

Revision ID: 536c55fef230
Revises: 133abb3230f0
Create Date: 2026-07-11 15:48:15.404526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = '536c55fef230'
down_revision: Union[str, None] = '133abb3230f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1: Add a tsvector column that PostgreSQL maintains automatically.
    # The 'english' configuration handles stemming (e.g., "running" -> "run")
    # and stop-word removal (e.g., "the", "and" are ignored).
    # GENERATED ALWAYS AS ... STORED means we never set this column manually.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE clinical_knowledge_base
        ADD COLUMN content_fts tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
        """
    )

    # ------------------------------------------------------------------
    # Step 2: Create a GIN index on the tsvector column.
    # GIN (Generalized Inverted Index) maps each search token back to
    # the rows containing it — this is what makes ``@@ plainto_tsquery(...)
    # queries run in milliseconds instead of scanning the entire table.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX ix_clinical_knowledge_base_content_fts_gin
        ON clinical_knowledge_base
        USING GIN (content_fts);
        """
    )


def downgrade() -> None:
    # Remove the GIN index first (faster than dropping the column with the index)
    op.execute(
        "DROP INDEX IF EXISTS ix_clinical_knowledge_base_content_fts_gin;"
    )

    # Remove the generated column
    op.execute(
        "ALTER TABLE clinical_knowledge_base DROP COLUMN IF EXISTS content_fts;"
    )
