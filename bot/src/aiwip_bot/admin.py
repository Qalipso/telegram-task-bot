"""Pure admin dashboard logic — formatting + outbound webhook push.

No aiogram imports. No DB access. State reads go through state.py (Redis); all task/candidate
data is passed in by the telegram_app adapter (which fetches it over the API). Each screen
answers ONE question:
  • dashboard   — what is the current system state?
  • tasks       — what work exists / needs action?
  • review      — what is waiting for a human decision?
  • chats       — where do tasks come from?
  • integrations— where are tasks sent / stored?
  • history     — what did the AI extraction do over time?
"""
from __future__ import annotations

import ipaddress
import socket
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from aiwip_core.logging import get_logger
from . import state

logger = get_logger("aiwip.bot.admin")

_MAX_URL_DISPLAY = 44

# A WorkItem is "closed" once it leaves the active flow.
CLOSED_WI_STATUSES = {"done", "cancelled", "archived"}

# Candidate statuses that still await a human decision (the review queue).
PENDING_CAND_STATUSES = {"new", "needs_review", "edited"}

# Priority grouping for the tasks screen (critical+high read as "high" visually).
_PRIORITY_ORDER: list[str | None] = ["critical", "high", "medium", "low", None]
_PRIORITY_GROUP = {
    "critical": "🔴 Срочный",
    "high": "🟠 Высокий",
    "medium": "🟡 Средний",
    "low": "🟢 Низкий",
    None: "⚪ Без приоритета",
}

_PRIORITY_DOT = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", None: "⚪"}

# Colour/helper emoji per work-item status — eases scanning inside a task block.
_WI_STATUS_EMOJI = {
    "inbox": "📥", "backlog": "📋", "ready": "🟢", "in_progress": "🔧",
    "blocked": "⛔", "review": "👀", "done": "✅", "cancelled": "🚫", "archived": "🗄",
}

# Status as plain words (paired with _WI_STATUS_EMOJI on a task line).
_WI_STATUS_WORD = {
    "inbox": "входящее",
    "backlog": "бэклог",
    "ready": "готово",
    "in_progress": "в работе",
    "blocked": "заблокировано",
    "review": "на проверке",
    "done": "выполнено",
    "cancelled": "отменено",
    "archived": "в архиве",
}

# Outcome markers for the processing-history list (✅❌⏳ are genuine status markers).
_CAND_STATUS_ICON = {
    "approved": "✅", "rejected": "❌", "needs_review": "⏳",
    "new": "⏳", "edited": "⏳", "duplicate": "❌", "error": "⚠",
}


@dataclass(frozen=True)
class AdminButton:
    text: str
    callback_data: str


# ============================================================ pure aggregators
# These compute the screen numbers from the raw work-item / candidate lists. They live here
# (the aiogram-free "pure logic" module) so they are unit-testable without importing the bot
# runtime. telegram_app.py's adapters fetch the lists over the API and call these.

def dashboard_counters(work_items: list[dict], candidates: list[dict]) -> dict:
    """The five list-derived dashboard counters (chat count is added by the caller)."""
    closed = sum(1 for w in work_items if w.get("status") in CLOSED_WI_STATUSES)
    total = len(work_items)
    return {
        "tasks_total": total,
        "tasks_active": total - closed,
        "tasks_done": closed,
        "pending_review": sum(1 for c in candidates if c.get("status") in PENDING_CAND_STATUSES),
        "rejected": sum(1 for c in candidates if c.get("status") == "rejected"),
    }


def chat_task_stats(work_items: list[dict], chat_id: int) -> dict:
    """total / active / closed task counts for one source chat."""
    mine = [w for w in work_items if w.get("source_chat_id") == chat_id]
    closed = sum(1 for w in mine if w.get("status") in CLOSED_WI_STATUSES)
    return {"total": len(mine), "active": len(mine) - closed, "closed": closed}


def build_wi_map(work_items: list[dict]) -> dict[int, int]:
    """candidate_id -> work_item_id, so approved candidates render their WI-N task id.
    Work items without a source candidate (manual, or missing key) are skipped."""
    return {w["source_candidate_id"]: w["id"] for w in work_items if w.get("source_candidate_id")}


def _short_date(iso: str | None) -> str:
    return iso[:10] if iso else ""


def _short_dt(iso: str | None) -> str:
    """ISO timestamp -> 'YYYY-MM-DD HH:MM' for human display."""
    if not iso:
        return ""
    return iso[:16].replace("T", " ")


# ============================================================ 1. Dashboard (/admin)

