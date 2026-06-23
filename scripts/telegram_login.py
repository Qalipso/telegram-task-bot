"""Interactive helper to mint a Telethon StringSession.

RUN THIS YOURSELF in a terminal (it cannot be done by the agent — it requires the login
code Telegram sends to your device, and your 2FA password if set).

  1. Get api_id + api_hash from https://my.telegram.org (API development tools).
  2. Put them in .env (TELEGRAM_API_ID / TELEGRAM_API_HASH), or you'll be prompted.
  3. Run:  python scripts/telegram_login.py
  4. Enter your phone, then the code Telegram sends, then your 2FA password if prompted.
  5. Copy the printed session string into .env as TELEGRAM_SESSION (keep it SECRET — it is
     equivalent to a logged-in session; never commit it).
"""
import os


def main() -> None:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    api_id = os.environ.get("TELEGRAM_API_ID") or input("api_id: ").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("api_hash: ").strip()

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        session = client.session.save()
        print(f"\nLogged in as: {getattr(me, 'username', None) or me.first_name}")
        print("\n=== TELEGRAM_SESSION (paste into .env; keep secret) ===")
        print(session)


if __name__ == "__main__":
    main()
