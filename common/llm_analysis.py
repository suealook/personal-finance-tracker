"""Generates the monthly planned-vs-actual spending analysis via Claude."""

from anthropic import Anthropic

from common import sheets_client
from common import usage_tracker
from common.dateutil_helpers import month_bounds, now_str
from config import settings

_client = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def compute_variance(month: str, actual: list[dict] | None = None) -> list[dict]:
    """Planned vs actual per category for `month` (YYYY-MM). Arithmetic done in Python,
    never left to the LLM.

    `actual` lets a caller that already fetched transactions (e.g. the dashboard,
    which needs several months at once) pass them in instead of triggering another
    full Sheets read here.
    """
    planned = sheets_client.get_planned(month)
    if actual is None:
        start, end = month_bounds(month)
        actual = sheets_client.get_actual(start_date=start, end_date=end)

    planned_by_cat = {p["Category"]: float(p["PlannedAmount"] or 0) for p in planned}
    actual_by_cat: dict[str, float] = {}
    for txn in actual:
        cat = txn.get("Category", "")
        amt = float(txn.get("Amount") or 0)
        actual_by_cat[cat] = actual_by_cat.get(cat, 0.0) + amt

    categories = sorted(set(planned_by_cat) | set(actual_by_cat))
    rows = []
    for cat in categories:
        planned_amt = planned_by_cat.get(cat, 0.0)
        actual_amt = actual_by_cat.get(cat, 0.0)
        rows.append(
            {
                "category": cat,
                "planned": planned_amt,
                "actual": actual_amt,
                "variance": actual_amt - planned_amt,
            }
        )
    return rows


def _build_prompt(month: str, rows: list[dict]) -> str:
    if not rows:
        table = "(no planned budgets or transactions recorded for this month)"
    else:
        lines = ["| Category | Planned | Actual | Variance |", "|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['category']} | {r['planned']:.2f} | {r['actual']:.2f} | {r['variance']:+.2f} |")
        table = "\n".join(lines)

    total_planned = sum(r["planned"] for r in rows)
    total_actual = sum(r["actual"] for r in rows)

    return (
        f"Here is my planned vs. actual spending for {month}:\n\n"
        f"{table}\n\n"
        f"Totals: planned {total_planned:.2f}, actual {total_actual:.2f}, "
        f"variance {total_actual - total_planned:+.2f}.\n\n"
        "Please give me:\n"
        "1. The top overspending areas and by how much\n"
        "2. What's going well / where I'm under budget\n"
        "3. 3-5 concrete, specific, actionable suggestions for next month\n\n"
        "Format as markdown, keep it around 400 words."
    )


def generate_monthly_report(month: str) -> str:
    rows = compute_variance(month)
    user_prompt = _build_prompt(month, rows)
    system = (
        "You are a supportive but direct personal finance coach. The user's goals are to pay "
        "off debt, build savings, and gain more freedom to pursue their own life priorities. "
        "Be specific and reference the actual numbers given rather than generic advice."
    )
    response = get_client().messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    usage_tracker.record_claude_usage(response.usage.input_tokens, response.usage.output_tokens)
    return "".join(block.text for block in response.content if block.type == "text")


def quick_tip(month: str) -> str | None:
    """A single short, concrete observation about this month's transactions so far
    (e.g. overlapping subscriptions, one category dominating spend), or None if
    nothing stands out. Meant for the bot's /summary command, so it stays fast and
    doesn't nag every time.
    """
    start, end = month_bounds(month)
    txns = sheets_client.get_actual(start_date=start, end_date=end)
    if not txns:
        return None

    lines = [f"{t.get('Date')} - {t.get('Category')} - {t.get('Note')} - {t.get('Amount')}" for t in txns]
    system = (
        "You are a terse personal finance assistant. Given this month's transactions, look "
        "for ONE actionable, concrete observation — e.g. duplicate/overlapping subscriptions "
        "(multiple streaming or software services), one category eating an unusually large "
        "share of spend, or a small recurring charge that adds up. If something clearly "
        "stands out, reply with exactly one short sentence (under 25 words) starting with an "
        "actionable verb (e.g. 'Consider cancelling...'). If nothing stands out, reply with "
        "exactly: None"
    )
    response = get_client().messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=100,
        system=system,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    usage_tracker.record_claude_usage(response.usage.input_tokens, response.usage.output_tokens)
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text or text.lower() == "none":
        return None
    return text


INSIGHTS_TOOL_SCHEMA = {
    "name": "give_insights",
    "description": "Give 3-5 short, concrete spending insights for the dashboard.",
    "input_schema": {
        "type": "object",
        "properties": {
            "insights": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 5,
                "description": (
                    "Each item is one short sentence (under 25 words), concrete and "
                    "specific to the numbers given — e.g. an overspending flag, a habit "
                    "suggestion (overlapping subscriptions, a recurring small leak), or "
                    "positive reinforcement where something is going well. No generic advice."
                ),
            }
        },
        "required": ["insights"],
    },
}


def dashboard_insights(month: str) -> list[str]:
    """3-5 short, concrete insights for the web dashboard's on-demand AI Insights
    card. Same spirit as the bot's quick_tip() but returns multiple structured
    items via forced tool-calling instead of one free-text line."""
    rows = compute_variance(month)
    if not rows:
        return []

    user_prompt = _build_prompt(month, rows)
    system = (
        "You are a supportive but direct personal finance coach. The user's goals are to pay "
        "off debt, build savings, and gain more freedom to pursue their own life priorities. "
        "Call give_insights exactly once with 3-5 short, concrete, numbers-grounded insights."
    )
    response = get_client().messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[INSIGHTS_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "give_insights"},
    )
    usage_tracker.record_claude_usage(response.usage.input_tokens, response.usage.output_tokens)
    for block in response.content:
        if block.type == "tool_use" and block.name == "give_insights":
            return block.input.get("insights", [])
    return []


def generate_and_save_report(month: str) -> dict:
    report_text = generate_monthly_report(month)
    row = {
        "Month": month,
        "GeneratedAt": now_str(),
        "ReportText": report_text,
        "ModelUsed": settings.CLAUDE_MODEL,
    }
    sheets_client.append_report(row)
    try:
        cache_dir = settings.REPORTS_CACHE_DIR / sheets_client.get_current_sheet_id()
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{month}.md").write_text(report_text, encoding="utf-8")
    except OSError:
        pass
    return row
