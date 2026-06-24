"""Minimal Redis job queue (Full v1.0 §21).

A single Redis list holds JSON jobs; producers LPUSH, the worker BRPOPs. Retry is handled by
the consumer re-enqueueing failed sync jobs (bounded attempts); the persisted failed `sync_runs`
row is the dead-letter record (D14 admin re-run = a fresh `retry` run).
"""
from __future__ import annotations

import json

import redis

from aiwip_core.redis_client import get_redis

JOBS_KEY = "aiwip:jobs"


def enqueue(job: dict) -> None:
    get_redis().lpush(JOBS_KEY, json.dumps(job))


def dequeue(timeout: int = 5) -> dict | None:
    try:
        res = get_redis().brpop(JOBS_KEY, timeout=timeout)
    except redis.exceptions.TimeoutError:
        return None  # idle BRPOP socket timeout — treat as "no job available"
    if res is None:
        return None
    return json.loads(res[1])


def queue_length() -> int:
    return int(get_redis().llen(JOBS_KEY))


def enqueue_sync(chat_id: int, trigger: str = "manual", user_id: int | None = None, attempts: int = 0) -> None:
    enqueue(
        {"type": "telegram.sync", "chat_id": chat_id, "trigger": trigger, "user_id": user_id, "attempts": attempts}
    )
