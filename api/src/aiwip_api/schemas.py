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
