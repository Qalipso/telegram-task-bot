#!/usr/bin/env bash
# One-shot deploy of the AIWIP stack on a fresh Ubuntu VPS (22.04/24.04).
#
# The Telegram bot uses long-polling (getUpdates), so NO domain, open port, or TLS is
# required for it to work — the server can sit behind NAT. All services run under
# `restart: unless-stopped`, so they survive a reboot.
#
# Usage (run from the repo root on the server, as a user in the `docker` group or with sudo):
#     bash scripts/deploy.sh
#
# Idempotent: re-run after a `git pull` to redeploy the latest code.
set -euo pipefail

cd "$(dirname "$0")/.."

# --- 1. Docker (install if missing) ---------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "→ Installing Docker…"
  curl -fsSL https://get.docker.com | sh
  echo "  Docker installed. (Optional: 'sudo usermod -aG docker \$USER' then re-login to drop sudo.)"
fi

# --- 2. .env (must hold real secrets before we can start) -----------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  cat <<'MSG'

!! Created .env from .env.example — FILL THESE before re-running:

   POSTGRES_PASSWORD     strong random value (e.g. `openssl rand -base64 24`)
   SECRET_KEY            strong random value (`openssl rand -base64 32`)
   TELEGRAM_BOT_TOKEN    from @BotFather
   BOT_REVIEW_CHAT_ID    your Telegram user id (from @userinfobot) — where cards arrive
   BOT_ADMIN_EMAIL       e.g. admin@aiwip.local
   BOT_ADMIN_PASSWORD    strong random value (full admin API access)
   OPENAI_API_KEY        your OpenAI key

   (TELEGRAM_API_ID/HASH/PHONE/SESSION are NOT needed — Telethon was removed.)

   Edit:  nano .env    then re-run:  bash scripts/deploy.sh
MSG
  exit 1
fi

# --- 3. Build + start ----------------------------------------------------------------
echo "→ Building images (first run can take a few minutes; web build needs ~1–2 GB RAM)…"
docker compose build

echo "→ Starting the stack…"
docker compose up -d

echo
echo "→ Status:"
docker compose ps
echo
echo "Done. The api self-creates its DB schema on first boot."
echo "Next: bash scripts/bootstrap-admin.sh   # seed admin + get a /link code for Telegram"
