"""Interactive helper: mint a Telethon session, save it to .env, and list your chats.

RUN THIS YOURSELF (it needs the login code Telegram sends to your device):

    .venv/bin/python scripts/telegram_login.py

Reads TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE from .env, logs you in
(prompts for the code, and your 2FA password if set), writes TELEGRAM_SESSION back into
.env, then prints your recent chats with their IDs so you can pick TELEGRAM_CHAT_ID.
The session string is written to .env, never printed — keep .env secret (it is gitignored).
"""
from __future__ import annotations

import pathlib
from getpass import getpass

ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"


def _write_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def main() -> None:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    from aiwip_core.config import settings

    api_id, api_hash, phone = settings.telegram_api_id, settings.telegram_api_hash, settings.telegram_phone
    if not (api_id and api_hash and phone):
        raise SystemExit("Set TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE in .env first.")
    phone = str(phone)
    if not phone.startswith("+"):
        phone = "+" + phone

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    client.connect()
    if not client.is_user_authorized():
        client.send_code_request(phone)
        code = input("Login code from Telegram: ").strip()
        try:
            client.sign_in(phone, code)
        except Exception:  # noqa: BLE001 — likely 2FA enabled
            client.sign_in(password=getpass("2FA password: "))

    me = client.get_me()
    _write_env("TELEGRAM_SESSION", client.session.save())
    print(f"\n✓ Logged in as {getattr(me, 'username', None) or me.first_name}; TELEGRAM_SESSION saved to .env\n")

    print("Your recent chats (copy one id into .env as TELEGRAM_CHAT_ID):")
    for dialog in client.iter_dialogs(limit=40):
        kind = "channel" if getattr(dialog, "is_channel", False) else ("group" if getattr(dialog, "is_group", False) else "user")
        print(f"  {dialog.id:>16}  [{kind:<7}] {dialog.name}")
    client.disconnect()


if __name__ == "__main__":
    main()
