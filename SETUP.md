# Setup

## 1. Telegram bot

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts → copy the bot token.
2. Message **@userinfobot** → it replies with your numeric Telegram user ID.

## 2. Google Sheet + service account

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project (or reuse one).
2. APIs & Services → Library → enable **Google Sheets API** and **Google Drive API**.
3. APIs & Services → Credentials → Create Credentials → **Service Account**. Give it any name, no roles needed.
4. Open the service account → Keys → Add Key → JSON. Downloads a `.json` file.
5. Move that file to `data/credentials/service_account.json` in this project.
6. Create a new Google Sheet (sheets.new). Copy the ID from the URL:
   `https://docs.google.com/spreadsheets/d/`**`<SHEET_ID>`**`/edit`
7. Click **Share** on the sheet and share it with the service account's email address
   (looks like `something@your-project.iam.gserviceaccount.com`, found in the JSON file's
   `client_email` field) as **Editor**.

## 3. Anthropic API key

Get a key from [console.anthropic.com](https://console.anthropic.com/).

## 4. Configure

```bash
cp .env.example .env
```

Fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `GOOGLE_SHEET_ID`,
`ANTHROPIC_API_KEY` (leave `GOOGLE_SERVICE_ACCOUNT_FILE` as the default path).

## 5. Install & initialize

```bash
pip install -r requirements.txt
python scripts/init_sheet.py
```

This creates the 5 tabs (`Categories`, `Planned`, `Actual`, `RawLog`, `Reports`) with headers.
Open the sheet and add a few starter rows to `Categories` (e.g. `Groceries`, `Expense`, `TRUE`),
or just add them from the bot/website once it's running.

## 6. Run

In two terminals:

```bash
python scripts/run_bot.py
```

```bash
python scripts/run_web.py
```

Then open http://127.0.0.1:5000 and message your bot on Telegram.

## 7. Deploying to a server

See [DEPLOY.md](DEPLOY.md) for running this on a real server (e.g. Oracle Cloud's
Always Free tier) as two systemd services behind a TLS-terminating reverse proxy.
