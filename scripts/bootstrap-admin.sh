#!/usr/bin/env bash
# Bootstrap the admin account and print a Telegram /link code (run once after deploy.sh).
#
#   1. seeds the admin User from BOT_ADMIN_EMAIL / BOT_ADMIN_PASSWORD in .env (idempotent)
#   2. ensures that admin has an Assignee row (so the bot can authorize your taps)
#   3. issues a single-use /link code (valid ~5 min)
#
# Then, in Telegram, DM your bot:  /link <code>   — this binds YOUR Telegram id to the admin.
#
# Usage (from the repo root on the server, with the stack already up):
#     bash scripts/bootstrap-admin.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# Load .env so we have the admin creds (without echoing them).
set -a; [ -f .env ] && . ./.env; set +a
: "${BOT_ADMIN_EMAIL:?set BOT_ADMIN_EMAIL in .env}"
: "${BOT_ADMIN_PASSWORD:?set BOT_ADMIN_PASSWORD in .env}"

echo "→ Seeding admin user (${BOT_ADMIN_EMAIL})…"
docker compose exec -T \
  -e ADMIN_EMAIL="$BOT_ADMIN_EMAIL" -e ADMIN_PASSWORD="$BOT_ADMIN_PASSWORD" \
  api python -m aiwip_api.seed

echo "→ Ensuring admin Assignee + issuing a Telegram /link code…"
docker compose exec -T -e BOT_ADMIN_EMAIL="$BOT_ADMIN_EMAIL" api python -c '
import os
from aiwip_api import telegram_link
from aiwip_core import models as m
from aiwip_core.db import get_sessionmaker

email = os.environ["BOT_ADMIN_EMAIL"]
with get_sessionmaker()() as db:
    admin = db.query(m.User).filter_by(email=email).one()
    a = db.query(m.Assignee).filter_by(user_id=admin.id).one_or_none()
    if a is None:
        a = m.Assignee(display_name=admin.display_name or "Admin", user_id=admin.id, is_active=True)
        db.add(a); db.commit()
    code = telegram_link.issue_link_code(admin.id)
    print("\n  In Telegram, DM your bot:\n\n      /link " + code + "\n\n  (valid ~5 min — binds your Telegram id to the admin so your taps authorize)\n")
'
