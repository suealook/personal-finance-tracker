"""Turns a message — free text ("spent 12.50 on coffee at starbucks") or a
receipt photo — into a structured transaction dict via Claude tool-calling.
"""

import base64

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


def _build_system_prompt(categories: list[str], today: str) -> str:
    category_list = ", ".join(categories) if categories else "(no categories defined yet)"
    return (
        "You extract a single financial transaction from a message a user sent to their "
        "own personal expense/income logging bot. The message may be free text, a photo "
        "of a receipt, or both.\n"
        f"Today's date is {today}.\n"
        f"The user's current active categories are: {category_list}.\n"
        "Always prefer matching an existing category (case-insensitive) over inventing a new "
        "one; only set category_is_new=true if nothing existing reasonably fits. For a "
        "receipt photo, use the total amount and infer the merchant/category from what's "
        "visible. Call the log_transaction tool exactly once with your best extraction."
    )


def _extract_transaction(content, categories: list[str], today: str) -> dict:
    """`content` is either a plain string (text messages) or a list of Claude
    content blocks (e.g. image + text, for receipt photos). Shared by every
    input path so the tool schema, system prompt, and usage tracking never
    drift between them."""
    response = get_client().messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=500,
        system=_build_system_prompt(categories, today),
        messages=[{"role": "user", "content": content}],
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "log_transaction"},
    )
    usage_tracker.record_claude_usage(response.usage.input_tokens, response.usage.output_tokens)
    for block in response.content:
        if block.type == "tool_use" and block.name == "log_transaction":
            return block.input
    raise ValueError("Model did not return a log_transaction tool call")


def parse_transaction(text: str, categories: list[str], today: str | None = None) -> dict:
    """Returns a dict matching TOOL_SCHEMA's properties.

    Raises ValueError if the model doesn't return the expected tool call.
    """
    return _extract_transaction(text, categories, today or today_str())


def parse_transaction_from_image(
    image_bytes: bytes,
    categories: list[str],
    today: str | None = None,
    caption: str | None = None,
    media_type: str = "image/jpeg",
) -> dict:
    """Same contract as parse_transaction, for a receipt photo instead of text.
    `caption` is whatever text the user attached to the photo, if any."""
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode("ascii"),
            },
        },
        {"type": "text", "text": caption or "Extract the transaction from this receipt photo."},
    ]
    return _extract_transaction(content, categories, today or today_str())
