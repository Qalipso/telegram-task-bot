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

PRIORITY_LABELS = {"low": "Низкий", "medium": "Средний", "high": "Высокий", "critical": "Срочно"}
PRIORITY_DOT = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
_TYPE_LABELS = {
    "task": "Задача", "request": "Запрос", "reminder": "Напоминание",
    "idea": "Идея", "knowledge": "Заметка", "issue": "Проблема",
}
# Human labels for the AI's missing-field flags (keeps the card professional, not techy).
_MISSING_LABELS = {
    "assignee": "ответственный", "due_date": "срок", "priority": "приоритет", "title": "название",
}


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + ELLIPSIS


def format_candidate_text(candidate: dict) -> str:
    """CandidateOut dict -> a clean card body. Plain text (no markdown — the bot sends cards
    without parse_mode). Emoji appear only as status markers (⚠ warnings)."""
    cid = candidate.get("id")
    ctype = candidate.get("candidate_type", "item")
    type_label = _TYPE_LABELS.get(ctype, ctype.capitalize())
    title = _truncate(candidate.get("title"), TITLE_MAX_LEN) or "(без названия)"
    summary = _truncate(candidate.get("summary"), SUMMARY_MAX_LEN)
    priority = candidate.get("priority") or ""
    due_raw = candidate.get("due_date") or ""
    due = due_raw[:10] if due_raw else ""

    # Header + title + (optional) summary
    lines = [f"{type_label} · #{cid}", title]
    if summary and summary.lower() != (candidate.get("title") or "").lower():
        lines.append(summary)

    # One compact meta line: priority · due · assignee (only the parts we have), with colour/helpers
    meta: list[str] = []
    if priority:
        meta.append(f"{PRIORITY_DOT.get(priority, '⚪')} {PRIORITY_LABELS.get(priority, priority)}")
    if due:
        meta.append(f"📅 {due}")
    ambiguous = bool(candidate.get("assignee_ambiguous"))
    if not ambiguous:
        if (candidate.get("assignee_count") or 0) >= 1:
            names = candidate.get("assignees") or []
            meta.append("👤 " + (", ".join(names) if names else "назначено"))
        else:
            meta.append("👤 без ответственного")
    if meta:
        lines.append("")
        lines.append(" · ".join(meta))

    # Warnings last, as status markers
    if ambiguous:
        mentions = candidate.get("unresolved_mentions") or []
        lines.append("⚠ Кто из: " + (", ".join(mentions) if mentions else "?"))
    missing = candidate.get("missing_fields") or []
    if missing:
        lines.append("⚠ Не хватает: " + ", ".join(_MISSING_LABELS.get(m, m) for m in missing))
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

    # Approve is shown for any actionable (non-terminal) candidate that has a resolved assignee
    # and no blocking missing fields. "edited" is actionable — it just means an assignee was set.
    _ACTIONABLE = {"new", "edited", "needs_review"}
    ready = status in _ACTIONABLE and not missing and assignee_count >= 1 and not ambiguous
    if ready:
        rows.append([_btn("🌿 Одобрить", "approve", cid)])

    # Assignee row — always show so the admin can change/add an assignee at any time.
    if ambiguous:
        rows.append([_btn("🐒 Кто?", "who", cid), _btn("🐘 Назначить", "assign", cid)])
    elif assignee_count == 0:
        rows.append([_btn("🐘 Назначить", "assign", cid)])
    else:
        rows.append([_btn("🐘 Сменить", "assign", cid)])

    rows.append([_btn("🦫 Изменить", "edit", cid), _btn("🍂 Отклонить", "reject", cid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_PRIORITY_PICKER_PAIRS = [
    [("🔴 Срочно", "critical"), ("🟠 Высокий", "high")],
    [("🟡 Средний", "medium"), ("🟢 Низкий", "low")],
]


def render_edit_menu(candidate: dict) -> CardMessage:
    """Edit submenu: priority picker + instructions for /title and /due."""
    cid = int(candidate["id"])
    title = _truncate(candidate.get("title"), 60) or "(без названия)"
    priority = candidate.get("priority") or ""
    priority_label = PRIORITY_LABELS.get(priority, priority or "—")
    due = (candidate.get("due_date") or "—")[:10]

    text = (
        f"Редактирование · #{cid}\n"
        f"{title}\n\n"
        f"Приоритет: {priority_label}   Срок: {due}\n\n"
        "Выбери приоритет ниже, либо отправь боту:\n"
        f"/title {cid} новое название\n"
        f"/due {cid} ГГГГ-ММ-ДД"
    )
    rows: list[list[InlineButton]] = []
    for pair in _PRIORITY_PICKER_PAIRS:
        rows.append([InlineButton(label, f"eprio{CB_SEP}{cid}{CB_SEP}{val}") for label, val in pair])
    rows.append([InlineButton("🐾 К задаче", f"eback{CB_SEP}{cid}")])
    return CardMessage(candidate_id=cid, text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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
