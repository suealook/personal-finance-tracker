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

## 4. Google Sign-In (only needed once the dashboard is reachable by anyone
   besides you — see step 8; skip this for pure local use on 127.0.0.1)

1. In the same GCP project as step 2: APIs & Services → Credentials →
   Create Credentials → **OAuth client ID** → Application type **Web application**.
2. If prompted, configure the OAuth consent screen first — External, Testing
   mode is fine for a small allowlisted group.
3. Add an **Authorized redirect URI**: `https://<your-domain>/auth/google/callback`.
   Google's console rejects a bare IP address here — you need an actual
   domain (a free one from [DuckDNS](https://www.duckdns.org/) works fine;
   see [DEPLOY.md](DEPLOY.md) if you're deploying to a VM without one yet).
   Local dev is the one exception: `http://127.0.0.1:5000/auth/google/callback`
   is allowed as-is, no domain needed.
4. Copy the generated **Client ID** and **Client secret**.

## 5. Configure

```bash
cp .env.example .env
```

Fill in `TELEGRAM_BOT_TOKEN`, `GOOGLE_SHEET_ID`, `ANTHROPIC_API_KEY` (leave
`GOOGLE_SERVICE_ACCOUNT_FILE` as the default path). Fill in
`GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` from step 4 if you did it.

Create `data/users.json` — who's allowed to use this deployment:

```json
[
  {
    "email": "you@gmail.com",
    "sheet_id": "<your GOOGLE_SHEET_ID from above>",
    "telegram_user_id": "<your numeric Telegram user ID from step 1>",
    "label": "You"
  }
]
```

`email` is the Google account you'll sign in with on the dashboard;
`telegram_user_id` is who the shared bot will respond to as this person;
`sheet_id` is which sheet their data reads from and writes to. Add more
entries later for more people — see [DEPLOY.md](DEPLOY.md)'s onboarding
checklist.

## 6. Install & initialize

```bash
pip install -r requirements.txt
python scripts/init_sheet.py
```

This creates the 5 tabs (`Categories`, `Planned`, `Actual`, `RawLog`, `Reports`) with headers.
Open the sheet and add a few starter rows to `Categories` (e.g. `Groceries`, `Expense`, `TRUE`),
or just add them from the bot/website once it's running.

## 7. Run

In two terminals:

```bash
python scripts/run_bot.py
```

```bash
python scripts/run_web.py
```

Then open http://127.0.0.1:5000 and message your bot on Telegram. Locally,
with `GOOGLE_OAUTH_CLIENT_ID` unset, the dashboard has no login gate at all —
same as `DASHBOARD_PASSWORD` being unset used to work.

## 8. Deploying to a server

See [DEPLOY.md](DEPLOY.md) for running this on a real server (e.g. Google
Cloud's Always Free tier) as two systemd services behind a TLS-terminating
reverse proxy — this is the point where Google Sign-In (step 4) actually
matters, since the dashboard becomes reachable by more than just you.
