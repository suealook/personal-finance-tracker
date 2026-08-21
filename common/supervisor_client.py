"""Thin wrapper around the Home Assistant Supervisor REST API, scoped to this
add-on ("self"). Supervisor injects SUPERVISOR_TOKEN automatically into every
add-on container — when that's absent (e.g. running locally on Windows), every
function here reports unavailable instead of erroring, so the rest of the app
works the same either way.
"""

import os

import requests

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_BASE_URL = "http://supervisor"
REQUEST_TIMEOUT_SECONDS = 10


def is_available() -> bool:
    return bool(SUPERVISOR_TOKEN)


def _request(method: str, path: str) -> dict:
    if not is_available():
        raise RuntimeError("Not running under Home Assistant Supervisor (no SUPERVISOR_TOKEN).")
    resp = requests.request(
        method,
        f"{SUPERVISOR_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def get_self_info() -> dict:
    """Supervisor's /addons/self/info payload, e.g. {'version': '0.1.0',
    'version_latest': '0.2.0', 'update_available': True, 'state': 'started', ...}."""
    return _request("GET", "/addons/self/info").get("data", {})


def trigger_update() -> None:
    _request("POST", "/addons/self/update")


def trigger_restart() -> None:
    _request("POST", "/addons/self/restart")
