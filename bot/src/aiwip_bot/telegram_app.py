"""Thin aiogram v3 adapter — the live runtime glue (the ONLY module importing aiogram).

Wires the pure, already-tested logic to live Telegram:
  * group text   -> ingest.record_from_update + ingest.ingest_message (configure-gated, debounced)
  * bot added/removed -> onboarding prompt / clear config
  * callback taps -> dispatch.dispatch_callback (authz + handlers) -> edit message / answer
  * /start, /link <code>  (link redeems POST /api/auth/telegram/redeem with the tapper's id)
  * background bot.notify consumer -> render the candidate card -> send to BOT_REVIEW_CHAT_ID

Concurrency rules (per design review):
  - Every SYNC call (DB Session, httpx ApiClient, blocking Redis brpop) is offloaded via
    asyncio.to_thread so the event loop never blocks.
  - A SQLAlchemy Session and an httpx ApiClient are NOT thread-safe to share — each offloaded
    function builds and closes its own. Redis (get_redis) IS a shared thread-safe pool — reused.
  - dequeue_notify uses a small FINITE timeout so the worker thread returns regularly and the
    consumer task is cancellable at the await boundary on shutdown (never timeout=0).
  - Cards are sent as PLAIN text (no parse_mode) so arbitrary candidate text can't trigger a
    Telegram markdown-parse 400.

This module is host-untestable (aiogram is absent from the host venv); it is verified by building
the bot image and running the live runbook. All logic it calls is host-unit-tested.
"""
from __future__ import annotations

import asyncio
import contextlib

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from aiwip_core.db import get_sessionmaker
from aiwip_core.logging import get_logger
from aiwip_core import queue

from . import cards, dispatch, ingest, onboarding, state
from .api_client import ApiClient, ConversationalApiError

logger = get_logger("aiwip.bot.telegram_app")

_NOTIFY_TIMEOUT_SECONDS = 5  # finite so the consumer thread returns + stays cancellable


# --------------------------------------------------------------------------- sync helpers (to_thread)
def _new_api(settings) -> ApiClient:
    return ApiClient(settings.bot_api_base, settings.bot_admin_email, settings.bot_admin_password)


def _message_to_update(message: Message) -> dict:
    """aiogram Message -> the raw-update dict shape ingest.record_from_update expects."""
    frm = message.from_user
    return {
        "message": {
            "message_id": message.message_id,
            "date": int(message.date.timestamp()),
            "chat": {"id": message.chat.id},
            "from": ({"id": frm.id, "username": frm.username, "first_name": frm.first_name} if frm else {}),
            "text": message.text,
            "reply_to_message": (
                {"message_id": message.reply_to_message.message_id} if message.reply_to_message else None
            ),
        }
    }


def _capture(settings, update: dict) -> tuple[str, dict | None]:
    """Configure-gate then buffer. Returns ('onboard', prompt) for an unconfigured chat, else
    ('captured', None). Runs in a worker thread (Redis is shared/thread-safe)."""
    chat_id = update["message"]["chat"]["id"]
    if not state.is_chat_configured(chat_id):
        return ("onboard", onboarding.on_bot_added_to_group(chat_id))
    record = ingest.record_from_update(update)
    ingest.ingest_message(chat_id, record, debounce_seconds=settings.bot_debounce_seconds)
    return ("captured", None)


