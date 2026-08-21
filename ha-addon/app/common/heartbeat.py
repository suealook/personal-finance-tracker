"""Simple file-based liveness signal so the web process can report the bot
process's status (and vice versa) without any IPC — both run in the same
container/filesystem under the Home Assistant add-on, or the same local `data/`
folder in dev.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings


def _path_for(name: str) -> Path:
    return settings.HEARTBEAT_DIR / f"heartbeat_{name}.txt"


def write_heartbeat(name: str) -> None:
    path = _path_for(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    except OSError:
        pass


def read_heartbeat(name: str) -> Optional[datetime]:
    path = _path_for(name)
    try:
        text = path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (OSError, ValueError):
        return None


def heartbeat_age_seconds(name: str) -> Optional[float]:
    ts = read_heartbeat(name)
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds()
