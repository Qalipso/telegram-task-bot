"""Render a CandidateOut JSON dict to a Telegram card: message text + inline keyboard.

The bot reads candidate JSON (a dict) over the API — it does NOT import the Pydantic schema.
This module is pure (no network), so it is fully unit-testable.

Iron Law: this module renders only. It never decides to approve; it offers buttons a human taps.
"""
from __future__ import annotations

from dataclasses import dataclass

TITLE_MAX_LEN = 120
SUMMARY_MAX_LEN = 280
ELLIPSIS = "…"


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + ELLIPSIS


def _confidence_pct(value: float | None) -> str:
    return f"{round(value * 100)}%" if isinstance(value, (int, float)) else "—"


def format_candidate_text(candidate: dict) -> str:
    """CandidateOut dict -> human-readable card body. Pure string; no side effects."""
    cid = candidate.get("id")
    ctype = candidate.get("candidate_type", "item")
    title = _truncate(candidate.get("title"), TITLE_MAX_LEN) or "(no title)"
    summary = _truncate(candidate.get("summary"), SUMMARY_MAX_LEN)
    priority = candidate.get("priority") or "—"
    due = candidate.get("due_date") or "—"
    status = candidate.get("status", "")
    task_conf = _confidence_pct(candidate.get("task_confidence"))

    lines = [
        f"📥 {ctype.capitalize()} #{cid}",
        f"*{title}*",
    ]
    if summary:
        lines.append(summary)
    lines.append(f"Priority: {priority}   Due: {due}   Confidence: {task_conf}")

    missing = candidate.get("missing_fields") or []
    if missing:
        lines.append("⚠ Missing: " + ", ".join(missing))

    if candidate.get("assignee_ambiguous"):
        mentions = candidate.get("unresolved_mentions") or []
        who = ", ".join(mentions) if mentions else "?"
        lines.append(f"❓ Ambiguous assignee — who is: {who}")
    elif (candidate.get("assignee_count") or 0) == 0:
        mentions = candidate.get("unresolved_mentions") or []
        if mentions:
            lines.append("👤 Unassigned — mentioned: " + ", ".join(mentions))
        else:
            lines.append("👤 Unassigned")

    if status and status != "new":
        lines.append(f"_status: {status}_")
    return "\n".join(lines)


# --- inline keyboard ---------------------------------------------------------

CB_SEP = ":"  # callback_data format:  "<action><CB_SEP><candidate_id>"  (e.g. "approve:42")


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineButton]]


def encode_callback(action: str, candidate_id: int) -> str:
    return f"{action}{CB_SEP}{candidate_id}"


def _btn(text: str, action: str, candidate_id: int) -> InlineButton:
    return InlineButton(text=text, callback_data=encode_callback(action, candidate_id))


def build_keyboard(candidate: dict) -> InlineKeyboardMarkup:
    """Status/assignee-driven inline keyboard. NEVER includes an 'Approve all' button (§6.2)."""
    cid = int(candidate["id"])
    status = candidate.get("status", "")
    missing = candidate.get("missing_fields") or []
    assignee_count = candidate.get("assignee_count") or 0
    ambiguous = bool(candidate.get("assignee_ambiguous"))

    rows: list[list[InlineButton]] = []

    # A bare one-tap Approve is offered ONLY for a clean, ready candidate (§6.2 low-friction band):
    # status == new AND no missing fields AND exactly one resolved assignee.
    ready = status == "new" and not missing and assignee_count == 1 and not ambiguous
    if ready:
        rows.append([_btn("✅ Approve", "approve", cid)])

    # Assignee disambiguation / assignment row (§6.1 bot UX).
    if ambiguous:
        rows.append([_btn("❓ Who?", "who", cid)])
    elif assignee_count == 0:
        rows.append([_btn("👤 Assign…", "assign", cid)])

    # Reject is always available; it is never destructive of an approved item (server-guarded).
    rows.append([_btn("✏️ Edit", "edit", cid), _btn("🗑 Reject", "reject", cid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dataclass(frozen=True)
class CardMessage:
    candidate_id: int
    text: str
    reply_markup: InlineKeyboardMarkup


def render_card(candidate: dict) -> CardMessage:
    return CardMessage(
        candidate_id=int(candidate["id"]),
        text=format_candidate_text(candidate),
        reply_markup=build_keyboard(candidate),
    )