def _dispatch(settings, data: str, telegram_user_id: int):
    """Build a fresh Session + ApiClient (not thread-shareable), run the pure dispatch, clean up."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            return dispatch.dispatch_callback(db, api, data, telegram_user_id)
    finally:
        api.close()


def _notify_card(settings, candidate_id: int):
    api = _new_api(settings)
    try:
        envelope = api.get_candidate(candidate_id)
        candidate = envelope["candidate"] if "candidate" in envelope else envelope
        return cards.render_card(candidate)
    except ConversationalApiError as exc:
        logger.warning("notify fetch failed for #%s: %s", candidate_id, exc.message)
        return None
    finally:
        api.close()


def _redeem(settings, code: str, telegram_user_id: int) -> tuple[int, str]:
    """POST /api/auth/telegram/redeem (unauthenticated). Returns (status_code, detail)."""
    try:
        resp = httpx.post(
            f"{settings.bot_api_base}/api/auth/telegram/redeem",
            json={"code": code, "telegram_user_id": telegram_user_id},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return (0, f"could not reach API: {exc}")
    try:
        detail = resp.json().get("detail") or resp.json().get("status") or ""
    except Exception:  # noqa: BLE001
        detail = ""
    return (resp.status_code, str(detail))


def _redeem_message(status_code: int, detail: str) -> str:
    if status_code == 200:
        return "✅ Аккаунт привязан. Теперь твои нажатия авторизуются."
    if status_code == 429:
        return "Слишком много попыток. Подожди немного и попробуй снова."
    if status_code == 400:
        return f"Код недействителен или истёк ({detail}). Сгенерируй новый в веб-консоли."
    return f"Не удалось привязать ({status_code}). {detail}"


# --------------------------------------------------------------------------- aiogram rendering
def _to_markup(markup: cards.InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row]
            for row in markup.inline_keyboard
        ]
    )


def _onboard_markup(prompt: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=a["label"], callback_data=a["action"])] for a in prompt["actions"]
        ]
    )


async def _send_card(bot: Bot, chat_id: int, card: cards.CardMessage) -> None:
    await bot.send_message(chat_id, card.text, reply_markup=_to_markup(card.reply_markup))


# --------------------------------------------------------------------------- background consumer
async def _notify_consumer(bot: Bot, settings) -> None:
    """Drain aiwip:bot:notify and send each candidate's card to the review chat. One surfacing path
    for MVP (the digest loop is intentionally NOT run — nothing stages candidates, and running both
    would double-surface)."""
    while True:
        try:
            msg = await asyncio.to_thread(queue.dequeue_notify, _NOTIFY_TIMEOUT_SECONDS)
            if not msg:
                continue
            card = await asyncio.to_thread(_notify_card, settings, msg["candidate_id"])
            if card is not None:
                await _send_card(bot, settings.bot_review_chat_id, card)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 — a bad notify must not kill the consumer
            logger.exception("notify consumer error")
            await asyncio.sleep(1)


# --------------------------------------------------------------------------- wiring
def _register(dp: Dispatcher, bot: Bot, settings) -> None:
    @dp.message(Command("start"))
    async def _start(message: Message) -> None:
        await message.answer(
            "Привет! Я превращаю сообщения в рабочем чате в задачи на ревью.\n"
            "Добавь меня в группу (я должен быть админом, privacy mode выключен).\n"
            "Чтобы привязать свой аккаунт-админ: /link <код> — код выдаёт веб-консоль."
        )

    @dp.message(Command("link"))
    async def _link(message: Message, command: CommandObject) -> None:
        code = (command.args or "").strip()
        if not code:
            await message.answer("Использование: /link <код> (получи код в веб-консоли).")
            return
        status_code, detail = await asyncio.to_thread(_redeem, settings, code, message.from_user.id)
        await message.answer(_redeem_message(status_code, detail))

    @dp.my_chat_member()
    async def _membership(event: ChatMemberUpdated) -> None:
        status = event.new_chat_member.status
        chat_id = event.chat.id
        if status in ("member", "administrator"):
            prompt = await asyncio.to_thread(onboarding.on_bot_added_to_group, chat_id)
            if prompt:
                await bot.send_message(chat_id, prompt["text"], reply_markup=_onboard_markup(prompt))
        elif status in ("left", "kicked"):
            await asyncio.to_thread(onboarding.on_bot_removed_from_group, chat_id)

    @dp.callback_query(F.data == "choose_destination")
    async def _choose_destination(cb: CallbackQuery) -> None:
        await asyncio.to_thread(
            onboarding.handle_destination_choice, cb.message.chat.id, destination="internal"
        )
        with contextlib.suppress(Exception):
            await cb.message.edit_text("Готово — я начал ловить задачи в этом чате.")
        await cb.answer("Настроено")

    @dp.callback_query()
    async def _callback(cb: CallbackQuery) -> None:
        result = await asyncio.to_thread(_dispatch, settings, cb.data or "", cb.from_user.id)
        if result.card is not None:
            with contextlib.suppress(Exception):
                await cb.message.edit_text(result.card.text, reply_markup=_to_markup(result.card.reply_markup))
        await cb.answer((result.text or "")[:200])

    @dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
    async def _group_text(message: Message) -> None:
        kind, prompt = await asyncio.to_thread(_capture, settings, _message_to_update(message))
        if kind == "onboard" and prompt:
            await message.answer(prompt["text"], reply_markup=_onboard_markup(prompt))


async def _amain(settings) -> None:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    _register(dp, bot, settings)
    notify_task = asyncio.create_task(_notify_consumer(bot, settings))
    logger.info("bot polling started; confirm cards go to chat %s", settings.bot_review_chat_id)
    try:
        await dp.start_polling(bot, polling_timeout=settings.bot_getupdates_timeout)
    finally:
        notify_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notify_task
        await bot.session.close()


def run_app(settings) -> None:
    """Entry point called by main.run() when a token is configured. Blocks until the process stops."""
    if not settings.telegram_bot_token:
        raise RuntimeError("run_app requires TELEGRAM_BOT_TOKEN")
    if not settings.bot_review_chat_id:
        raise RuntimeError(
            "BOT_REVIEW_CHAT_ID is required when TELEGRAM_BOT_TOKEN is set "
            "(the admin DM / private review chat where confirm cards are sent)."
        )
    asyncio.run(_amain(settings))
