# Personal Finance Tracker

Log planned vs. actual spending by texting a Telegram bot; review and manage everything
from a local dashboard; get a Claude-generated monthly spending analysis.

- **Storage**: a single Google Sheet (`Categories`, `Planned`, `Actual`, `RawLog`, `Reports` tabs)
- **Logging**: Telegram bot, long-polling, whitelisted to one user, parses free text or receipt photos via Claude
- **Dashboard**: local Flask app — set budgets, manage categories, view/generate reports, export data

See [SETUP.md](SETUP.md) to get running (Telegram bot token, Google service account, Anthropic
API key, then `python scripts/init_sheet.py`).

## Running

```bash
python scripts/run_bot.py    # Telegram bot (long polling)
python scripts/run_web.py    # dashboard at http://127.0.0.1:5000
```

## Bot commands

- Text a transaction (`spent 12.50 on coffee at starbucks`) or send a photo of a receipt — either logs it, with a tap-to-Undo button on the confirmation
- `/undo` — remove the last transaction
- `/correct <field> <value>` — fix the last transaction (`amount`, `category`, `note`, `date`)
- `/categories` — list active categories
- `/addcategory <name> <type>` — add a category (`Expense`/`Income`/`Savings`/`Debt`)
- `/summary` — month-to-date income and spending

Commands also show up in Telegram's native "/" menu (set from the same table as the
handlers in `bot/telegram_bot.py`, so it can't drift).
