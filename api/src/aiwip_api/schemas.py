"""Pydantic request/response schemas for the API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from aiwip_core.models import (
    AuditAction,
    AuditEntityType,
    CandidateStatus,
    CandidateType,
    EvaluationResult,
    Priority,
    UserRole,
    WorkItemStatus,
    WorkItemType,
)


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: UserRole = UserRole.assignee
    display_name: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None = None
    role: UserRole


class CreateAssigneeRequest(BaseModel):
    display_name: str | None = None
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    aliases: list[str] = []
    user_id: int | None = None
    is_active: bool = True


class UpdateAssigneeRequest(BaseModel):
    display_name: str | None = None
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    aliases: list[str] | None = None
    user_id: int | None = None
    is_active: bool | None = None


class AssigneeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None = None
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    aliases: list[str] | None = None
    is_active: bool
    user_id: int | None = None


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_type: CandidateType
    title: str | None = None
    summary: str | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None
    status: CandidateStatus
    task_confidence: float | None = None
    # §6.2 per-field confidences (give the bot a richer policy than status alone).
    assignee_confidence: float | None = None
    priority_confidence: float | None = None
    due_date_confidence: float | None = None
    context_confidence: float | None = None
    missing_fields: list[str] | None = None
    # §6.1C: raw unmatched/ambiguous mention text, for the [Assign…] picker title.
    unresolved_mentions: list[str] | None = None
    created_at: dt.datetime
    # Source chat (external Telegram id + title) — set by the enrich layer, default None.
    source_chat_id: int | None = None
    source_chat_title: str | None = None
    # Resolved assignee display names (primary first) — set by the enrich/detail layer.
    assignees: list[str] = Field(default_factory=list)

    # Populated from the ORM relationship Candidate.candidate_assignees; excluded from output.
    # Reduced to a list of assignee ids so we can derive assignee_count without a nested schema.
    candidate_assignees: list[int] = Field(default_factory=list, exclude=True)

    @field_validator("candidate_assignees", mode="before")
    @classmethod
    def _coerce_assignee_rows(cls, v: object) -> list[int]:
        """Accept the ORM list of CandidateAssignee rows (or any iterable) and reduce it to a
        list of assignee ids, so model_validate(orm_candidate) populates it."""
        if not v:
            return []
        ids: list[int] = []
        for row in v:
            aid = getattr(row, "assignee_id", None)
            if aid is not None:
                ids.append(aid)
        return ids

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_count(self) -> int:
        return len(self.candidate_assignees)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assignee_ambiguous(self) -> bool:
        """§6.1B: ambiguous if 2+ assignees are linked OR any mention went unresolved."""
        return self.assignee_count > 1 or bool(self.unresolved_mentions)


class UpdateCandidateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    candidate_type: CandidateType | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None
    assignee_ids: list[int] | None = None  # set/replace the responsible person(s); first is primary


class WorkItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: WorkItemType
    title: str | None = None
    summary: str | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None
    status: WorkItemStatus
    source_candidate_id: int
    # Enriched fields (set by the enrich layer; default empty/None so model_validate(orm) works).
    assignees: list[str] = Field(default_factory=list)  # display names, primary first
    source_chat_id: int | None = None  # external Telegram chat id
    source_chat_title: str | None = None


class StatusChangeRequest(BaseModel):
    status: WorkItemStatus


class UpdateWorkItemRequest(BaseModel):
    """Partial edit of a work item's content fields (admin-only). Omitted fields
    are left unchanged; explicit null clears a nullable field."""
    title: str | None = Field(default=None, max_length=512)  # matches WorkItem.title column
    summary: str | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None


class CreateLabelRequest(BaseModel):
    name: str
    color: str | None = None


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str | None = None


class AssignLabelRequest(BaseModel):
    label_id: int


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None = None
    action: AuditAction
    entity_type: AuditEntityType
    entity_id: int | None = None
    before_value: dict | None = None
    after_value: dict | None = None
    created_at: dt.datetime


class CreateEvaluationCaseRequest(BaseModel):
    candidate_id: int | None = None  # derive input/expected from a reviewed candidate
    source_message_ids: list[int] | None = None
    input_payload: dict | None = None
    expected_output: dict | None = None
    actual_output: dict | None = None
    result: EvaluationResult = EvaluationResult.pending
    score: float | None = None
    comments: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None


class EvaluationCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_message_ids: list[int] | None = None
    input_payload: dict | None = None
    expected_output: dict | None = None
    actual_output: dict | None = None
    result: EvaluationResult
    score: float | None = None
    comments: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    created_at: dt.datetime


class TelegramLinkStartResponse(BaseModel):
    code: str
    expires_in_seconds: int


class TelegramRedeemRequest(BaseModel):
    code: str
    telegram_user_id: int  # data to WRITE after the code proves identity — NEVER trusted as identity


class TelegramRedeemResponse(BaseModel):
    status: str


class InviteStartResponse(BaseModel):
    code: str
    expires_in_seconds: int


class InviteRedeemRequest(BaseModel):
    code: str
    telegram_user_id: int            # data to WRITE after the code proves the invite — never identity
    display_name: str | None = None  # the new admin's name (from Telegram), for the Assignee row
    telegram_username: str | None = None
