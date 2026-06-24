"""Pydantic models for validating the LLM's structured output (llm-extraction-spec.md)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LLMConfidence(BaseModel):
    item: float = 0.0
    context: float = 0.0
    assignee: float = 0.0
    priority: float = 0.0
    due_date: float = 0.0


class LLMCandidate(BaseModel):
    type: str
    title: str = ""
    summary: str = ""
    priority: str | None = None
    due_date: str | None = None
    assignees: list[str] = Field(default_factory=list)
    source_message_ids: list[int] = Field(default_factory=list)
    supporting_message_ids: list[int] = Field(default_factory=list)
    reasoning_summary: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    confidence: LLMConfidence = Field(default_factory=LLMConfidence)


class LLMOutput(BaseModel):
    candidates: list[LLMCandidate] = Field(default_factory=list)
    context_summary: str = ""
    context_confidence: float = 0.0