def dashboard_text(stats: dict) -> str:
    """stats: chats, tasks_total, tasks_active, tasks_done, pending_review, rejected."""
    return (
        "🌴 TaskDefiner · панель\n\n"
        f"💬 Чаты: {stats.get('chats', 0)}\n"
        f"📋 Задачи: {stats.get('tasks_total', 0)}\n"
        f"🟢 Активные: {stats.get('tasks_active', 0)}\n"
        f"✅ Закрыто: {stats.get('tasks_done', 0)}\n"
        f"🟡 На ревью: {stats.get('pending_review', 0)}\n"
        f"🔴 Отклонено: {stats.get('rejected', 0)}"
    )


def dashboard_buttons() -> list[list[AdminButton]]:
    return [
        [AdminButton("🌴 Задачи", "admin:tasks"), AdminButton("🐒 На ревью", "admin:review")],
        [AdminButton("🦜 Чаты", "admin:chats"), AdminButton("🐘 Люди", "admin:people")],
        [AdminButton("🐢 История", "admin:history"), AdminButton("🐍 Интеграции", "admin:integrations")],
        [AdminButton("🪺 Пригласить", "admin:invite"), AdminButton("🍃 Обновить", "admin:menu")],
    ]


# ============================================================ 2. Tasks

def _task_block(wi: dict) -> str:
    """A compact 2-line block: 'WI-N · title' then a meta line. Priority is shown by the
    section header it sits under, so the line itself stays free of emoji."""
    title = wi.get("title") or "(без названия)"
    head = f"WI-{wi.get('id', '?')} · {title}"
    status = wi.get("status", "")
    meta: list[str] = []
    assignees = wi.get("assignees") or []
    if assignees:
        meta.append("👤 " + ", ".join(assignees[:2]))
    status_emoji = _WI_STATUS_EMOJI.get(status, "•")
    meta.append(f"{status_emoji} {_WI_STATUS_WORD.get(status, status)}")
    due = _short_date(wi.get("due_date"))
    if due:
        meta.append(f"📅 {due}")
    chat = wi.get("source_chat_title")
    if chat:
        meta.append(f"💬 {chat}")
    return head + "\n" + " · ".join(meta)


def tasks_text(work_items: list[dict], *, closed: bool = False) -> str:
    if closed:
        items = [w for w in work_items if w.get("status") in CLOSED_WI_STATUSES]
        if not items:
            return "🍂 Закрытых задач нет."
        header = f"🍂 Закрытые задачи: {len(items)}"
    else:
        items = [w for w in work_items if w.get("status") not in CLOSED_WI_STATUSES]
        if not items:
            return "🌴 Активных задач нет.\n\nОдобренные задачи появятся здесь."
        header = f"🌴 Активные задачи: {len(items)}"

    lines = [header]
    by_priority: dict[str | None, list[dict]] = {}
    for w in items:
        by_priority.setdefault(w.get("priority"), []).append(w)
    for pr in _PRIORITY_ORDER:
        group = by_priority.get(pr)
        if not group:
            continue
        lines.append("")
        lines.append(_PRIORITY_GROUP[pr])  # e.g. "🟠 Высокий" — the only status marker per row
        for w in group[:15]:
            lines.append("")
            lines.append(_task_block(w))
    return "\n".join(lines)


def tasks_buttons(*, closed: bool = False) -> list[list[AdminButton]]:
    if closed:
        toggle = AdminButton("🌿 Активные", "admin:tasks")
        refresh = AdminButton("🍃 Обновить", "admin:tasks:closed")
    else:
        toggle = AdminButton("🍂 Закрытые", "admin:tasks:closed")
        refresh = AdminButton("🍃 Обновить", "admin:tasks")
    return [[refresh, toggle], [AdminButton("🐾 Назад", "admin:menu")]]


# ============================================================ 3. Review queue

def review_text(candidates: list[dict]) -> str:
    pending = [c for c in candidates if c.get("status") in PENDING_CAND_STATUSES]
    if not pending:
        return "Очередь ревью пуста.\n\nНовые кандидаты из чатов появятся здесь."
    lines = [f"🟡 На ревью: {len(pending)}"]
    for c in pending[:10]:
        icon = _CAND_STATUS_ICON.get(c.get("status", ""), "⏳")
        title = c.get("title") or "(без названия)"
        lines.append("")
        lines.append(f"{icon} #{c.get('id', '?')} · {title}")
        chat = c.get("source_chat_title")
        if chat:
            lines.append(f"💬 {chat}")
    if len(pending) > 10:
        lines.append(f"\n… ещё {len(pending) - 10}")
    return "\n".join(lines)


