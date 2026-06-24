#!/usr/bin/env python3
"""Entrypoint for API service: ensure the DB schema exists, then start uvicorn.

The alembic migration files are not packaged into the image, so we apply the schema with
metadata.create_all (idempotent — creates only missing tables). For alembic-tracked
migrations in containers, package core/alembic into the image and run `alembic upgrade head`
here instead (tracked as a hardening follow-up).
"""
import subprocess
import sys

print("Ensuring database schema (create_all)...")
import aiwip_core.models  # noqa: F401 — register all tables on Base.metadata
from aiwip_core.db import Base, get_engine

Base.metadata.create_all(get_engine())
print("Schema ready. Starting uvicorn...")
sys.exit(subprocess.call(["uvicorn", "aiwip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]))
