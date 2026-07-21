"""add audit_action work_item_edited

Revision ID: d4e7b2c9f1a3
Revises: 415f2124f336
Create Date: 2026-06-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e7b2c9f1a3'
down_revision: Union[str, None] = '415f2124f336'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; use autocommit.
    # IF NOT EXISTS makes it idempotent against a create_all()-built schema.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'work_item_edited'")


def downgrade() -> None:
    # Forward-only (Decisions §16.2): Postgres cannot DROP an enum value without a type rebuild.
    # Downgrade is intentionally a no-op.
    pass
