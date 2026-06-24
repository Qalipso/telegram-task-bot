"""Candidate → WorkItem promotion on approval (D16/D25).

Creates one WorkItem from the candidate snapshot (reasoning/confidence carried), copies
candidate_assignees → work_item_assignees (carry is_primary, drop per-row confidence) and
candidate_labels → work_item_labels. Source messages stay derivable via source_candidate_id (D16).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Candidate,
    CandidateAssignee,
    CandidateLabel,
    CandidateStatus,
    WorkItem,
    WorkItemAssignee,
    WorkItemLabel,
    WorkItemStatus,
    WorkItemType,
)


def approve_candidate(db: Session, candidate: Candidate, actor_user_id: int | None = None) -> WorkItem:
    work_item = WorkItem(
        source_candidate_id=candidate.id,
        type=WorkItemType(candidate.candidate_type.value),
        title=candidate.title,
        summary=candidate.summary,
        priority=candidate.priority,
        due_date=candidate.due_date,
        status=WorkItemStatus.inbox,
        reasoning=candidate.reasoning_summary,
        confidence=candidate.task_confidence,
        created_by_user_id=actor_user_id,
    )
    db.add(work_item)
    db.flush()

    for ca in db.execute(
        select(CandidateAssignee).where(CandidateAssignee.candidate_id == candidate.id)
    ).scalars():
        db.add(WorkItemAssignee(work_item_id=work_item.id, assignee_id=ca.assignee_id, is_primary=ca.is_primary))

    for cl in db.execute(
        select(CandidateLabel).where(CandidateLabel.candidate_id == candidate.id)
    ).scalars():
        db.add(WorkItemLabel(work_item_id=work_item.id, label_id=cl.label_id))

    candidate.status = CandidateStatus.approved
    candidate.reviewed_at = dt.datetime.now(dt.timezone.utc)
    candidate.reviewed_by_user_id = actor_user_id
    return work_item
