# Personal Finance Tracker

Log planned vs. actual spending by texting a Telegram bot; review and manage everything
from a local dashboard; get a Claude-generated monthly spending analysis.

- **Storage**: a single Google Sheet (`Categories`, `Planned`, `Actual`, `RawLog`, `Reports` tabs)
- **Logging**: Telegram bot, long-polling, whitelisted to one user, parses free text via Claude
- **Dashboard**: local Flask app — set budgets, manage categories, view/generate reports, export data

See [SETUP.md](SETUP.md) to get running (Telegram bot token, Google service account, Anthropic
API key, then `python scripts/init_sheet.py`).

## Running

```bash
python scripts/run_bot.py    # Telegram bot (long polling)
python scripts/run_web.py    # dashboard at http://127.0.0.1:5000
```

## Bot commands

- Just text a transaction: `spent 12.50 on coffee at starbucks`
- `/undo` — remove the last transaction
- `/correct <field> <value>` — fix the last transaction (`amount`, `category`, `note`, `date`)
- `/categories` — list active categories
- `/addcategory <name> <type>` — add a category (`Expense`/`Income`/`Savings`/`Debt`)
