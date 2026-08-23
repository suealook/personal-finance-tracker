import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in (see SETUP.md)."
        )
    return value


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_FILE = str(
    BASE_DIR / os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "data/credentials/service_account.json")
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
WEB_BIND_HOST = os.environ.get("WEB_BIND_HOST", "127.0.0.1")

# Required whenever WEB_BIND_HOST isn't loopback-only (enforced, fail-closed,
# in web/app.py specifically — not here, since this module is also imported
# by the bot process, which has no need for this password). Optional for
# local dev, which stays on 127.0.0.1 by default.
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
# Optional — if blank, the login page accepts any username alongside the
# correct password (password-only).
DASHBOARD_USERNAME = os.environ.get("DASHBOARD_USERNAME", "")

REPORTS_CACHE_DIR = DATA_DIR / "reports_cache"
HEARTBEAT_DIR = DATA_DIR


def _get_or_create_secret_key() -> str:
    """A random key for signing session cookies, generated once and persisted
    to disk so sessions survive restarts/deploys — never typed by the user,
    never in git, never in chat, unlike DASHBOARD_PASSWORD above."""
    path = HEARTBEAT_DIR / "flask_secret_key"
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        path.write_text(key, encoding="utf-8")
        return key
    except OSError:
        # Falls back to a key that's regenerated every process start (every
        # existing session gets logged out on restart) rather than crashing
        # the app if the data directory is somehow unwritable.
        return secrets.token_hex(32)


FLASK_SECRET_KEY = _get_or_create_secret_key()
