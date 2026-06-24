"""Prompt template + OpenAI Structured-Outputs JSON schema (llm-extraction-spec.md).

Bump PROMPT_VERSION on any change — it is stored on every ai_run and candidate so quality
changes are attributable (the single most important eval lever).
"""
from __future__ import annotations

import datetime as dt

PROMPT_VERSION = "v1"

SYSTEM = """You extract actionable WORK ITEMS from a window of team chat messages.

Precision over recall: a FALSE work item is worse than a missed weak signal. If a window is just
chatter, return an empty candidates list.

Active types: task, request, reminder, idea, knowledge.
Priority: one of critical, high, medium, low, or null. Use "critical" ONLY for an explicit blocker,
urgency, risk of failure, or business-critical action. If priority is not stated and unclear, use null.
Assignees: choose ONLY from the provided assignee list (match by username/alias/name). Multiple are
allowed. If you cannot determine an assignee, leave the array empty and add "assignee" to missing_fields.
Due date: convert relative dates ("Friday", "tomorrow") into an ISO-8601 calendar date using the given
current UTC time. If no deadline is stated, use null.
For each candidate set per-field confidence in [0,1] (item, context, assignee, priority, due_date).
Reference messages by their [id] from the window in source_message_ids (the anchor) and
supporting_message_ids (extra evidence).

Return ONLY the structured JSON. Do not create work items — only candidates."""

JSON_SCHEMA = {
    "name": "work_item_candidates",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates", "context_summary", "context_confidence"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "type", "title", "summary", "priority", "due_date", "assignees",
                        "source_message_ids", "supporting_message_ids", "reasoning_summary",
                        "missing_fields", "confidence",
                    ],
                    "properties": {
                        "type": {"type": "string", "enum": ["task", "request", "reminder", "idea", "knowledge"]},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "priority": {"type": ["string", "null"], "enum": ["critical", "high", "medium", "low", None]},
                        "due_date": {"type": ["string", "null"]},
                        "assignees": {"type": "array", "items": {"type": "string"}},
                        "source_message_ids": {"type": "array", "items": {"type": "integer"}},
                        "supporting_message_ids": {"type": "array", "items": {"type": "integer"}},
                        "reasoning_summary": {"type": "string"},
                        "missing_fields": {"type": "array", "items": {"type": "string"}},
                        "confidence": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["item", "context", "assignee", "priority", "due_date"],
                            "properties": {
                                "item": {"type": "number"},
                                "context": {"type": "number"},
                                "assignee": {"type": "number"},
                                "priority": {"type": "number"},
                                "due_date": {"type": "number"},
                            },
                        },
                    },
                },
            },
            "context_summary": {"type": "string"},
            "context_confidence": {"type": "number"},
        },
    },
}


def build_user(ctx, assignees, now_utc: dt.datetime) -> str:
    lines = [f"Current UTC time: {now_utc.isoformat()}", "", "Available assignees:"]
    if assignees:
        for a in assignees:
            keys = [k for k in [a.telegram_username, *(a.aliases or [])] if k]
            lines.append(f"- {a.display_name or a.telegram_username} (match: {', '.join(keys) or 'n/a'})")
    else:
        lines.append("- (none configured)")
    lines += ["", "Conversation window (newest last):"]
    for cm in ctx.messages:
        reply = f" [reply to {cm.reply_to}]" if cm.reply_to else ""
        lines.append(f"[{cm.external_message_id}] {cm.sent_at_utc} @{cm.sender or '?'}:{reply} {cm.text or ''}")
    return "\n".join(lines)


def build_messages(ctx, assignees, now_utc: dt.datetime) -> tuple[str, str]:
    return SYSTEM, build_user(ctx, assignees, now_utc)
