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

# Bootstrap-only default for scripts/init_sheet.py when no --sheet-id is
# given — not read by any runtime request path. Each user's actual sheet id
# lives in data/users.json (see common/users.py) instead, since a single
# deployment now serves multiple users, each with their own sheet.
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_FILE = str(
    BASE_DIR / os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "data/credentials/service_account.json")
)

# "Sign in with Google" OAuth client — create one in the GCP Console under
# APIs & Services -> Credentials -> OAuth client ID (Web application), with
# an authorized redirect URI of https://<your-domain-or-ip>/auth/google/callback.
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
WEB_BIND_HOST = os.environ.get("WEB_BIND_HOST", "127.0.0.1")

# Explicit opt-in only, never inferred from WEB_BIND_HOST — a reverse proxy
# (Caddy) can sit in front of a loopback-bound Flask and forward everything,
# debugger included, straight to the internet. Binding to 127.0.0.1 no
# longer reliably means "not reachable externally" once that's the
# deployment shape, so this has to be its own explicit flag, off by default.
DEBUG = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")

REPORTS_CACHE_DIR = DATA_DIR / "reports_cache"
HEARTBEAT_DIR = DATA_DIR


def _get_or_create_secret_key() -> str:
    """A random key for signing session cookies, generated once and persisted
    to disk so sessions survive restarts/deploys — never typed by the user,
    never in git, never in chat."""
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
