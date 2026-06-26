"""Callback handlers for the confirm loop (approve / reject / assign / who / pick / edit).

Every handler runs the same security guard (design spec §6.4):
  1. authorize the tapper against the DB (authz.authorize_tapper);
  2. re-fetch the candidate by id (callback_data is UNTRUSTED) and confirm it is still actionable;
  3. only THEN call the existing, admin-gated API endpoint.

Iron Law: the bot NEVER calls /approve on its own. handle_approve runs only because a human tapped
the Approve button, and it still goes through the human-gated POST /api/candidates/{id}/approve.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aiwip_bot import authz, cards

# Candidate statuses that are already settled — any approve/reject on them is a no-op (replay guard).
_TERMINAL_STATUSES = {"approved", "rejected"}

_ASK_ADMIN = "You are not authorized to do this. Please ask an admin."


@dataclass(frozen=True)
class HandlerResult:
    text: str                              # what to show the tapper (toast / message)
    card: cards.CardMessage | None = None  # optional refreshed card to re-render
    did_act: bool = False                  # True iff an API mutation actually happened


def parse_callback(data: str) -> tuple[str, int]:
    """Parse "<action>:<candidate_id>" -> (action, candidate_id). Raises ValueError on garbage."""
    if not data or cards.CB_SEP not in data:
        raise ValueError(f"malformed callback_data: {data!r}")
    action, _, rest = data.partition(cards.CB_SEP)
    if not action:
        raise ValueError(f"malformed callback_data: {data!r}")
    return action, int(rest)  # int() raises ValueError on non-numeric id


def parse_pick_callback(data: str) -> tuple[int, int]:
    """Parse "pick:<candidate_id>:<assignee_id>" -> (candidate_id, assignee_id)."""
    parts = data.split(cards.CB_SEP)
    if len(parts) != 3 or parts[0] != "pick":
        raise ValueError(f"malformed pick callback_data: {data!r}")
    return int(parts[1]), int(parts[2])


def _guard(db: Session, api, telegram_user_id: int, candidate_id: int):
    """Shared §6.4 guard.

    On deny, returns (HandlerResult, None). On allow, returns (AuthDecision, candidate_dict)
    where candidate_dict is the freshly re-fetched candidate (callback_data is NOT trusted)."""
    decision = authz.authorize_tapper(db, telegram_user_id)
    if not decision.allowed:
        return HandlerResult(text=decision.reason or _ASK_ADMIN, did_act=False), None
    envelope = api.get_candidate(candidate_id)        # re-fetch by id — never trust the button
    candidate = envelope["candidate"] if "candidate" in envelope else envelope
    return decision, candidate


def handle_approve(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.approve_candidate(candidate_id)               # human-gated endpoint; bot never auto-approves
    return HandlerResult(text=f"Approved #{candidate_id}.", did_act=True)


def handle_reject(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.reject_candidate(candidate_id)
    return HandlerResult(text=f"Rejected #{candidate_id}.", did_act=True)


def _assignee_picker(api, candidate_id: int) -> cards.InlineKeyboardMarkup:
    """One choose-button per active assignee. callback_data: "pick:<candidate_id>:<assignee_id>"."""
    rows: list[list[cards.InlineButton]] = []
    for a in api.list_assignees(active=True):
        label = a.get("display_name") or a.get("telegram_username") or f"#{a['id']}"
        data = f"pick{cards.CB_SEP}{candidate_id}{cards.CB_SEP}{a['id']}"
        rows.append([cards.InlineButton(text=label, callback_data=data)])
    return cards.InlineKeyboardMarkup(inline_keyboard=rows)


def handle_assign(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    picker = _assignee_picker(api, candidate_id)
    card = cards.CardMessage(candidate_id=candidate_id, text="Who is responsible?", reply_markup=picker)
    return HandlerResult(text="Pick an assignee.", card=card, did_act=False)


# 'Who?' (ambiguity) and 'Assign…' (zero match) present the same picker.
handle_who = handle_assign


def handle_pick_assignee(
    db: Session, api, telegram_user_id: int, candidate_id: int, assignee_id: int
) -> HandlerResult:
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    if candidate.get("status") in _TERMINAL_STATUSES:
        return HandlerResult(text="This candidate is already settled — no action taken.", did_act=False)
    api.patch_candidate(candidate_id, {"assignee_ids": [assignee_id]})
    return HandlerResult(text=f"Assigned #{candidate_id}.", did_act=True)


def handle_edit(db: Session, api, telegram_user_id: int, candidate_id: int) -> HandlerResult:
    # Free-text title/summary editing is a documented fast-follow (spec §15). For MVP, authorize
    # then direct the admin to the web console for full edits.
    guard, candidate = _guard(db, api, telegram_user_id, candidate_id)
    if candidate is None:
        return guard  # denied
    return HandlerResult(
        text=f"Edit #{candidate_id} fields in the web console for now.", did_act=False
    )
