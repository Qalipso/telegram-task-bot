"""SQLAlchemy ORM models — full v1.0 schema (19 tables).

Source of truth: `docs/database-design.md` + ratified decisions D11–D25
(`docs/decisions.md`). Notable decision encodings:
- D11: candidate_type enum uses `decision`/`risk` (reserved/inactive — the LLM never emits them).
- D13: attachment_type = voice|image|document (no `photo`).
- D15: attachment processing_status enum = new|processing|processed|failed|skipped.
- D16: WorkItem source messages are DERIVED (source_candidate_id → candidate_messages); no join table.
- D17: candidates.missing_fields (jsonb).
- D20: candidates.context_summary (text) + context_confidence.
- D22: audit_logs.entity_type enum = candidate|work_item|assignee|chat|sync_run|message.
- D24: assignees.user_id nullable FK + unique (one user ↔ at most one assignee).
- D25: work_item_assignees.is_primary carried on approval; candidate_assignees keeps per-row confidence.

Under-specified status fields (connector_accounts.status, sync_states.status, ai_runs.status) use
String rather than a fabricated enum, since the docs do not enumerate their values.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# --------------------------------------------------------------------------- enums
class UserRole(str, enum.Enum):
    admin = "admin"
    assignee = "assignee"


class ConnectorType(str, enum.Enum):
    telegram = "telegram"          # active (MVP) — Telethon, removed at the Phase-6 cutover
    telegram_bot = "telegram_bot"  # active — Bot API forward-only capture (bot-first layer)
    slack = "slack"        # reserved/future
    email = "email"        # reserved/future
    whatsapp = "whatsapp"  # reserved/future
    discord = "discord"    # reserved/future


class MessageType(str, enum.Enum):
    text = "text"
    voice = "voice"
    image = "image"
    document = "document"
    mixed = "mixed"


class MessageProcessingStatus(str, enum.Enum):
    new = "new"
    normalized = "normalized"
    analyzed = "analyzed"
    failed = "failed"
    skipped = "skipped"


class AttachmentType(str, enum.Enum):
    voice = "voice"
    image = "image"
    document = "document"


class AttachmentProcessingStatus(str, enum.Enum):
    new = "new"
    processing = "processing"
    processed = "processed"
    failed = "failed"
    skipped = "skipped"


class SyncTriggerType(str, enum.Enum):
    scheduled = "scheduled"
    manual = "manual"
    retry = "retry"


class SyncRunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    partial_success = "partial_success"
    failed = "failed"


class CandidateType(str, enum.Enum):
    task = "task"
    request = "request"
    reminder = "reminder"
    idea = "idea"
    knowledge = "knowledge"
    decision = "decision"  # reserved/inactive (D11) — never emitted by the LLM
    risk = "risk"          # reserved/inactive (D11)


class CandidateStatus(str, enum.Enum):
    new = "new"
    needs_review = "needs_review"
    edited = "edited"
    approved = "approved"
    rejected = "rejected"
    duplicate = "duplicate"
    error = "error"


class Priority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    # `null` priority is represented by a NULL column value, not an enum member.


class CandidateMessageRole(str, enum.Enum):
    primary = "primary"
    context = "context"
    supporting = "supporting"


class WorkItemType(str, enum.Enum):
    task = "task"
    request = "request"
    reminder = "reminder"
    idea = "idea"
    knowledge = "knowledge"


class WorkItemStatus(str, enum.Enum):
    inbox = "inbox"
    backlog = "backlog"
    ready = "ready"
    in_progress = "in_progress"
    blocked = "blocked"
    review = "review"
    done = "done"
    cancelled = "cancelled"
    archived = "archived"


class AiRunType(str, enum.Enum):
    classification = "classification"
    extraction = "extraction"
    due_date_resolution = "due_date_resolution"
    vision_analysis = "vision_analysis"
    document_analysis = "document_analysis"
    evaluation = "evaluation"


class EvaluationResult(str, enum.Enum):
    passed = "pass"
    failed = "fail"
    partial = "partial"
    pending = "pending"


class AuditAction(str, enum.Enum):
    sync_started = "sync_started"
    sync_finished = "sync_finished"
    candidate_created = "candidate_created"
    candidate_edited = "candidate_edited"
    candidate_approved = "candidate_approved"
    candidate_rejected = "candidate_rejected"
    candidate_marked_duplicate = "candidate_marked_duplicate"
    work_item_status_changed = "work_item_status_changed"
    work_item_edited = "work_item_edited"
    work_item_reassigned = "work_item_reassigned"
    assignee_created = "assignee_created"
    assignee_updated = "assignee_updated"


class AuditEntityType(str, enum.Enum):
    candidate = "candidate"
    work_item = "work_item"
    assignee = "assignee"
    chat = "chat"
    sync_run = "sync_run"
    message = "message"


def _pg_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """Native Postgres enum storing the member *values* (lowercase tokens)."""
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


# One instance per type so each CREATE TYPE is emitted exactly once and shared across columns.
user_role_enum = _pg_enum(UserRole, "user_role")
connector_type_enum = _pg_enum(ConnectorType, "connector_type")
message_type_enum = _pg_enum(MessageType, "message_type")
message_processing_status_enum = _pg_enum(MessageProcessingStatus, "message_processing_status")
attachment_type_enum = _pg_enum(AttachmentType, "attachment_type")
attachment_processing_status_enum = _pg_enum(AttachmentProcessingStatus, "attachment_processing_status")
sync_trigger_type_enum = _pg_enum(SyncTriggerType, "sync_trigger_type")
sync_run_status_enum = _pg_enum(SyncRunStatus, "sync_run_status")
candidate_type_enum = _pg_enum(CandidateType, "candidate_type")
candidate_status_enum = _pg_enum(CandidateStatus, "candidate_status")
priority_enum = _pg_enum(Priority, "priority")
candidate_message_role_enum = _pg_enum(CandidateMessageRole, "candidate_message_role")
work_item_type_enum = _pg_enum(WorkItemType, "work_item_type")
work_item_status_enum = _pg_enum(WorkItemStatus, "work_item_status")
ai_run_type_enum = _pg_enum(AiRunType, "ai_run_type")
evaluation_result_enum = _pg_enum(EvaluationResult, "evaluation_result")
audit_action_enum = _pg_enum(AuditAction, "audit_action")
audit_entity_type_enum = _pg_enum(AuditEntityType, "audit_entity_type")


# --------------------------------------------------------------------------- mixins
def _created_at() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated_at() -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- identity / config
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # bcrypt hash; NULL = no password login
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()

    assignee: Mapped["Assignee | None"] = relationship(back_populates="user", uselist=False)


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("connector_type", "external_chat_id", name="uq_chats_connector_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connector_type: Mapped[ConnectorType] = mapped_column(connector_type_enum, nullable=False)
    external_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()

    messages: Mapped[list["Message"]] = relationship(back_populates="chat")


class ConnectorAccount(Base):
    __tablename__ = "connector_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector_type: Mapped[ConnectorType] = mapped_column(connector_type_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # under-specified in docs → String; sensible default.
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    # D21: a reference to the secret (env var name / secret-manager key), never the secret itself.
    credentials_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()


# --------------------------------------------------------------------------- messages
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "external_message_id", name="uq_messages_chat_external"),
        Index("ix_messages_chat_id", "chat_id"),
        Index("ix_messages_external_message_id", "external_message_id"),
        Index("ix_messages_sent_at", "sent_at"),
        Index("ix_messages_processing_status", "processing_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    external_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_external_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_username: Mapped[str | None] = mapped_column(String(255))
    sender_display_name: Mapped[str | None] = mapped_column(String(255))
    message_type: Mapped[MessageType] = mapped_column(message_type_enum, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    processing_status: Mapped[MessageProcessingStatus] = mapped_column(
        message_processing_status_enum, nullable=False, server_default=text("'new'")
    )
    created_at: Mapped[dt.datetime] = _created_at()

    chat: Mapped["Chat"] = relationship(back_populates="messages")
    attachments: Mapped[list["MessageAttachment"]] = relationship(back_populates="message")


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (Index("ix_message_attachments_message_id", "message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    attachment_type: Mapped[AttachmentType] = mapped_column(attachment_type_enum, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    vision_summary: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[AttachmentProcessingStatus] = mapped_column(
        attachment_processing_status_enum, nullable=False, server_default=text("'new'")
    )
    created_at: Mapped[dt.datetime] = _created_at()

    message: Mapped["Message"] = relationship(back_populates="attachments")


# --------------------------------------------------------------------------- sync
class SyncState(Base):
    __tablename__ = "sync_states"
    __table_args__ = (UniqueConstraint("chat_id", name="uq_sync_states_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_external_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_successful_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(32))  # under-specified → String
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = _updated_at()


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_type: Mapped[SyncTriggerType] = mapped_column(sync_trigger_type_enum, nullable=False)
    status: Mapped[SyncRunStatus] = mapped_column(sync_run_status_enum, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    messages_read: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    messages_saved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    messages_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    candidates_created: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# --------------------------------------------------------------------------- assignees
class Assignee(Base):
    __tablename__ = "assignees"
    __table_args__ = (
        # D24: one user ↔ at most one assignee (nullable FK; uniqueness ignores NULLs in Postgres).
        UniqueConstraint("user_id", name="uq_assignees_user"),
        Index("ix_assignees_telegram_user_id", "telegram_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list | None] = mapped_column(JSONB)  # JSON array of alias strings
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()

    user: Mapped["User | None"] = relationship(back_populates="assignee")


# --------------------------------------------------------------------------- candidates
class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (Index("ix_candidates_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_type: Mapped[CandidateType] = mapped_column(candidate_type_enum, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority | None] = mapped_column(priority_enum)  # NULL allowed
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[CandidateStatus] = mapped_column(
        candidate_status_enum, nullable=False, server_default=text("'new'")
    )

    task_confidence: Mapped[float | None] = mapped_column(Float)
    context_confidence: Mapped[float | None] = mapped_column(Float)
    assignee_confidence: Mapped[float | None] = mapped_column(Float)
    priority_confidence: Mapped[float | None] = mapped_column(Float)
    due_date_confidence: Mapped[float | None] = mapped_column(Float)

    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    missing_fields: Mapped[list | None] = mapped_column(JSONB)  # D17
    unresolved_mentions: Mapped[list | None] = mapped_column(JSONB)  # spec §6.1C: raw unmatched/ambiguous mention text
    context_summary: Mapped[str | None] = mapped_column(Text)   # D20
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    candidate_messages: Mapped[list["CandidateMessage"]] = relationship(back_populates="candidate")
    candidate_assignees: Mapped[list["CandidateAssignee"]] = relationship(back_populates="candidate")
    candidate_labels: Mapped[list["CandidateLabel"]] = relationship(back_populates="candidate")
    work_item: Mapped["WorkItem | None"] = relationship(back_populates="source_candidate", uselist=False)


class CandidateMessage(Base):
    __tablename__ = "candidate_messages"
    __table_args__ = (
        UniqueConstraint("candidate_id", "message_id", name="uq_candidate_messages_pair"),
        Index("ix_candidate_messages_candidate_id", "candidate_id"),
        Index("ix_candidate_messages_message_id", "message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[CandidateMessageRole] = mapped_column(candidate_message_role_enum, nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()

    candidate: Mapped["Candidate"] = relationship(back_populates="candidate_messages")
    message: Mapped["Message"] = relationship()


class CandidateAssignee(Base):
    __tablename__ = "candidate_assignees"
    __table_args__ = (
        UniqueConstraint("candidate_id", "assignee_id", name="uq_candidate_assignees_pair"),
        Index("ix_candidate_assignees_candidate_id", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    assignee_id: Mapped[int] = mapped_column(
        ForeignKey("assignees.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float)  # per-row score (D19)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = _created_at()

    candidate: Mapped["Candidate"] = relationship(back_populates="candidate_assignees")
    assignee: Mapped["Assignee"] = relationship()


class CandidateLabel(Base):
    __tablename__ = "candidate_labels"
    __table_args__ = (
        UniqueConstraint("candidate_id", "label_id", name="uq_candidate_labels_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()

    candidate: Mapped["Candidate"] = relationship(back_populates="candidate_labels")
    label: Mapped["Label"] = relationship()


# --------------------------------------------------------------------------- labels
class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = _created_at()


# --------------------------------------------------------------------------- work items
class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        # "One approved candidate creates one work_item" → 1:1 traceability.
        UniqueConstraint("source_candidate_id", name="uq_work_items_source_candidate"),
        Index("ix_work_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[WorkItemType] = mapped_column(work_item_type_enum, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority | None] = mapped_column(priority_enum)
    due_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[WorkItemStatus] = mapped_column(
        work_item_status_enum, nullable=False, server_default=text("'inbox'")
    )
    reasoning: Mapped[str | None] = mapped_column(Text)       # snapshot at approval
    confidence: Mapped[float | None] = mapped_column(Float)   # snapshot at approval
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    source_candidate: Mapped["Candidate"] = relationship(back_populates="work_item")
    work_item_assignees: Mapped[list["WorkItemAssignee"]] = relationship(back_populates="work_item")
    work_item_labels: Mapped[list["WorkItemLabel"]] = relationship(back_populates="work_item")


class WorkItemAssignee(Base):
    __tablename__ = "work_item_assignees"
    __table_args__ = (
        UniqueConstraint("work_item_id", "assignee_id", name="uq_work_item_assignees_pair"),
        Index("ix_work_item_assignees_assignee_id", "assignee_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    assignee_id: Mapped[int] = mapped_column(
        ForeignKey("assignees.id", ondelete="CASCADE"), nullable=False
    )
    # D25: is_primary carried from candidate_assignees on approval (per-row confidence dropped).
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = _created_at()

    work_item: Mapped["WorkItem"] = relationship(back_populates="work_item_assignees")
    assignee: Mapped["Assignee"] = relationship()


class WorkItemLabel(Base):
    __tablename__ = "work_item_labels"
    __table_args__ = (
        UniqueConstraint("work_item_id", "label_id", name="uq_work_item_labels_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()

    work_item: Mapped["WorkItem"] = relationship(back_populates="work_item_labels")
    label: Mapped["Label"] = relationship()


# --------------------------------------------------------------------------- observability / eval / audit
class AiRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (Index("ix_ai_runs_input_hash", "input_hash"),)  # D23 idempotency lookups

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[AiRunType] = mapped_column(ai_run_type_enum, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str | None] = mapped_column(String(128))
    input_payload: Mapped[dict | None] = mapped_column(JSONB)
    output_payload: Mapped[dict | None] = mapped_column(JSONB)
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 6))
    status: Mapped[str | None] = mapped_column(String(32))  # under-specified → String (e.g. success/failed)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created_at()


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_message_ids: Mapped[list | None] = mapped_column(JSONB)
    input_payload: Mapped[dict | None] = mapped_column(JSONB)
    expected_output: Mapped[dict | None] = mapped_column(JSONB)
    actual_output: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[EvaluationResult] = mapped_column(
        evaluation_result_enum, nullable=False, server_default=text("'pending'")
    )
    score: Mapped[float | None] = mapped_column(Float)
    comments: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "actor_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[AuditAction] = mapped_column(audit_action_enum, nullable=False)
    entity_type: Mapped[AuditEntityType] = mapped_column(audit_entity_type_enum, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before_value: Mapped[dict | None] = mapped_column(JSONB)
    after_value: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = _created_at()