def review_buttons() -> list[list[AdminButton]]:
    return [[AdminButton("🍃 Обновить", "admin:review"), AdminButton("🐾 Назад", "admin:menu")]]


# ============================================================ 4. Chats

def chats_text(chats: list[tuple[int, str]]) -> str:
    """chats: list of (external_chat_id, display_title)."""
    if not chats:
        return "🦜 Чаты\n\nНет подключённых чатов.\nДобавь бота в группу и пройди настройку."
    lines = [f"🦜 Подключённые чаты: {len(chats)}", ""]
    for cid, title in chats:
        marker = "⏸" if state.is_chat_paused(cid) else "🟢"
        lines.append(f"{marker} {title}")
    return "\n".join(lines)


def chats_buttons(chats: list[tuple[int, str]]) -> list[list[AdminButton]]:
    """One button per chat → opens chat detail."""
    rows: list[list[AdminButton]] = []
    for cid, title in chats:
        short = title[:24] + "…" if len(title) > 24 else title
        icon = "🦥" if state.is_chat_paused(cid) else "🦜"
        rows.append([AdminButton(f"{icon} {short}", f"admin:chat:{cid}")])
    rows.append([AdminButton("🐾 Назад", "admin:menu")])
    return rows


def chat_detail_text(title: str, stats: dict, last_sync: str | None, *, paused: bool) -> str:
    """stats: total, active, closed. last_sync: ISO timestamp or None."""
    state_line = "⏸ На паузе" if paused else "🟢 Активен"
    sync_line = _short_dt(last_sync) or "ещё не было"
    return (
        f"🦜 {title}\n\n"
        f"{state_line}\n"
        f"📋 Задачи: {stats.get('total', 0)}\n"
        f"🟢 Активные: {stats.get('active', 0)}\n"
        f"✅ Закрыто: {stats.get('closed', 0)}\n"
        f"🕓 Синхронизация: {sync_line}"
    )


def chat_detail_buttons(chat_id: int, *, paused: bool) -> list[list[AdminButton]]:
    pause_btn = (
        AdminButton("🐆 Возобновить", f"admin:resume:{chat_id}")
        if paused else AdminButton("🦥 Пауза", f"admin:pause:{chat_id}")
    )
    return [
        [AdminButton("🌧 Синхронизировать", f"admin:sync:{chat_id}")],
        [AdminButton("🐢 История", f"admin:history:{chat_id}"), pause_btn],
        [AdminButton("🐾 К чатам", "admin:chats")],
    ]


# ============================================================ People (recognized assignees)

def people_text(assignees: list[dict], unresolved: list[str]) -> str:
    """Who the AI resolver recognizes in chat messages, plus mentions it could NOT match."""
    active = [a for a in assignees if a.get("is_active")]
    if not assignees:
        lines = ["🐘 Люди\n", "Пока никого нет — добавь людей, чтобы задачи назначались."]
    else:
        lines = [f"🐘 Узнаю в чатах: {len(active)}", ""]
        for a in assignees:
            marker = "✅" if a.get("is_active") else "⏸"
            name = a.get("display_name") or "—"
            uname = f" · @{a['telegram_username']}" if a.get("telegram_username") else ""
            aliases = a.get("aliases") or []
            alias_s = f" · {', '.join(aliases)}" if aliases else ""
            lines.append(f"{marker} {name}{uname}{alias_s}")
    if unresolved:
        lines.append("")
        lines.append("❓ Не распознаны в чатах: " + ", ".join(unresolved[:10]))
    return "\n".join(lines)


def people_buttons(assignees: list[dict]) -> list[list[AdminButton]]:
    """One toggle per person (deactivate/activate) + add + back."""
    rows: list[list[AdminButton]] = []
    for a in assignees[:12]:
        name = (a.get("display_name") or "—")[:16]
        if a.get("is_active"):
            rows.append([AdminButton(f"🌿 {name}", f"admin:poff:{a['id']}")])
        else:
            rows.append([AdminButton(f"🍂 {name}", f"admin:pon:{a['id']}")])
    rows.append([AdminButton("🌱 Добавить", "admin:addperson")])
    rows.append([AdminButton("🐾 Назад", "admin:menu")])
    return rows


# ============================================================ 5. Integrations

