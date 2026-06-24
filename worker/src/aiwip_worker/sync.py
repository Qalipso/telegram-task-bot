"""Sync engine: fetch new messages from a connector and persist them idempotently.

Invariants:
- dedup on (chat_id, external_message_id) — re-sync creates no duplicates;
- sync_state advances ONLY after a successful run (failures leave last_external_message_id intact);
- every run is recorded in sync_runs (success | failed), with errors captured.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiwip_core import audit
from aiwip_core.logging import get_logger
from aiwip_core.models import (
    AttachmentProcessingStatus,
    AttachmentType,
    AuditAction,
    AuditEntityType,
    Chat,
    Message,
    MessageAttachment,
    MessageProcessingStatus,
    MessageType,
    SyncRun,
    SyncRunStatus,
    SyncState,
    SyncTriggerType,
)

from .connectors.base import Connector

logger = get_logger("aiwip.worker.sync")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def get_or_create_sync_state(db: Session, chat_id: int) -> SyncState:
    state = db.execute(select(SyncState).where(SyncState.chat_id == chat_id)).scalar_one_or_none()
    if state is None:
        state = SyncState(chat_id=chat_id)
        db.add(state)
        db.flush()
    return state


def run_sync(
    db: Session,
    connector: Connector,
    chat: Chat,
    trigger_type: SyncTriggerType = SyncTriggerType.manual,
    created_by_user_id: int | None = None,
    batch_limit: int = 200,
) -> SyncRun:
    run = SyncRun(
        trigger_type=trigger_type,
        status=SyncRunStatus.running,
        started_at=_utcnow(),
        created_by_user_id=created_by_user_id,
    )
    db.add(run)
    db.flush()
    state = get_or_create_sync_state(db, chat.id)
    audit.record_audit(db, created_by_user_id, AuditAction.sync_started, AuditEntityType.sync_run, run.id)
    db.commit()  # persist the running run + state baseline before doing fallible work

    try:
        fetched = connector.fetch_messages(chat.external_chat_id, state.last_external_message_id, batch_limit)
        fetched_ids = [fm.external_message_id for fm in fetched]
        existing: set[int] = set()
        if fetched_ids:
            existing = set(
                db.execute(
                    select(Message.external_message_id).where(
                        Message.chat_id == chat.id, Message.external_message_id.in_(fetched_ids)
                    )
                ).scalars().all()
            )
        max_id = state.last_external_message_id
        saved = 0
        for fm in fetched:
            if fm.external_message_id in existing:
                continue
            message = Message(
                chat_id=chat.id,
                external_message_id=fm.external_message_id,
                sender_external_id=fm.sender_external_id,
                sender_username=fm.sender_username,
                sender_display_name=fm.sender_display_name,
                message_type=MessageType(fm.message_type),
                text_content=fm.text,
                sent_at=fm.sent_at,
                synced_at=_utcnow(),
                raw_payload=fm.raw,
                processing_status=MessageProcessingStatus.new,
            )
            db.add(message)
            for att in fm.attachments:
                db.add(
                    MessageAttachment(
                        message=message,
                        attachment_type=AttachmentType(att.attachment_type),
                        file_name=att.file_name,
                        mime_type=att.mime_type,
                        processing_status=AttachmentProcessingStatus.new,
                    )
                )
            saved += 1
            if max_id is None or fm.external_message_id > max_id:
                max_id = fm.external_message_id

        state.last_external_message_id = max_id
        state.last_synced_at = _utcnow()
        state.last_successful_sync_at = _utcnow()
        state.last_error = None
        run.status = SyncRunStatus.success
        run.messages_read = len(fetched)
        run.messages_saved = saved
        run.finished_at = _utcnow()
        audit.record_audit(
            db, created_by_user_id, AuditAction.sync_finished, AuditEntityType.sync_run, run.id,
            after={"status": "success", "messages_read": len(fetched), "messages_saved": saved},
        )
        db.commit()
        logger.info("sync ok chat=%s read=%s saved=%s", chat.id, len(fetched), saved)
        return run
    except Exception as exc:  # noqa: BLE001 — any failure must be recorded, not crash the worker
        db.rollback()
        run.status = SyncRunStatus.failed
        run.error_message = str(exc)
        run.finished_at = _utcnow()
        state.last_error = str(exc)
        audit.record_audit(
            db, created_by_user_id, AuditAction.sync_finished, AuditEntityType.sync_run, run.id,
            after={"status": "failed", "error": str(exc)},
        )
        db.commit()
        logger.warning("sync failed chat=%s err=%s", chat.id, exc)
        return run
