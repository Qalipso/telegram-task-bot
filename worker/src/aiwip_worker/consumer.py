"""Job consumer + scheduler: turns queued sync jobs into run_sync calls."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core import queue
from aiwip_core.db import get_sessionmaker
from aiwip_core.logging import get_logger
from aiwip_core.models import (
    Chat,
    ConnectorType,
    Message,
    MessageProcessingStatus,
    SyncRun,
    SyncRunStatus,
    SyncTriggerType,
)

from . import extract, normalize, sync
from .connectors.base import Connector
from .connectors.bot_api import BotApiConnector

logger = get_logger("aiwip.worker.consumer")
MAX_ATTEMPTS = 3


def build_connector(connector_type: str) -> Connector:
    """Pick the transport for a chat. Bot-only after the Phase-6 cutover (Decisions §16.1)."""
    if connector_type == "telegram_bot":
        return BotApiConnector()
    raise ValueError(f"no connector for connector_type={connector_type!r}")


def get_or_create_chat(
    db: Session, chat_id: int, connector_type: ConnectorType = ConnectorType.telegram
) -> Chat:
    # Look up by external id ALONE: a chat is owned by exactly one transport (design §4.2), so a
    # bot-owned (telegram_bot) chat must be FOUND here, not duplicated as a second telegram row.
    chat = db.execute(
        select(Chat).where(Chat.external_chat_id == chat_id)
    ).scalars().first()
    if chat is None:
        chat = Chat(connector_type=connector_type, external_chat_id=chat_id, title=f"chat {chat_id}")
        db.add(chat)
        db.commit()
    return chat


def sync_chat(
    db: Session, connector: Connector, chat_id: int, trigger: SyncTriggerType = SyncTriggerType.manual, user_id: int | None = None
) -> SyncRun:
    chat = get_or_create_chat(db, chat_id)
    return sync.run_sync(db, connector, chat, trigger, created_by_user_id=user_id)


def _mark_analyzed(db: Session, internal_chat_id: int) -> None:
    """Flip this chat's normalized messages to 'analyzed' after an extraction pass."""
    db.query(Message).filter(
        Message.chat_id == internal_chat_id,
        Message.processing_status == MessageProcessingStatus.normalized,
    ).update({Message.processing_status: MessageProcessingStatus.analyzed})
    db.commit()


def run_pipeline(
    db: Session,
    connector: Connector,
    chat_id: int,
    trigger: SyncTriggerType = SyncTriggerType.manual,
    user_id: int | None = None,
    llm_client=None,
) -> SyncRun:
    """Full ingestion pipeline for one sync: sync → normalize → (gated) extract.

    Extraction runs only when this sync actually saved new messages, so the periodic
    scheduled sync does not re-extract an unchanged window into duplicate candidates.
    A failed extraction is logged but never fails the (successful) sync job.
    """
    chat = get_or_create_chat(db, chat_id)
    run = sync.run_sync(db, connector, chat, trigger, created_by_user_id=user_id)
    normalize.normalize_pending(db)
    if run.status == SyncRunStatus.success and (run.messages_saved or 0) > 0:
        try:
            created = extract.extract_candidates(db, chat.id, client=llm_client)
            for cand in created:
                queue.enqueue_notify(cand.id)  # worker → bot: render a confirm card
        except Exception:  # noqa: BLE001 — extraction failure must not fail the sync job
            logger.exception("extraction failed chat=%s", chat_id)
        _mark_analyzed(db, chat.id)
    return run


def should_requeue(status: SyncRunStatus, attempts: int) -> bool:
    return status == SyncRunStatus.failed and (attempts + 1) < MAX_ATTEMPTS


def process_job(job: dict, connector_factory=None, session_factory=None, llm_client=None) -> None:
    if job.get("type") != "telegram.sync":
        logger.warning("unknown job type: %s", job.get("type"))
        return
    sf = session_factory or get_sessionmaker()
    chat_id = job["chat_id"]
    trigger = SyncTriggerType(job.get("trigger", "manual"))
    with sf() as db:
        # Resolve the chat once; its connector_type is the source of truth for transport selection.
        chat = get_or_create_chat(db, chat_id)
        connector = connector_factory() if connector_factory else build_connector(chat.connector_type.value)
        run = run_pipeline(db, connector, chat_id, trigger, job.get("user_id"), llm_client=llm_client)
        status = run.status
    attempts = job.get("attempts", 0)
    if status == SyncRunStatus.failed:
        if should_requeue(status, attempts):
            queue.enqueue_sync(chat_id, job.get("trigger", "manual"), job.get("user_id"), attempts + 1)
            logger.warning("requeued sync chat=%s attempt=%s", chat_id, attempts + 1)
        else:
            logger.error("sync chat=%s permanently failed after %s attempts (see sync_runs)", chat_id, attempts + 1)


def consume_once(timeout: int = 5, connector_factory=None) -> bool:
    job = queue.dequeue(timeout=timeout)
    if job is None:
        return False
    process_job(job, connector_factory=connector_factory)
    return True
