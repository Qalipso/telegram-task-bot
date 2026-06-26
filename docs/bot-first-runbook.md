# Bot-first — live test runbook

How to test the BotFather bot end-to-end against a real Telegram group. Assumes the design/impl is
on branch `feat/bot-first-capture`.

## 0. Prerequisites (BotFather side — done once)
- A bot created via **@BotFather** → you have its **token**.
- BotFather → `/setprivacy` → your bot → **Disable** (so it sees ordinary group messages).
- A test Telegram **group** with the bot added as **admin**.
- Your numeric Telegram id (DM **@userinfobot**) — this is `BOT_REVIEW_CHAT_ID` (where confirm
  cards are sent) and the account you'll link as admin.

## 1. Configure `.env`
Edit `~/Documents/telegram-task-bot/.env`:
```bash
TELEGRAM_BOT_TOKEN=<token from BotFather>
BOT_REVIEW_CHAT_ID=<your numeric Telegram id>
BOT_ADMIN_EMAIL=admin@aiwip.local
BOT_ADMIN_PASSWORD=aiwip-admin-dev
BOT_API_BASE=http://api:8000
# OPENAI_API_KEY must be set (extraction needs it) — already set in this stack.
```
`.env` is gitignored — never commit it.

## 2. Rebuild + run the stack
The `api`/`worker` images are stale (pre-bot-first) and the `bot` image is new — rebuild all three:
```bash
cd ~/Documents/telegram-task-bot
docker compose build api worker bot
docker compose up -d api worker bot
docker compose logs -f bot          # watch: "bot polling started; confirm cards go to chat <id>"
```

## 3. Start a DM + link your admin account
Telegram bots can't message you first, so DM the bot **`/start`** once (opens the DM that confirm
cards go to). Then generate a one-time link code (no web button yet):
```bash
cd ~/Documents/telegram-task-bot
DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" \
REDIS_URL="redis://localhost:6379/0" \
.venv/bin/python scripts/bot_test_setup.py
```
It prints `/link <code>`. DM that to your bot → **“Аккаунт привязан.”** Now your taps authorize
(per-callback authz maps your Telegram id → the linked admin).

## 4. Configure the group (configure-before-capture)
Send **any** message in the test group. The bot replies *“выберите куда складывать”* with a button →
tap **“Выбрать борду/назначение”** → *“я начал ловить задачи в этом чате.”* The chat is now
configured (until then it captures nothing — by design).

## 5. Test the capture → confirm → approve loop
Send a work message in the group, e.g.:
> подготовь отчёт к пятнице, срочно

Within ~60s (debounce window) the worker extracts a **Candidate** and the bot DMs you a **confirm
card** (to `BOT_REVIEW_CHAT_ID`) with **✅ Approve / 🗑 Reject / ✏️ Edit** (and **Assign…/Who?** when
the responsible person is unknown/ambiguous). Tap **✅ Approve** → it promotes to a **WorkItem**,
visible on the web board at `http://localhost:3000`.

## Notes / troubleshooting
- Casual chatter yields **no** card by design (precision-over-recall: `<0.60` confidence is dropped).
- No card? `docker compose logs -f bot worker` — check extraction ran and `bot.notify` was consumed.
- Only people added as **Assignees** resolve by name; an unknown mention shows **Assign…**.
- The bot **never auto-approves** — every approval is your explicit tap through the admin-gated API.
- Reset a chat's onboarding: remove + re-add the bot (clears its config), then reconfigure.
- Known MVP gaps (fast-follows): no web "Link Telegram" button (hence the helper script); confirm
  cards route to one review chat, not back to the source group; free-text edit deep-links to the web
  console.
