"""feat(notifications): add nullable health_risk_score_id deep-link column

Revision ID: e5d6c7b8a9f0
Revises: c6c10b7f975e
Create Date: 2026-08-03 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5d6c7b8a9f0'
down_revision: Union[str, None] = 'c6c10b7f975e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable because only health-risk-triggered notifications point at a
    # score row; existing rows (and other alert types) legitimately have none.
    op.add_column('notifications', sa.Column('health_risk_score_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('notifications', 'health_risk_score_id')
