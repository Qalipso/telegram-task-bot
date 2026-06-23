"""Stage 2 — the Alembic migration runs cleanly and reverses (real Postgres).

Uses a dedicated migrate-test database so it never collides with the ORM test DB.
"""
import os
import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO = pathlib.Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(REPO / "core" / "alembic.ini")
MIGRATE_URL = os.environ.get(
    "MIGRATE_TEST_DATABASE_URL", "postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip_migrate_test"
)

EXPECTED_TABLES = {
    "users", "chats", "connector_accounts", "messages", "message_attachments",
    "sync_states", "sync_runs", "assignees", "candidates", "candidate_messages",
    "candidate_assignees", "candidate_labels", "labels", "work_items",
    "work_item_assignees", "work_item_labels", "ai_runs", "evaluation_cases", "audit_logs",
}


def _reset(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")


def test_migration_upgrade_creates_all_tables_then_downgrades(monkeypatch):
    engine = create_engine(MIGRATE_URL, future=True)
    try:
        _reset(engine)
        monkeypatch.setenv("ALEMBIC_DATABASE_URL", MIGRATE_URL)
        cfg = Config(ALEMBIC_INI)

        command.upgrade(cfg, "head")
        tables = set(inspect(engine).get_table_names())
        missing = EXPECTED_TABLES - tables
        assert not missing, f"migration did not create: {missing}"
        assert len(EXPECTED_TABLES) == 19

        command.downgrade(cfg, "base")
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set(), f"downgrade left tables: {remaining}"
    finally:
        _reset(engine)
        engine.dispose()
