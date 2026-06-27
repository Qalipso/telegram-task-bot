"""Pure callback dispatch (no aiogram import — host-testable).

Maps an untrusted Telegram callback_data string + the tapper's telegram_user_id to the right
handler, returning a HandlerResult/CardMessage. The thin aiogram adapter (telegram_app.py) calls
this inside asyncio.to_thread with a fresh DB Session + ApiClient, then renders the result.

Security (spec §6.4): every action routes through handlers that run authz.authorize_tapper and
re-fetch the candidate by id before mutating — callback_data is never trusted. The 'open' branch
(digest/notify → single-item card) authorizes BEFORE any API I/O. Malformed data is caught and
returned as a calm denied result so the adapter always answers the callback and never crashes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from aiwip_bot import authz, cards, handlers

_INVALID_BUTTON = "That button is no longer valid."


def _denied(text: str) -> handlers.HandlerResult:
    return handlers.HandlerResult(text=text, did_act=False)


def _open(db: Session, api, telegram_user_id: int, candidate_id: int) -> handlers.HandlerResult:
    # Authorize BEFORE any API I/O so a denied tapper triggers zero candidate fetch.
    decision = authz.authorize_tapper(db, telegram_user_id)
    if not decision.allowed:
        return _denied(decision.reason or _INVALID_BUTTON)
    envelope = api.get_candidate(candidate_id)
    candidate = envelope["candidate"] if "candidate" in envelope else envelope
    return handlers.HandlerResult(
        text=f"Candidate #{candidate_id}", card=cards.render_card(candidate), did_act=False
    )


def dispatch_callback(db: Session, api, data: str, telegram_user_id: int) -> handlers.HandlerResult:
    """Route one callback_data string to its handler. Never raises on bad input."""
    # "pick:<candidate_id>:<assignee_id>" — different arity, route before parse_callback.
    if data.startswith("pick" + cards.CB_SEP):
        try:
            candidate_id, assignee_id = handlers.parse_pick_callback(data)
        except ValueError:
            return _denied(_INVALID_BUTTON)
        return handlers.handle_pick_assignee(db, api, telegram_user_id, candidate_id, assignee_id)

    # "eprio:<candidate_id>:<priority>" — set priority inline.
    if data.startswith("eprio" + cards.CB_SEP):
        try:
            candidate_id, priority = handlers.parse_eprio_callback(data)
        except ValueError:
            return _denied(_INVALID_BUTTON)
        return handlers.handle_set_priority(db, api, telegram_user_id, candidate_id, priority)

    try:
        action, candidate_id = handlers.parse_callback(data)
    except ValueError:
        return _denied(_INVALID_BUTTON)

    if action == "approve":
        return handlers.handle_approve(db, api, telegram_user_id, candidate_id)
    if action == "reject":
        return handlers.handle_reject(db, api, telegram_user_id, candidate_id)
    if action == "assign":
        return handlers.handle_assign(db, api, telegram_user_id, candidate_id)
    if action == "who":
        return handlers.handle_who(db, api, telegram_user_id, candidate_id)
    if action == "edit":
        return handlers.handle_edit(db, api, telegram_user_id, candidate_id)
    if action == "open":
        return _open(db, api, telegram_user_id, candidate_id)
    if action == "eback":
        return _open(db, api, telegram_user_id, candidate_id)
    return _denied(_INVALID_BUTTON)
