"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aiwip_core.models import UserRole


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
