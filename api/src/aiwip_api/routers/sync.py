"""Sync control endpoints (admin-only): trigger + status + history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_core import queue
from aiwip_core.config import settings
from aiwip_core.models import SyncRun, SyncState, User

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncRunRequest(BaseModel):
    chat_id: int | None = None


def _run_dict(r: SyncRun) -> dict:
    return {
        "id": r.id,
        "trigger_type": r.trigger_type.value,
        "status": r.status.value,
        "messages_read": r.messages_read,
        "messages_saved": r.messages_saved,
        "error_message": r.error_message,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_sync(
    payload: SyncRunRequest, admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
) -> dict:
    chat_id = payload.chat_id if payload.chat_id is not None else settings.telegram_chat_id
    if chat_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No chat_id provided and TELEGRAM_CHAT_ID is unset")
    queue.enqueue_sync(chat_id, trigger="manual", user_id=admin.id)
    return {"status": "queued", "chat_id": chat_id, "queue_length": queue.queue_length()}


@router.get("/status")
def sync_status(admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)) -> dict:
    latest = db.execute(select(SyncRun).order_by(desc(SyncRun.id)).limit(1)).scalar_one_or_none()
    states = db.execute(select(SyncState)).scalars().all()
    return {
        "queue_length": queue.queue_length(),
        "latest_run": _run_dict(latest) if latest else None,
        "states": [
            {
                "chat_id": s.chat_id,
                "last_external_message_id": s.last_external_message_id,
                "last_successful_sync_at": s.last_successful_sync_at.isoformat() if s.last_successful_sync_at else None,
                "last_error": s.last_error,
            }
            for s in states
        ],
    }


@router.get("/history")
def sync_history(
    limit: int = 20, admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
) -> list[dict]:
    runs = db.execute(select(SyncRun).order_by(desc(SyncRun.id)).limit(min(limit, 100))).scalars().all()
    return [_run_dict(r) for r in runs]
