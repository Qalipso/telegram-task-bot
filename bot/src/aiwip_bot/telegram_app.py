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

from . import admin, cards, dispatch, ingest, onboarding, state
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
    """Configure-gate + pause-gate then buffer.
    Returns ('onboard', prompt), ('paused', None), or ('captured', None).
    Runs in a worker thread (Redis is shared/thread-safe)."""
    chat_id = update["message"]["chat"]["id"]
    if not state.is_chat_configured(chat_id):
        return ("onboard", onboarding.on_bot_added_to_group(chat_id))
    if state.is_chat_paused(chat_id):
        return ("paused", None)  # admin paused capture — silently discard
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


def _admin_check(db, telegram_user_id: int) -> bool:
    """Return True iff the tapper is a linked admin (same authz as card callbacks)."""
    from aiwip_bot import authz as _authz
    decision = _authz.authorize_tapper(db, telegram_user_id)
    return decision.allowed


def _dashboard_stats(work_items: list[dict], candidates: list[dict]) -> dict:
    """Compute the six dashboard counters from the full work-item + candidate lists.
    Math lives in admin.dashboard_counters (aiogram-free + unit-tested); we add the chat count."""
    return {"chats": len(state.list_configured_chats()), **admin.dashboard_counters(work_items, candidates)}


