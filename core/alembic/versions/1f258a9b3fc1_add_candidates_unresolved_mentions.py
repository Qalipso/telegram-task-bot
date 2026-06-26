"""add candidates.unresolved_mentions

Revision ID: 1f258a9b3fc1
Revises: 2fe660361238
Create Date: 2026-06-26 10:04:01.033118
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '1f258a9b3fc1'
down_revision: Union[str, None] = '2fe660361238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'candidates',
        sa.Column('unresolved_mentions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('candidates', 'unresolved_mentions')
