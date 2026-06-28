"""add audit_action candidate_marked_duplicate

Revision ID: e8a1c25b3f07
Revises: d4e7b2c9f1a3
Create Date: 2026-06-28 00:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8a1c25b3f07'
down_revision: Union[str, None] = 'd4e7b2c9f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; use autocommit.
    # IF NOT EXISTS makes it idempotent against a create_all()-built schema.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'candidate_marked_duplicate'")


def downgrade() -> None:
    # Forward-only (Decisions §16.2): Postgres cannot DROP an enum value without a type rebuild.
    # Downgrade is intentionally a no-op.
    pass
