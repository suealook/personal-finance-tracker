"""Tracks cumulative Claude API token usage (persisted to disk, survives
restarts) for the /update page's cost estimate. Google Sheets API call
counts live in common.sheets_client instead — Sheets has no per-call
billing, so there's nothing to cost-estimate there, just a call count.
"""

import json
from pathlib import Path
from threading import Lock

from config import settings

USAGE_FILE: Path = settings.HEARTBEAT_DIR / "claude_usage.json"

# Claude Sonnet 5 standard list pricing, per 1M tokens (USD, as of 2026-08).
# Not the temporary intro pricing (expires 2026-08-31) -- update these if
# Anthropic's pricing changes, or if CLAUDE_MODEL is switched to a different
# model tier.
INPUT_COST_PER_MILLION_USD = 3.00
OUTPUT_COST_PER_MILLION_USD = 15.00

# Rough fixed conversion, not a live exchange rate -- this is a ballpark
# estimate, not an accounting figure. Update occasionally.
USD_TO_THB = 36.0

_lock = Lock()


def _read() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict):
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def record_claude_usage(input_tokens: int, output_tokens: int):
    """Call once after every Claude messages.create() response. Not safe
    against true concurrent writes across processes (bot + web both call
    this) -- for this app's call volume, a lost update is an acceptable,
    self-corrects-next-call approximation, not a real accounting ledger."""
    with _lock:
        data = _read()
        data["input_tokens"] = data.get("input_tokens", 0) + max(0, input_tokens)
        data["output_tokens"] = data.get("output_tokens", 0) + max(0, output_tokens)
        data["call_count"] = data.get("call_count", 0) + 1
        _write(data)


def get_claude_usage_summary() -> dict:
    data = _read()
    input_tokens = data.get("input_tokens", 0)
    output_tokens = data.get("output_tokens", 0)
    cost_usd = (
        (input_tokens / 1_000_000) * INPUT_COST_PER_MILLION_USD
        + (output_tokens / 1_000_000) * OUTPUT_COST_PER_MILLION_USD
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "call_count": data.get("call_count", 0),
        "cost_usd": round(cost_usd, 4),
        "cost_thb": round(cost_usd * USD_TO_THB, 2),
    }
