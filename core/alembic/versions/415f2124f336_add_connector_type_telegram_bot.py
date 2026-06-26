"""add connector_type telegram_bot

Revision ID: 415f2124f336
Revises: 1f258a9b3fc1
Create Date: 2026-06-26 12:04:10.108732
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '415f2124f336'
down_revision: Union[str, None] = '1f258a9b3fc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; use autocommit.
    # IF NOT EXISTS makes it idempotent against a create_all()-built schema.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE connector_type ADD VALUE IF NOT EXISTS 'telegram_bot'")


def downgrade() -> None:
    # Forward-only (Decisions §16.2): Postgres cannot DROP an enum value without a type rebuild.
    # Downgrade is intentionally a no-op.
    pass
