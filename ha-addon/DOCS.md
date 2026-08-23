# Personal Finance Tracker

Logs planned vs. actual spending via a Telegram bot, with a local dashboard and
Claude-generated monthly/on-demand insights. Everything is stored in a Google
Sheet you control.

## Before you install

You need, from the app's [SETUP.md](../SETUP.md):
1. A Telegram bot token and your numeric Telegram user ID.
2. A Google Cloud service account with Sheets + Drive API access, shared as
   Editor on a Google Sheet you've created, plus that Sheet's ID.
3. An Anthropic API key.

## Configuration

Fill in the add-on's Configuration tab:

| Option | What it is |
|---|---|
| `telegram_bot_token` | From @BotFather |
| `telegram_allowed_user_id` | Your numeric Telegram user ID (from @userinfobot) — the bot ignores everyone else |
| `google_sheet_id` | The ID from your Google Sheet's URL |
| `google_service_account_json` | Paste the **entire contents** of your service account's JSON key file |
| `anthropic_api_key` | From console.anthropic.com |
| `claude_model` | Defaults to `claude-sonnet-5` |
| `dashboard_password` | **Required.** The dashboard binds to all network interfaces under Home Assistant (reachable from your whole LAN, not just this device), so the add-on refuses to start without one. Pick any password — the browser will prompt for it (any username, that password) the first time you visit. |

Then start the add-on. On first start, run `python scripts/init_sheet.py`-equivalent
setup once (see the main SETUP.md) if the Sheet's tabs haven't been created yet.

## Using it

- The web dashboard is at `http://<your-ha-ip>:5000` — your browser will prompt
  for the `dashboard_password` you set above (Basic Auth; any username works).
- The `/update` page in the dashboard shows live status for the web service, the
  Telegram bot (via a heartbeat, refreshed every 30s), the Google Sheets
  connection, and a running Claude API cost estimate (in THB), plus a one-click
  Update button once a new version is published to this add-on's repository.
- Logs for both the bot and web processes appear in this add-on's **Log** tab.

## Security notes

- The dashboard requires `dashboard_password` (HTTP Basic Auth) and rejects
  cross-origin form submissions — but Basic Auth credentials are cached by the
  browser per-origin, so still don't port-forward this add-on's port to the
  public internet. It's designed for LAN-only access via Home Assistant.
- Every transaction/category text field is written to Google Sheets with
  spreadsheet-formula injection neutralized (a value starting with `=`, `+`,
  `-`, or `@` is stored as literal text, never evaluated as a formula).
- Monthly report text (Claude-generated, rendered as HTML) is sanitized
  through an allowlist before display.

## Updating

New versions are published by pushing to the GitHub repo this add-on came from.
Refresh the Add-on Store (or use the dashboard's own `/update` page) to pick up
and install the new version.
