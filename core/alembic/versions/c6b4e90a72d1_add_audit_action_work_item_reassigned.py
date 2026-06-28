"""add audit_action work_item_reassigned

Revision ID: c6b4e90a72d1
Revises: e8a1c25b3f07
Create Date: 2026-06-28 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6b4e90a72d1'
down_revision: Union[str, None] = 'e8a1c25b3f07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; use autocommit.
    # IF NOT EXISTS makes it idempotent against a create_all()-built schema.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'work_item_reassigned'")


def downgrade() -> None:
    # Forward-only (Decisions §16.2): Postgres cannot DROP an enum value without a type rebuild.
    # Downgrade is intentionally a no-op.
    pass
