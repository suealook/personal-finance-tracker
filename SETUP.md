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

## 7. Deploying to Home Assistant OS (Raspberry Pi)

This runs as a real Home Assistant local Add-on rather than a bare Docker container,
since HAOS has no general systemd environment — Supervisor manages everything as
containers.

1. **Push this repo to GitHub.** Create a private repo on github.com, then from
   this project:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/<you>/<your-repo>.git
   git branch -M main
   git push -u origin main
   ```
2. Edit `repository.yaml` and `ha-addon/config.yaml`'s `url:` field to point at
   your actual repo URL, then commit/push again.
3. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ (top right) →
   Repositories** → paste your GitHub repo URL → Add.
4. Find "Personal Finance Tracker" in the store and install it.
5. Open its **Configuration** tab and fill in the same values as `.env` above
   (paste the *entire* service-account JSON as the `google_service_account_json`
   field — HA's config form can't upload files), plus a **`dashboard_password`**
   — required here (unlike local dev): the dashboard binds to your whole LAN
   under Home Assistant, and the add-on refuses to start without one.
6. Start the add-on. Check its **Log** tab for both the bot and web processes
   starting cleanly.
7. Open `http://<your-ha-ip>:5000` — the dashboard's own **Update** page shows
   live bot/web/Sheets status from here on, plus a one-click update once you've
   published a newer version (see below).
8. **Publishing an update later**: make your code changes, run
   `python ha-addon/sync_app.py` to refresh the mirrored copy the Docker build
   uses (see the comment at the top of that file for why this step exists), bump
   the `version:` in `ha-addon/config.yaml`, commit everything (including the
   regenerated `ha-addon/app/`), and push. Then either refresh the Add-on Store
   in HA or click **Update** on the dashboard's `/update` page.

See [ha-addon/DOCS.md](ha-addon/DOCS.md) for the add-on's own reference doc (also
shown in its Documentation tab once installed).
