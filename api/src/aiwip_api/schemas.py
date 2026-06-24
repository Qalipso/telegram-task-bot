"""Pydantic request/response schemas for the API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

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
    missing_fields: list[str] | None = None
    created_at: dt.datetime


class UpdateCandidateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    candidate_type: CandidateType | None = None
    priority: Priority | None = None
    due_date: dt.datetime | None = None


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


class StatusChangeRequest(BaseModel):
    status: WorkItemStatus


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
