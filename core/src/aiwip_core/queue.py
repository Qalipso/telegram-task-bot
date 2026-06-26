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
NOTIFY_KEY = "aiwip:bot:notify"  # worker → bot: {"type":"bot.notify","candidate_id":int}
BOTBUF_PREFIX = "aiwip:botbuf:"  # per-chat inbound buffer: aiwip:botbuf:{external_chat_id}


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


# --- bot-first capture layer: ingest buffer + worker→bot notify (spec §8) -------------------
def botbuf_key(external_chat_id: int) -> str:
    return f"{BOTBUF_PREFIX}{external_chat_id}"


def push_botbuf(external_chat_id: int, record: dict) -> None:
    """Append one inbound message record (forward-only). RPUSH keeps arrival order."""
    get_redis().rpush(botbuf_key(external_chat_id), json.dumps(record))


def botbuf_len(external_chat_id: int) -> int:
    return int(get_redis().llen(botbuf_key(external_chat_id)))


def enqueue_notify(candidate_id: int) -> None:
    get_redis().lpush(NOTIFY_KEY, json.dumps({"type": "bot.notify", "candidate_id": candidate_id}))


def dequeue_notify(timeout: int = 5) -> dict | None:
    try:
        res = get_redis().brpop(NOTIFY_KEY, timeout=timeout)
    except redis.exceptions.TimeoutError:
        return None
    if res is None:
        return None
    return json.loads(res[1])
