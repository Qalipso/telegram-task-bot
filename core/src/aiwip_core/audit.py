"""Audit logging helper (system-spec §18)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditAction, AuditEntityType, AuditLog


def record_audit(
    db: Session,
    actor_user_id: int | None,
    action: AuditAction,
    entity_type: AuditEntityType,
    entity_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_value=before,
        after_value=after,
    )
    db.add(entry)
    return entry