def _admin_menu(settings, telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    """Dashboard: the whole-system snapshot. Fetches work items + candidates once."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
        work_items = api.list_work_items()
        candidates = api.list_candidates(limit=500)
        stats = _dashboard_stats(work_items, candidates)
        return admin.dashboard_text(stats), _admin_markup(admin.dashboard_buttons())
    finally:
        api.close()


def _remap_chat_titles(work_items: list[dict], title_map: dict[int, str]) -> None:
    """Replace each item's API-supplied (synthetic) chat title with the real Telegram name
    from Redis when we have it. Mutates in place."""
    for w in work_items:
        cid = w.get("source_chat_id")
        if cid in title_map:
            w["source_chat_title"] = title_map[cid]


def _admin_tasks(settings, telegram_user_id: int, *, closed: bool = False) -> tuple[str, InlineKeyboardMarkup] | None:
    """Active (or closed) task list, grouped by priority, with assignee + source chat."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
            title_map = _chat_title_map(db)
        work_items = api.list_work_items()
        _remap_chat_titles(work_items, title_map)
        return admin.tasks_text(work_items, closed=closed), _admin_markup(admin.tasks_buttons(closed=closed))
    finally:
        api.close()


def _admin_review(settings, telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup, list] | None:
    """Review queue: pending candidates as actionable cards. Returns (text, back, cards)."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
        candidates = api.list_candidates(limit=100)
        pending = [c for c in candidates if c.get("status") in admin.PENDING_CAND_STATUSES]
        rendered = []
        for c in pending[:10]:
            try:
                envelope = api.get_candidate(c["id"])
                cand = envelope["candidate"] if "candidate" in envelope else envelope
                rendered.append(cards.render_card(cand))
            except ConversationalApiError:
                pass
        return admin.review_text(candidates), _admin_markup(admin.review_buttons()), rendered
    finally:
        api.close()


def _admin_integrations(telegram_user_id: int, *, clear: bool = False) -> tuple[str, InlineKeyboardMarkup] | None:
    with get_sessionmaker()() as db:
        if not _admin_check(db, telegram_user_id):
            return None
    if clear:
        state.clear_admin_webhook()
    url = state.get_admin_webhook()
    return admin.integrations_text(url), _admin_markup(admin.integrations_buttons(url))


def _chat_title_map(db) -> dict[int, str]:
    """Return {external_chat_id: title} for every configured chat.

    Priority: (1) Redis config 'title' field (real Telegram name, set at onboarding),
    (2) DB Chat.title, (3) str(chat_id) fallback.
    """
    from aiwip_core.models import Chat as _Chat
    from sqlalchemy import select as _select
    ids = state.list_configured_chats()
    if not ids:
        return {}
    # Start with Redis-stored titles (set when user completes onboarding)
    result: dict[int, str] = {}
    for cid in ids:
        cfg = state.get_chat_config(cid)
        if cfg and cfg.get("title"):
            result[cid] = cfg["title"]
    # Fill missing titles from DB (may have real title stored by other paths)
    missing = [cid for cid in ids if cid not in result]
    if missing:
        rows = db.execute(_select(_Chat).where(_Chat.external_chat_id.in_(missing))).scalars().all()
        for r in rows:
            t = r.title or ""
            # DB stores synthetic "chat {id}" titles — skip those
            if t and not t.startswith("chat "):
                result[r.external_chat_id] = t
    for cid in ids:
        result.setdefault(cid, str(cid))
    return result


def _chats_with_titles(db) -> list[tuple[int, str]]:
    m = _chat_title_map(db)
    return [(cid, m[cid]) for cid in m]


def _admin_chats(telegram_user_id: int, *, _backfill_titles: dict[int, str] | None = None) -> tuple[str, InlineKeyboardMarkup] | None:
    with get_sessionmaker()() as db:
        if not _admin_check(db, telegram_user_id):
            return None
        # If caller supplied titles fetched from Telegram API (async), backfill Redis now
        if _backfill_titles:
            for cid, title in _backfill_titles.items():
                cfg = state.get_chat_config(cid) or {}
                if not cfg.get("title") and title:
                    state.set_chat_config(cid, destination=cfg.get("destination", "internal"), title=title)
        chats = _chats_with_titles(db)
    return admin.chats_text(chats), _admin_markup(admin.chats_buttons(chats))


def _admin_pause_resume(settings, telegram_user_id: int, chat_id: int, *, pause: bool) -> tuple[str, InlineKeyboardMarkup] | None:
    """Pause/resume a chat, then re-render its detail screen (where the button lives)."""
    with get_sessionmaker()() as db:
        if not _admin_check(db, telegram_user_id):
            return None
        if pause:
            state.pause_chat(chat_id)
        else:
            state.resume_chat(chat_id)
    return _admin_chat_detail(settings, telegram_user_id, chat_id)


def _admin_sync(settings, telegram_user_id: int, chat_id: int) -> str | None:
    """Enqueue a manual sync job for the chat. Returns a status string or None if not authorized."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
        result = api.sync_chat(chat_id)
        q_len = result.get("queue_length", "?")
        return f"🔄 Синхронизация поставлена в очередь (позиция {q_len}).\nКандидаты появятся через ~60 сек."
    except Exception as exc:
        logger.warning("admin sync failed: %s", exc)
        return f"Ошибка при запуске синхронизации: {exc}"
    finally:
        api.close()


def _last_sync_for(api, external_chat_id: int) -> str | None:
    """Look up last successful sync timestamp (ISO) for a chat by its external id."""
    try:
        status = api.sync_status()
    except Exception:  # noqa: BLE001 — sync state is best-effort decoration
        return None
    for s in status.get("states", []):
        if s.get("external_chat_id") == external_chat_id:
            return s.get("last_successful_sync_at")
    return None


def _admin_chat_detail(settings, telegram_user_id: int, chat_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    """Per-chat dashboard: task counts (from this chat) + last sync + actions."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
            title_map = _chat_title_map(db)
        title = title_map.get(chat_id, str(chat_id))
        work_items = api.list_work_items()
        stats = admin.chat_task_stats(work_items, chat_id)
        last_sync = _last_sync_for(api, chat_id)
        paused = state.is_chat_paused(chat_id)
        return (
            admin.chat_detail_text(title, stats, last_sync, paused=paused),
            _admin_markup(admin.chat_detail_buttons(chat_id, paused=paused)),
        )
    finally:
        api.close()


def _admin_history(settings, telegram_user_id: int, chat_id: int | None = None) -> tuple[str, InlineKeyboardMarkup] | None:
    """Processing history mapped to task language. Global (chat_id=None) or per-chat."""
    api = _new_api(settings)
    try:
        with get_sessionmaker()() as db:
            if not _admin_check(db, telegram_user_id):
                return None
            title_map = _chat_title_map(db)
        candidates = api.list_candidates(limit=100)
        work_items = api.list_work_items()
        # candidate_id -> work_item_id, so approved candidates show their WI-N task id.
        wi_map = admin.build_wi_map(work_items)
        if chat_id is not None:
            candidates = [c for c in candidates if c.get("source_chat_id") == chat_id]
            label = title_map.get(chat_id, str(chat_id))
            back = "admin:chat:" + str(chat_id)
        else:
            label = None
            back = "admin:menu"
        return (
            admin.history_text(candidates, wi_map, label=label),
            _admin_markup(admin.history_buttons(back)),
        )
    finally:
        api.close()


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


def _admin_markup(buttons: list[list[admin.AdminButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row]
            for row in buttons
        ]
    )


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
    # ---- admin panel (/admin, /setwebhook, admin:* callbacks) ----

    @dp.message(Command("admin"))
    async def _admin_cmd(message: Message) -> None:
        if message.chat.type != "private":
            await message.answer("Команда /admin доступна только в личных сообщениях.")
            return
        result = await asyncio.to_thread(_admin_menu, settings, message.from_user.id)
        if result is None:
            await message.answer("Нет доступа. Привяжи аккаунт: /link <код>.")
            return
        text, markup = result
        await message.answer(text, reply_markup=markup)

    @dp.message(Command("setwebhook"))
    async def _setwebhook(message: Message, command: CommandObject) -> None:
        if message.chat.type != "private":
            await message.answer("Команда /setwebhook доступна только в личных сообщениях.")
            return
        with get_sessionmaker()() as db:
            authorized = await asyncio.to_thread(_admin_check, db, message.from_user.id)
        if not authorized:
            await message.answer("Нет доступа.")
            return
        url = (command.args or "").strip()
        if not url:
            await message.answer("Использование: /setwebhook https://hooks.zapier.com/...")
            return
        err = await asyncio.to_thread(admin.validate_webhook_url, url)  # DNS resolution off the loop
        if err:
            await message.answer(f"❌ {err}\nИспользование: /setwebhook https://hooks.zapier.com/...")
            return
        state.set_admin_webhook(url)
        short = url if len(url) <= 40 else url[:37] + "..."
        await message.answer(f"✅ Webhook задан:\n{short}\n\nТеперь каждый Approve отправит JSON на этот адрес.")

    @dp.callback_query(F.data.startswith("admin:"))
    async def _admin_cb(cb: CallbackQuery) -> None:
        data = cb.data or ""
        uid = cb.from_user.id

        async def _reply(text: str, markup: InlineKeyboardMarkup) -> None:
            try:
                await cb.message.edit_text(text, reply_markup=markup)
            except Exception:
                # edit failed (media message, already edited, etc.) — send a new message
                with contextlib.suppress(Exception):
                    await cb.message.answer(text, reply_markup=markup)
            with contextlib.suppress(Exception):  # suppress "query too old" on restart
                await cb.answer()

        async def _deny(text: str = "Нет доступа.") -> None:
            with contextlib.suppress(Exception):
                await cb.answer(text, show_alert=True)

        if data == "admin:menu":
            result = await asyncio.to_thread(_admin_menu, settings, uid)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:tasks":
            result = await asyncio.to_thread(_admin_tasks, settings, uid, closed=False)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:tasks:closed":
            result = await asyncio.to_thread(_admin_tasks, settings, uid, closed=True)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:review":
            result = await asyncio.to_thread(_admin_review, settings, uid)
            if result is None:
                return await _deny()
            text, back, card_list = result
            await _reply(text, back)
            for card in card_list:
                await _send_card(bot, settings.bot_review_chat_id, card)

        elif data == "admin:integrations":
            result = await asyncio.to_thread(_admin_integrations, uid)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:integrations:clear":
            result = await asyncio.to_thread(_admin_integrations, uid, clear=True)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:integrations:help":
            # Instant alert popup (no extra message) — the /setwebhook line is already on screen.
            with contextlib.suppress(Exception):
                await cb.answer(
                    "Отправь команду:\n/setwebhook https://your-webhook-url.com\n\n"
                    "Подходит Zapier, Make, n8n и любой HTTP-эндпоинт.",
                    show_alert=True,
                )

        elif data == "admin:export":
            with contextlib.suppress(Exception):
                await cb.answer("Загружаю…")
            def _fetch_export():
                with get_sessionmaker()() as db:
                    if not _admin_check(db, uid):
                        return None
                api = _new_api(settings)
                try:
                    return api.list_work_items()
                finally:
                    api.close()
            items = await asyncio.to_thread(_fetch_export)
            if items is None:
                return await _deny()
            if not items:
                with contextlib.suppress(Exception):
                    await cb.message.answer("📋 Одобренных задач пока нет.")
            else:
                STATUS_ICON = {"inbox": "📥", "backlog": "📋", "ready": "🟢",
                               "in_progress": "🔄", "blocked": "🔴", "done": "✅"}
                lines = [f"📋 Задачи ({len(items)} шт.):\n"]
                for wi in items:
                    icon = STATUS_ICON.get(wi.get("status", ""), "•")
                    title = wi.get("title") or "(без названия)"
                    priority = wi.get("priority") or ""
                    due = (wi.get("due_date") or "")[:10]
                    meta = "  ".join(filter(None, [priority, due]))
                    lines.append(f"{icon} WI-{wi['id']} — {title}" + (f"\n    {meta}" if meta else ""))
                # PLAIN text (no parse_mode): titles are untrusted — Markdown specials in a title
                # would otherwise break the whole message (same reason cards are plain, see §17 docstring).
                with contextlib.suppress(Exception):
                    await cb.message.answer("\n".join(lines))

        elif data == "admin:chats":
            # Backfill Redis titles from Telegram API for chats that were configured before
            # we started storing titles (one-shot, free after first run)
            backfill: dict[int, str] = {}
            for cid in state.list_configured_chats():
                cfg = state.get_chat_config(cid) or {}
                if not cfg.get("title"):
                    try:
                        tg_chat = await bot.get_chat(cid)
                        if tg_chat.title:
                            backfill[cid] = tg_chat.title
                    except Exception:
                        pass
            result = await asyncio.to_thread(_admin_chats, uid, _backfill_titles=backfill)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data == "admin:history":
            result = await asyncio.to_thread(_admin_history, settings, uid, None)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data.startswith("admin:chat:"):
            try:
                chat_id = int(data[len("admin:chat:"):])
            except ValueError:
                return await _deny("Некорректный chat id.")
            result = await asyncio.to_thread(_admin_chat_detail, settings, uid, chat_id)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data.startswith("admin:pause:") or data.startswith("admin:resume:"):
            pause = data.startswith("admin:pause:")
            prefix = "admin:pause:" if pause else "admin:resume:"
            try:
                chat_id = int(data[len(prefix):])
            except ValueError:
                return await _deny("Некорректный chat id.")
            result = await asyncio.to_thread(_admin_pause_resume, settings, uid, chat_id, pause=pause)
            if result is None:
                return await _deny()
            await _reply(*result)

        elif data.startswith("admin:sync:"):
            try:
                chat_id = int(data[len("admin:sync:"):])
            except ValueError:
                return await _deny("Некорректный chat id.")
            msg = await asyncio.to_thread(_admin_sync, settings, uid, chat_id)
            if msg is None:
                return await _deny()
            with contextlib.suppress(Exception):
                await cb.answer(msg[:200], show_alert=True)

        elif data.startswith("admin:history:"):
            try:
                chat_id = int(data[len("admin:history:"):])
            except ValueError:
                return await _deny("Некорректный chat id.")
            result = await asyncio.to_thread(_admin_history, settings, uid, chat_id)
            if result is None:
                return await _deny()
            await _reply(*result)

        else:
            with contextlib.suppress(Exception):
                await cb.answer("Неизвестная команда.", show_alert=True)

    # ---- end admin panel ----

    @dp.message(Command("title"))
    async def _set_title(message: Message, command: CommandObject) -> None:
        if message.chat.type != "private":
            return
        args = (command.args or "").strip()
        if not args or " " not in args:
            await message.answer("Использование: /title <id> Новое название")
            return
        id_str, _, new_title = args.partition(" ")
        try:
            candidate_id = int(id_str)
        except ValueError:
            await message.answer("Укажи числовой ID: /title 5 Новое название")
            return
        new_title = new_title.strip()
        if not new_title:
            await message.answer("Название не может быть пустым.")
            return

        def _do_set_title():
            with get_sessionmaker()() as db:
                if not _admin_check(db, message.from_user.id):
                    return None
            api = _new_api(settings)
            try:
                api.patch_candidate(candidate_id, {"title": new_title})
                envelope = api.get_candidate(candidate_id)
                cand = envelope.get("candidate", envelope)
                return cards.render_card(cand)
            finally:
                api.close()

        card = await asyncio.to_thread(_do_set_title)
        if card is None:
            await message.answer("Нет доступа.")
            return
        await _send_card(bot, message.chat.id, card)

    @dp.message(Command("due"))
    async def _set_due(message: Message, command: CommandObject) -> None:
        if message.chat.type != "private":
            return
        import re as _re
        args = (command.args or "").strip()
        if not args or " " not in args:
            await message.answer("Использование: /due <id> ГГГГ-ММ-ДД")
            return
        id_str, _, date_str = args.partition(" ")
        try:
            candidate_id = int(id_str)
        except ValueError:
            await message.answer("Укажи числовой ID: /due 5 2026-07-15")
            return
        date_str = date_str.strip()
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            await message.answer(f"Неверный формат: {date_str!r}\nОжидается ГГГГ-ММ-ДД (например: 2026-07-15)")
            return

        def _do_set_due():
            with get_sessionmaker()() as db:
                if not _admin_check(db, message.from_user.id):
                    return None
            api = _new_api(settings)
            try:
                api.patch_candidate(candidate_id, {"due_date": date_str})
                envelope = api.get_candidate(candidate_id)
                cand = envelope.get("candidate", envelope)
                return cards.render_card(cand)
            finally:
                api.close()

        card = await asyncio.to_thread(_do_set_due)
        if card is None:
            await message.answer("Нет доступа.")
            return
        await _send_card(bot, message.chat.id, card)

    @dp.message(Command("start"))
    async def _start(message: Message) -> None:
        if message.chat.type == "private":
            result = await asyncio.to_thread(_admin_menu, settings, message.from_user.id)
            if result is not None:
                text, markup = result
                await message.answer(text, reply_markup=markup)
                return
        await message.answer(
            "Привет! Я превращаю сообщения в рабочем чате в задачи на ревью.\n"
            "Добавь меня в группу (я должен быть админом, privacy mode выключен).\n"
            "Чтобы привязать свой аккаунт-админ: /link <код>\n\n"
            "После привязки напиши /admin — откроется панель управления."
        )

    @dp.message(Command("link"))
    async def _link(message: Message, command: CommandObject) -> None:
        code = (command.args or "").strip()
        if not code:
            await message.answer("Использование: /link <код> (получи код в веб-консоли).")
            return
        status_code, detail = await asyncio.to_thread(_redeem, settings, code, message.from_user.id)
        await message.answer(_redeem_message(status_code, detail))
        if status_code == 200:
            result = await asyncio.to_thread(_admin_menu, settings, message.from_user.id)
            if result is not None:
                text, markup = result
                await message.answer(text, reply_markup=markup)

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
        opts = onboarding.destination_options()
        with contextlib.suppress(Exception):
            await cb.message.edit_text(opts["text"], reply_markup=_onboard_markup(opts))
        await cb.answer()

    @dp.callback_query(F.data == onboarding.DEST_INTERNAL)
    async def _dest_internal(cb: CallbackQuery) -> None:
        chat_title = cb.message.chat.title or None
        await asyncio.to_thread(
            onboarding.handle_destination_choice, cb.message.chat.id, destination="internal", title=chat_title
        )
        with contextlib.suppress(Exception):
            await cb.message.edit_text(
                "✅ Готово!\n\n"
                "Буду слушать этот чат и присылать карточки-кандидаты тебе в личку.\n"
                "Чтобы управлять — напиши /admin в личном чате со мной."
            )
        await cb.answer("Настроено")

    @dp.callback_query(F.data.in_({onboarding.DEST_TRELLO, onboarding.DEST_NOTION, onboarding.DEST_WEBHOOK}))
    async def _dest_soon(cb: CallbackQuery) -> None:
        labels = {
            onboarding.DEST_TRELLO: "Trello",
            onboarding.DEST_NOTION: "Notion",
            onboarding.DEST_WEBHOOK: "Webhook / Zapier",
        }
        name = labels.get(cb.data or "", "Эта интеграция")
        await cb.answer(f"{name} — скоро. Пока выбери «Только в боте».", show_alert=True)

    @dp.callback_query()
    async def _callback(cb: CallbackQuery) -> None:
        result = await asyncio.to_thread(_dispatch, settings, cb.data or "", cb.from_user.id)
        if result.card is not None:
            with contextlib.suppress(Exception):
                await cb.message.edit_text(result.card.text, reply_markup=_to_markup(result.card.reply_markup))
        elif result.did_act:
            # Action completed — collapse the card: remove buttons, append status line
            settled = (cb.message.text or "") + f"\n\n✅ {result.text}"
            try:
                await cb.message.edit_text(settled, reply_markup=None)
            except Exception:
                with contextlib.suppress(Exception):
                    await cb.message.edit_reply_markup(reply_markup=None)
        with contextlib.suppress(Exception):
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
