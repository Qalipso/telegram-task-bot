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
    AuditAction,
    AuditEntityType,
    Candidate,
    CandidateAssignee,
    CandidateMessage,
    CandidateStatus,
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
        select(CandidateAssignee).where(CandidateAssignee.candidate_id == candidate_id)
    ).scalars().all()
    links = db.execute(
        select(CandidateMessage).where(CandidateMessage.candidate_id == candidate_id)
    ).scalars().all()
    return {
        "candidate": CandidateOut.model_validate(candidate).model_dump(),
        "assignees": [{"assignee_id": a.assignee_id, "is_primary": a.is_primary} for a in assignees],
        "messages": [{"message_id": link.message_id, "role": link.role.value} for link in links],
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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(candidate, field, value)
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
