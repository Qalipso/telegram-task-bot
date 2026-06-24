"""Candidate review (admin-only): list / detail / edit / approve / reject.

Approve promotes the candidate to a WorkItem (D25). Every review action is audited.
Rejected candidates are kept in history (status only). Approved candidates are immutable.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from aiwip_api import auth
from aiwip_api.schemas import CandidateOut, UpdateCandidateRequest, WorkItemOut
from aiwip_core import audit, promotion
from aiwip_core.models import (
    Assignee,
    AuditAction,
    AuditEntityType,
    Candidate,
    CandidateAssignee,
    CandidateMessage,
    CandidateStatus,
    Message,
    User,
)

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


def _editable_snapshot(c: Candidate) -> dict:
    return {
        "title": c.title,
        "summary": c.summary,
        "candidate_type": c.candidate_type.value,
        "priority": c.priority.value if c.priority else None,
        "due_date": c.due_date.isoformat() if c.due_date else None,
    }


def _get_or_404(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return candidate


def _set_candidate_assignees(db: Session, candidate: Candidate, assignee_ids: list[int]) -> None:
    """Replace the candidate's responsible person(s) (first id = primary) and keep the
    'assignee' missing-field flag in sync."""
    db.query(CandidateAssignee).filter_by(candidate_id=candidate.id).delete()
    for i, aid in enumerate(assignee_ids):
        db.add(CandidateAssignee(candidate_id=candidate.id, assignee_id=aid, is_primary=(i == 0)))
    missing = [f for f in (candidate.missing_fields or []) if f != "assignee"]
    if not assignee_ids:
        missing.append("assignee")
    candidate.missing_fields = missing


@router.get("", response_model=list[CandidateOut])
def list_candidates(
    status_filter: CandidateStatus | None = Query(None, alias="status"),
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
):
    query = select(Candidate).order_by(desc(Candidate.id))
    if status_filter is not None:
        query = query.where(Candidate.status == status_filter)
    return db.execute(query).scalars().all()


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: int, _admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
) -> dict:
    candidate = _get_or_404(db, candidate_id)
    assignees = db.execute(
        select(CandidateAssignee, Assignee)
        .join(Assignee, Assignee.id == CandidateAssignee.assignee_id)
        .where(CandidateAssignee.candidate_id == candidate_id)
    ).all()
    links = db.execute(
        select(CandidateMessage, Message)
        .join(Message, Message.id == CandidateMessage.message_id)
        .where(CandidateMessage.candidate_id == candidate_id)
        .order_by(Message.external_message_id)
    ).all()
    return {
        "candidate": CandidateOut.model_validate(candidate).model_dump(),
        "assignees": [
            {
                "assignee_id": ca.assignee_id,
                "is_primary": ca.is_primary,
                "display_name": a.display_name,
                "telegram_username": a.telegram_username,
            }
            for ca, a in assignees
        ],
        "messages": [
            {
                "message_id": link.message_id,
                "role": link.role.value,
                "external_message_id": msg.external_message_id,
                "sender": msg.sender_display_name or msg.sender_username,
                "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
                "text": msg.normalized_content or msg.text_content,
            }
            for link, msg in links
        ],
    }


@router.patch("/{candidate_id}", response_model=CandidateOut)
def edit_candidate(
    candidate_id: int,
    payload: UpdateCandidateRequest,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> Candidate:
    candidate = _get_or_404(db, candidate_id)
    if candidate.status == CandidateStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot edit an approved candidate")
    before = _editable_snapshot(candidate)
    data = payload.model_dump(exclude_unset=True)
    assignee_ids = data.pop("assignee_ids", None)
    for field, value in data.items():
        setattr(candidate, field, value)
    if assignee_ids is not None:
        _set_candidate_assignees(db, candidate, assignee_ids)
    candidate.status = CandidateStatus.edited
    db.flush()
    audit.record_audit(
        db, admin.id, AuditAction.candidate_edited, AuditEntityType.candidate, candidate.id,
        before=before, after=_editable_snapshot(candidate),
    )
    db.commit()
    db.refresh(candidate)
    return candidate


@router.post("/{candidate_id}/approve", response_model=WorkItemOut, status_code=status.HTTP_201_CREATED)
def approve_candidate(
    candidate_id: int, admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
):
    candidate = _get_or_404(db, candidate_id)
    if candidate.status == CandidateStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Candidate already approved")
    work_item = promotion.approve_candidate(db, candidate, admin.id)
    audit.record_audit(
        db, admin.id, AuditAction.candidate_approved, AuditEntityType.candidate, candidate.id,
        after={"work_item_id": work_item.id},
    )
    db.commit()
    db.refresh(work_item)
    return work_item


@router.post("/{candidate_id}/reject", response_model=CandidateOut)
def reject_candidate(
    candidate_id: int, admin: User = Depends(auth.require_admin), db: Session = Depends(auth.get_db)
) -> Candidate:
    candidate = _get_or_404(db, candidate_id)
    if candidate.status == CandidateStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot reject an approved candidate")
    candidate.status = CandidateStatus.rejected
    candidate.reviewed_at = dt.datetime.now(dt.timezone.utc)
    candidate.reviewed_by_user_id = admin.id
    audit.record_audit(db, admin.id, AuditAction.candidate_rejected, AuditEntityType.candidate, candidate.id)
    db.commit()
    db.refresh(candidate)
    return candidate
