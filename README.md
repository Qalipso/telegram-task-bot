# TaskDefiner — AI Work Intelligence Platform

A Telegram bot that turns work chatter into tracked tasks.

People talk in a group ("Иван, fix the server by Friday"). The bot quietly notices the real
to-dos, uses AI to pull out **what** needs doing, **who** it's for, the **priority** and the
**due date**, and sends you a card to approve. Approved tasks land on a Kanban board.

> **The AI never creates a final task on its own** — every task is one tap of human approval.
> Precision over recall: a missed weak signal beats a wrong task.

```
group message → bot captures → AI drafts a task → card in your DM → you Approve → task on the board
```

## How it works

1. Add **@TaskDefiner_bot** to a work group (make it admin, turn group-privacy **off** so it sees messages).
2. It watches new messages, batches them, and asks OpenAI to extract candidate tasks.
3. Each candidate arrives as a card in your private chat with the bot — title, assignee, priority, due date.
4. Tap **Approve** → it becomes a Work Item on the board. Or **Reject / Edit / Assign**.

## The bot is the main interface

Send `/admin` in your DM with the bot to open the control panel (one live message you navigate):

| Section | What it shows |
|---|---|
| **Задачи** (Tasks) | All active tasks, grouped by priority, each a compact block: `WI-8 · title` + assignee · status · due · source chat. Toggle to closed tasks. |
| **На ревью** (Review) | Candidates waiting for a decision, as action cards (Approve / Reject / Assign / Edit). |
| **Чаты** (Chats) | Connected groups → open one for its task counts, last sync, pause, manual sync, history. |
| **Люди** (People) | Who the AI recognizes by name — plus names it saw but couldn't match, so you can add them. `/addperson Иван @ivan` |
| **История** (History) | What the AI processed (found / created / rejected / pending); approved items shown by their task id. |
| **Интеграции** (Integrations) | Optional outbound webhook (Zapier/Make/n8n) fired on approval; otherwise tasks live locally. |
| **Пригласить** (Invite) | Generate a one-time code → the new person sends `/join <code>` and becomes an admin. |

Bot commands: `/admin`, `/join <code>`, `/addperson Имя @username`, `/title <id> текст`, `/due <id> ГГГГ-ММ-ДД`, `/clear`, `/link <код>`.

## Web console (secondary)

A Next.js operator UI — login, Review Queue, Board (drag-and-drop), Assignees, Sync — over the same
data. In production it's bound to localhost; reach it via an SSH tunnel
(`ssh -L 3000:localhost:3000 …`). Locally it's `http://localhost:3000`.

## Architecture

| Service | Tech | Role |
|---|---|---|
| `bot` | aiogram (long-poll) | The interface: captures group messages, runs the `/admin` panel, sends + handles task cards. The single capture writer. |
| `api` | FastAPI | REST: auth, candidates, work items/board, assignees, sync, audit, invites. |
| `worker` | Python | The AI pipeline: sync → normalize → context → OpenAI extract → candidate. |
| `web` | Next.js 16 / React 19 | Operator console. |
| `core` | shared package | SQLAlchemy models, db, redis, queue, promotion, audit. |
| `postgres` 16 / `redis` 7 | — | data + job queue / sessions. |

Capture is **forward-only and real-time**: the bot buffers incoming messages and hands them to the
worker through one path — no history scraping, no polling of old chats, no duplicate-message races
(the bot is the only writer). The AI runs inside the worker via `run_pipeline()` and only extracts
when a sync actually saved new messages.

> The earlier Telethon (user-account) connector and the 6-hour scheduler were **removed** in the
> bot-first redesign — the bot itself is now the live source.

## Deploy (production, ~$5/mo VPS)

The bot uses long-polling, so **no domain, open ports, or TLS are needed**. On a fresh Ubuntu server:

```bash
git clone https://github.com/Qalipso/telegram-task-bot.git
cd telegram-task-bot
bash scripts/deploy.sh            # installs Docker, builds, starts; first run asks you to fill .env
bash scripts/bootstrap-admin.sh   # seeds the admin + prints a /link code for Telegram
```

Then DM the bot `/link <code>`, send `/admin`, and add the bot to your group. All services run with
`restart: unless-stopped` (survive reboots); Postgres/Redis/API/web are bound to `127.0.0.1` only.
This is running live 24/7 on a Hostinger VPS today.

## Local development

```bash
cp .env.example .env              # fill the secrets below
docker compose up -d --build      # postgres, redis, api, worker, web, bot
```

> ⚠️ **One token, one bot.** A Telegram bot token allows a single poller. Stop the local bot before
> running one on a server, or they fight over `getUpdates`.
> ⚠️ **Rebuild after edits.** Images bundle source at build time:
> `docker compose build <svc> && docker compose up -d <svc>`.

## Environment (`.env`)

| Var | Purpose |
|---|---|
| `POSTGRES_PASSWORD` / `SECRET_KEY` | DB password + session signing — use strong values in production |
| `TELEGRAM_BOT_TOKEN` | from [@BotFather](https://t.me/BotFather) |
| `BOT_REVIEW_CHAT_ID` | your Telegram user id (where cards arrive) — from [@userinfobot](https://t.me/userinfobot) |
| `BOT_ADMIN_EMAIL` / `BOT_ADMIN_PASSWORD` | the bot's own API login (full admin access) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI (default `gpt-4o-mini`) |

`TELEGRAM_API_ID/HASH/PHONE/SESSION` are **no longer required** (Telethon removed). Secrets stay in
`.env` (gitignored) — never in source or chat.

## REST API (admin/operator surface)

- **Auth:** `POST /api/auth/login` · `GET /api/auth/me` · `POST /api/auth/logout`
- **Registration:** invite `POST /api/auth/invite/{start,redeem}` · link `POST /api/auth/telegram-link/start` · `POST /api/auth/telegram/redeem`
- **Candidates (review):** `GET /api/candidates` · `PATCH /api/candidates/{id}` · `POST .../approve` (→ WorkItem) · `POST .../reject`
- **Work items / board:** `GET /api/work-items` · `GET /api/work-items/board` · `POST /api/work-items/{id}/status`
- **Assignees:** `GET/POST /api/assignees` · `PATCH /api/assignees/{id}`
- **Sync:** `POST /api/sync/run` · `GET /api/sync/status`

Roles: **admin** = everything; **assignee** = view + transition only their own work items.

## Tests

```bash
docker compose up -d postgres redis    # tests need them on localhost
.venv/bin/python -m pytest             # 250+ tests across api / bot / worker / core
```

Stop the live `worker` and `bot` containers first — they share Redis and would drain test queues.

## What works today (verified live)

Group capture → AI extraction (OpenAI) → candidate → card in your DM → **Approve → Work Item on the
board**. Plus: assignee resolution and management, **invite-by-code** admin registration, per-chat
sync / pause / history, processing history, optional outbound webhook, and the web console.
Deployed and used daily on a VPS.

## Planned / not yet built

- **Duplicate detection** — similar messages collapsing into one task (designed, not implemented).
- **Stronger title normalization** — turn raw commands ("Иван, сделай всё по ЮИ") into clean titles.
- **Media understanding** — voice/image/doc; attachments are metadata only today.
- **More connectors** — Slack/Email/etc. are reserved; Telegram is the one live source.
- **Per-chat review routing / multiple reviewers** — there is a single review DM today.

---

Product/spec docs live in [`docs/`](docs/). Some of them still describe the pre-bot-first design
(Telethon, 6h scheduler); this README reflects the current, deployed system.