def integrations_text(webhook_url: str | None) -> str:
    if webhook_url:
        display = webhook_url if len(webhook_url) <= _MAX_URL_DISPLAY else webhook_url[:_MAX_URL_DISPLAY - 1] + "…"
        return (
            "🐍 Интеграции\n\n"
            "✅ Webhook подключён\n"
            f"{display}\n\n"
            "Срабатывает при каждом одобрении задачи.\n"
            "Сменить: /setwebhook <url>"
        )
    return (
        "🐍 Интеграции\n\n"
        "✅ Одобренные задачи хранятся локально (видны в веб-консоли).\n"
        "⚠️ Внешний webhook не задан.\n\n"
        "Чтобы отправлять задачи во внешний сервис (Zapier, Make, n8n):\n"
        "/setwebhook https://your-webhook-url.com"
    )


def integrations_buttons(webhook_url: str | None) -> list[list[AdminButton]]:
    rows: list[list[AdminButton]] = []
    if webhook_url:
        rows.append([AdminButton("🪓 Отключить webhook", "admin:integrations:clear")])
    else:
        rows.append([AdminButton("🌱 Задать webhook", "admin:integrations:help")])
    rows.append([AdminButton("🌴 Список задач", "admin:export")])
    rows.append([AdminButton("🐾 Назад", "admin:menu")])
    return rows


# ============================================================ 6. Processing history

def history_text(
    candidates: list[dict],
    wi_map: dict[int, int],
    *,
    label: str | None = None,
) -> str:
    """Map AI candidates to user-facing language. wi_map: {candidate_id: work_item_id}.

    Approved candidates are shown as their promoted task id (WI-N), never the raw candidate id.
    """
    title = f"🐢 История обработки — {label}" if label else "🐢 История обработки"
    if not candidates:
        return f"{title}\n\nПока ничего не обработано."
    counts: Counter[str] = Counter(c.get("status") for c in candidates)
    pending = counts.get("new", 0) + counts.get("needs_review", 0) + counts.get("edited", 0)
    lines = [
        title,
        "",
        f"🔍 Найдено: {len(candidates)}",
        f"✅ Создано задач: {counts.get('approved', 0)}",
        f"🔴 Отклонено: {counts.get('rejected', 0)}",
        f"🟡 Ждут ревью: {pending}",
        "",
        "Последние",
    ]
    for c in candidates[:6]:
        status = c.get("status", "")
        icon = _CAND_STATUS_ICON.get(status, "•")  # ✅ / ❌ / ⏳ outcome marker
        c_title = c.get("title") or "(без названия)"
        if status == "approved" and c.get("id") in wi_map:
            ref = f"WI-{wi_map[c['id']]}"
        else:
            ref = f"#{c.get('id', '?')}"
        lines.append(f"{icon} {ref} · {c_title}")
    return "\n".join(lines)


def history_buttons(back: str = "admin:menu") -> list[list[AdminButton]]:
    return [[AdminButton("🐾 Назад", back)]]


# ============================================================ outbound webhook

def validate_webhook_url(url: str, *, _resolve=socket.getaddrinfo) -> str | None:
    """Guard /setwebhook against SSRF. Return None if the URL is an acceptable outbound target,
    else a short human error string.

    Policy (chosen 2026-06-27, security-sensitive): https-only; block loopback (127/8, ::1,
    localhost) and link-local / cloud-metadata (169.254.0.0/16, fe80::/10). Public and private-LAN
    https endpoints (e.g. self-hosted n8n on 192.168.x.x over TLS) are allowed. The host is resolved
    and EVERY mapped address is checked, so a public hostname pointing at metadata/loopback is caught.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001 — any parse failure is a reject
        return "Некорректный URL."
    if parsed.scheme != "https":
        return "Webhook должен использовать https://."
    host = parsed.hostname
    if not host:
        return "В URL не указан хост."
    if host.lower() == "localhost":
        return "Локальные адреса запрещены."
    try:
        infos = _resolve(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return "Не удалось разрешить хост."
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local:
            return "Адрес указывает на служебную/локальную сеть — запрещено."
    return None


def push_webhook(work_item: dict, url: str) -> bool:
    """POST the approved work item to the configured webhook URL. Returns True on success."""
    try:
        resp = httpx.post(
            url,
            json={"event": "work_item.approved", "work_item": work_item},
            timeout=5.0,
        )
        if resp.status_code >= 400:
            logger.warning("webhook POST %s for url=%r", resp.status_code, url)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — incl. httpx.InvalidURL (NOT an httpx.HTTPError) from a
        logger.warning("webhook POST failed: %s", exc)  # malformed stored URL; never fail the approve
        return False
