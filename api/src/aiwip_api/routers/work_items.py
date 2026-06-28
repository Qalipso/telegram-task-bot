"""WorkItem list + Kanban board + status transitions + tag assignment.

Visibility: admins see everything; assignees see (and can transition) only work items assigned to
them (system-spec §4). Status changes are audited (work_item_status_changed). Tag assignment is admin-only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, false, select
from sqlalchemy.orm import Session

from aiwip_api import auth, enrich
from aiwip_api.schemas import AssignLabelRequest, StatusChangeRequest, UpdateWorkItemRequest, WorkItemOut
from aiwip_core import audit
from aiwip_core.models import (
    Assignee,
    AuditAction,
    AuditEntityType,
    Label,
    User,
    UserRole,
    WorkItem,
    WorkItemAssignee,
    WorkItemLabel,
    WorkItemStatus,
)

router = APIRouter(prefix="/api/work-items", tags=["work-items"])


def _assignee_for(db: Session, user: User) -> Assignee | None:
    return db.execute(select(Assignee).where(Assignee.user_id == user.id)).scalar_one_or_none()


def _scope(db: Session, user: User, query):
    """Restrict a WorkItem query to what the user may see."""
    if user.role == UserRole.admin:
        return query
    assignee = _assignee_for(db, user)
    if assignee is None:
        return query.where(false())
    visible = select(WorkItemAssignee.work_item_id).where(WorkItemAssignee.assignee_id == assignee.id)
    return query.where(WorkItem.id.in_(visible))


def _get_visible_or_404(db: Session, user: User, work_item_id: int) -> WorkItem:
    work_item = db.execute(_scope(db, user, select(WorkItem).where(WorkItem.id == work_item_id))).scalar_one_or_none()
    if work_item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found")
    return work_item


@router.get("", response_model=list[WorkItemOut])
def list_work_items(
    status_filter: WorkItemStatus | None = Query(None, alias="status"),
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db),
):
    query = select(WorkItem).order_by(desc(WorkItem.id))
    if status_filter is not None:
        query = query.where(WorkItem.status == status_filter)
    items = db.execute(_scope(db, user, query)).scalars().all()
    return enrich.work_items_out(db, items)


@router.get("/board")
def board(user: User = Depends(auth.get_current_user), db: Session = Depends(auth.get_db)) -> dict:
    items = db.execute(_scope(db, user, select(WorkItem).order_by(WorkItem.id))).scalars().all()
    columns: dict[str, list] = {s.value: [] for s in WorkItemStatus}
    for wi in enrich.work_items_out(db, items):
        columns[wi.status.value].append(wi.model_dump())
    return {"columns": columns}


@router.get("/{work_item_id}")
def get_work_item(work_item_id: int, user: User = Depends(auth.get_current_user), db: Session = Depends(auth.get_db)) -> dict:
    wi = _get_visible_or_404(db, user, work_item_id)
    assignees = db.execute(
        select(WorkItemAssignee, Assignee)
        .join(Assignee, Assignee.id == WorkItemAssignee.assignee_id)
        .where(WorkItemAssignee.work_item_id == wi.id)
    ).all()
    labels = db.execute(
        select(Label).join(WorkItemLabel, WorkItemLabel.label_id == Label.id).where(WorkItemLabel.work_item_id == wi.id)
    ).scalars().all()
    return {
        "work_item": WorkItemOut.model_validate(wi).model_dump(),
        "assignees": [
            {
                "assignee_id": wa.assignee_id,
                "is_primary": wa.is_primary,
                "display_name": asg.display_name,
                "telegram_username": asg.telegram_username,
            }
            for wa, asg in assignees
        ],
        "labels": [{"id": label.id, "name": label.name} for label in labels],
    }


def _editable_snapshot(wi: WorkItem) -> dict:
    """Serialisable snapshot of the user-editable content fields, for the audit log."""
    return {
        "title": wi.title,
        "summary": wi.summary,
        "priority": wi.priority.value if wi.priority else None,
        "due_date": wi.due_date.isoformat() if wi.due_date else None,
    }


@router.patch("/{work_item_id}", response_model=WorkItemOut)
def edit_work_item(
    work_item_id: int,
    payload: UpdateWorkItemRequest,
    admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> WorkItem:
    wi = db.get(WorkItem, work_item_id)
    if wi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found")
    before = _editable_snapshot(wi)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wi, field, value)
    db.flush()
    audit.record_audit(
        db, admin.id, AuditAction.work_item_edited, AuditEntityType.work_item, wi.id,
        before=before, after=_editable_snapshot(wi),
    )
    db.commit()
    db.refresh(wi)
    return wi


@router.post("/{work_item_id}/status", response_model=WorkItemOut)
def change_status(
    work_item_id: int,
    payload: StatusChangeRequest,
    user: User = Depends(auth.get_current_user),
    db: Session = Depends(auth.get_db),
) -> WorkItem:
    wi = _get_visible_or_404(db, user, work_item_id)  # assignees may only transition their own
    before = wi.status.value
    wi.status = payload.status
    audit.record_audit(
        db, user.id, AuditAction.work_item_status_changed, AuditEntityType.work_item, wi.id,
        before={"status": before}, after={"status": payload.status.value},
    )
    db.commit()
    db.refresh(wi)
    return wi


@router.post("/{work_item_id}/labels", response_model=WorkItemOut, status_code=status.HTTP_201_CREATED)
def assign_label(
    work_item_id: int,
    payload: AssignLabelRequest,
    _admin: User = Depends(auth.require_admin),
    db: Session = Depends(auth.get_db),
) -> WorkItem:
    wi = db.get(WorkItem, work_item_id)
    if wi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work item not found")
    if db.get(Label, payload.label_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Label not found")
    exists = db.execute(
        select(WorkItemLabel).where(
            WorkItemLabel.work_item_id == work_item_id, WorkItemLabel.label_id == payload.label_id
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(WorkItemLabel(work_item_id=work_item_id, label_id=payload.label_id))
        db.commit()
    db.refresh(wi)
    return wi
