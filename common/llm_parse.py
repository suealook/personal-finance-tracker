"""Turns a free-text message ("spent 12.50 on coffee at starbucks") into a
structured transaction dict via Claude tool-calling.
"""

from anthropic import Anthropic

from common import usage_tracker
from common.dateutil_helpers import today_str
from config import settings

_client = None

TOOL_SCHEMA = {
    "name": "log_transaction",
    "description": "Log a single financial transaction extracted from the user's message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": (
                    "Transaction date in YYYY-MM-DD format. Resolve relative dates "
                    "(today/yesterday/last friday/etc) against the provided current date."
                ),
            },
            "amount": {
                "type": "number",
                "description": "Transaction amount as a positive number, regardless of income vs expense.",
            },
            "category": {
                "type": "string",
                "description": (
                    "Best-matching category name. Strongly prefer an exact (case-insensitive) "
                    "match from the provided active category list over inventing a new one."
                ),
            },
            "category_is_new": {
                "type": "boolean",
                "description": "True only if `category` is NOT one of the provided active categories.",
            },
            "category_type": {
                "type": "string",
                "enum": ["Expense", "Income", "Savings", "Debt"],
                "description": "Classification of `category`. Only used when category_is_new is true.",
            },
            "note": {
                "type": "string",
                "description": "Short free-text note, e.g. merchant name or memo.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "low"],
                "description": "Low if the message was ambiguous and you had to guess at amount or category.",
            },
        },
        "required": ["date", "amount", "category", "category_is_new", "category_type", "note", "confidence"],
    },
}


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def parse_transaction(text: str, categories: list[str], today: str | None = None) -> dict:
    """Returns a dict matching TOOL_SCHEMA's properties.

    Raises ValueError if the model doesn't return the expected tool call.
    """
    today = today or today_str()
    category_list = ", ".join(categories) if categories else "(no categories defined yet)"
    system = (
        "You extract a single financial transaction from a short free-text message a user "
        "sent to their own personal expense/income logging bot.\n"
        f"Today's date is {today}.\n"
        f"The user's current active categories are: {category_list}.\n"
        "Always prefer matching an existing category (case-insensitive) over inventing a new "
        "one; only set category_is_new=true if nothing existing reasonably fits. "
        "Call the log_transaction tool exactly once with your best extraction."
    )
    response = get_client().messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": text}],
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "log_transaction"},
    )
    usage_tracker.record_claude_usage(response.usage.input_tokens, response.usage.output_tokens)
    for block in response.content:
        if block.type == "tool_use" and block.name == "log_transaction":
            return block.input
    raise ValueError("Model did not return a log_transaction tool call")
