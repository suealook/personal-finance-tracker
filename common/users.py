"""The allowlist of people permitted to use this deployment: who they sign in
as (Google email), which Telegram account routes to them, and which Google
Sheet their data lives in.

A small, hand-edited JSON file rather than a database — right-sized for a
handful of known people; edit `data/users.json` and restart both services to
add or remove someone. Loaded once at import time by both the web and bot
processes independently.
"""

import json
from typing import Optional

from config import settings

_USERS_FILE = settings.DATA_DIR / "users.json"


def _load() -> list[dict]:
    if not _USERS_FILE.exists():
        return []
    try:
        data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Could not read {_USERS_FILE}: {e}") from e
    for row in data:
        missing = [k for k in ("email", "sheet_id", "telegram_user_id") if not row.get(k)]
        if missing:
            raise RuntimeError(f"{_USERS_FILE}: entry {row!r} is missing required field(s) {missing}")
    return data


_USERS = _load()
_BY_EMAIL = {row["email"].strip().lower(): row for row in _USERS}
_BY_TELEGRAM_ID = {str(row["telegram_user_id"]): row for row in _USERS}


def get_user_by_email(email: str) -> Optional[dict]:
    return _BY_EMAIL.get(email.strip().lower())


def get_user_by_telegram_id(telegram_id: str) -> Optional[dict]:
    return _BY_TELEGRAM_ID.get(str(telegram_id))


def any_users_configured() -> bool:
    return bool(_USERS)
