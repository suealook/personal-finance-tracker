import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Under Home Assistant, user-entered add-on config arrives as JSON here (populated
# by Supervisor from the add-on's Configuration tab) instead of as env vars/.env.
HA_OPTIONS_FILE = Path("/data/options.json")
HA_DATA_DIR = Path("/data")

RUNNING_UNDER_HOME_ASSISTANT = HA_OPTIONS_FILE.exists()

_ha_options: dict = {}
if RUNNING_UNDER_HOME_ASSISTANT:
    try:
        _ha_options = json.loads(HA_OPTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _ha_options = {}


def _get(ha_key: str, env_key: str, default: str = "") -> str:
    if RUNNING_UNDER_HOME_ASSISTANT and _ha_options.get(ha_key):
        return str(_ha_options[ha_key])
    return os.environ.get(env_key, default)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in (see SETUP.md)."
        )
    return value


TELEGRAM_BOT_TOKEN = _get("telegram_bot_token", "TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USER_ID = _get("telegram_allowed_user_id", "TELEGRAM_ALLOWED_USER_ID")

GOOGLE_SHEET_ID = _get("google_sheet_id", "GOOGLE_SHEET_ID")

if RUNNING_UNDER_HOME_ASSISTANT and _ha_options.get("google_service_account_json"):
    # HA's config form can't upload files, so the service-account JSON is pasted as
    # text; write it out once so the rest of the app can treat it as a normal file.
    _service_account_path = HA_DATA_DIR / "service_account.json"
    try:
        _service_account_path.write_text(_ha_options["google_service_account_json"], encoding="utf-8")
    except OSError:
        pass
    GOOGLE_SERVICE_ACCOUNT_FILE = str(_service_account_path)
else:
    GOOGLE_SERVICE_ACCOUNT_FILE = str(
        BASE_DIR / os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "data/credentials/service_account.json")
    )

ANTHROPIC_API_KEY = _get("anthropic_api_key", "ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("claude_model", "CLAUDE_MODEL", "claude-sonnet-5")

WEB_PORT = int(_get("web_port", "WEB_PORT", "5000"))
WEB_BIND_HOST = os.environ.get("WEB_BIND_HOST", "127.0.0.1")

REPORTS_CACHE_DIR = (HA_DATA_DIR if RUNNING_UNDER_HOME_ASSISTANT else BASE_DIR / "data") / "reports_cache"
HEARTBEAT_DIR = HA_DATA_DIR if RUNNING_UNDER_HOME_ASSISTANT else BASE_DIR / "data"
