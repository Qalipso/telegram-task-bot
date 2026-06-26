"""One-off helper for a live bot test: ensure the dev admin has a linked Assignee, then print a
fresh /link code to DM the bot. Avoids the (not-yet-built) web 'Link Telegram' button.

Run from the repo root with localhost DB/Redis (the docker stack maps both to localhost):

    DATABASE_URL="postgresql+psycopg://aiwip:aiwip@localhost:5432/aiwip" \
    REDIS_URL="redis://localhost:6379/0" \
    .venv/bin/python scripts/bot_test_setup.py

Then in Telegram DM your bot:  /link <code>   (the code is valid ~5 minutes).
"""
from __future__ import annotations

import os

from aiwip_api import telegram_link
from aiwip_core import models as m
from aiwip_core.db import get_sessionmaker

ADMIN_EMAIL = os.environ.get("BOT_ADMIN_EMAIL", "admin@aiwip.local")


def main() -> None:
    with get_sessionmaker()() as db:
        admin = db.query(m.User).filter_by(email=ADMIN_EMAIL).one_or_none()
        if admin is None:
            raise SystemExit(f"No user {ADMIN_EMAIL!r} — seed an admin first (python -m aiwip_api.seed).")
        if admin.role != m.UserRole.admin:
            raise SystemExit(f"{ADMIN_EMAIL!r} is not an admin.")

        assignee = db.query(m.Assignee).filter_by(user_id=admin.id).one_or_none()
        if assignee is None:
            assignee = m.Assignee(
                display_name=admin.display_name or "Admin", user_id=admin.id, is_active=True
            )
            db.add(assignee)
            db.commit()
            print(f"created Assignee #{assignee.id} linked to admin user #{admin.id}")
        else:
            print(f"admin user #{admin.id} already has Assignee #{assignee.id}")

        code = telegram_link.issue_link_code(admin.id)
        print("\n  In Telegram, DM your bot:\n")
        print(f"      /link {code}\n")
        print("  (valid ~5 min; redeem binds YOUR Telegram id to the admin so your taps authorize)")


if __name__ == "__main__":
    main()
