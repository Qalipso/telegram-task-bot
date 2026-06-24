"""Audit log query (admin-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import AuditOut
from aiwip_core.models import AuditAction, AuditEntityType, AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    entity_type: AuditEntityType | None = Query(None),
    action: AuditAction | None = Query(None),
    actor_user_id: int | None = Query(None),
    limit: int = 100,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
):
    query = select(AuditLog).order_by(desc(AuditLog.id))
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if actor_user_id is not None:
        query = query.where(AuditLog.actor_user_id == actor_user_id)
    return db.execute(query.limit(min(limit, 500))).scalars().all()
