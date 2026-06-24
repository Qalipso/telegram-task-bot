"""Prompt template + OpenAI Structured-Outputs JSON schema (llm-extraction-spec.md).

Bump PROMPT_VERSION on any change — it is stored on every ai_run and candidate so quality
changes are attributable (the single most important eval lever).
"""
from __future__ import annotations

import datetime as dt

PROMPT_VERSION = "v3"

SYSTEM = """You extract WORK ITEMS from a window of team chat messages.

Capture every message that represents work the team should track, across these five types:
- task: something concrete to be done ("ship the report", "fix the login bug").
- request: someone asks for something to be done or reviewed ("can someone review X?",
  "please take a look at Y") — count it even when no owner is named.
- reminder: a time-bound nudge ("don't forget the standup at 10am", "remember to send the invoice").
- idea: a suggestion or proposal worth keeping ("what if we added dark mode?").
- knowledge: a decision, fact, or piece of information worth documenting for later.

Be inclusive across these five types. A clear request, reminder, or idea IS a work item even if it
has no assignee and no due date — do NOT drop it; instead leave that field null and add the missing
piece ("assignee", "due_date", "priority") to missing_fields. Use a lower item confidence for softer
or implicit signals so a human can review them.

But IGNORE pure social chatter, greetings, reactions, jokes, emoji-only messages, and
gibberish/keyboard-mash — for a window that is only that, return an empty candidates list. A false
work item from real noise is still bad; the goal is to catch genuine signals, not to invent them.

Priority: one of "high", "medium", or "low" (shown to users as High / Mid / Low), or null. Use "high"
for urgent, blocking, time-critical, or business-critical work; "low" for minor or clearly non-urgent
work; "medium" otherwise. If priority is genuinely unclear from the message, use null.
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
                        "priority": {"type": ["string", "null"], "enum": ["high", "medium", "low", None]},
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
