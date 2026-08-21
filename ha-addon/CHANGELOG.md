# Changelog

## 0.3.0 — security hardening + usage/cost tracking

Full audit found the dashboard had **no authentication at all** while being
network-exposed (binds to 0.0.0.0 under HA) — the most important fix here.

- **Auth required under HA**: new `dashboard_password` config option, HTTP
  Basic Auth on every route. The add-on now refuses to start under Home
  Assistant if it's not set (fail-closed). Optional for local dev
  (127.0.0.1-only, trusted).
- **CSRF protection**: state-changing POST requests are rejected if their
  Origin/Referer doesn't match the dashboard's own host.
- **Google Sheets formula-injection fix**: any text written to a cell that
  starts with `=`, `+`, `-`, or `@` is now stored as literal text (was
  previously written as a live, evaluatable formula).
- **XSS hardening**: monthly report HTML (Claude-generated markdown) is now
  sanitized through an allowlist (`bleach`) before rendering, instead of
  trusting it directly.
- **Rate limiting**: `/api/insights` and `/reports/generate` (the two routes
  that trigger paid Claude API calls) now have a 10s cooldown to blunt
  automated cost-abuse.
- **Usage & cost tracking**: the `/update` page now shows cumulative Claude
  API token usage with an estimated cost in USD and THB, plus a Google
  Sheets API call count (free — shown as activity, not cost).
- Not fixed this round: container still runs as root (lower severity given
  Supervisor's own sandboxing; deferred to avoid another permission-mapping
  guessing game after the s6-overlay saga in earlier versions).

## 0.2.0

- Categories page: widened the mobile-card breakpoint from 640px to 900px —
  it was still falling back to a horizontally-scrolling table at in-between
  widths (tablets, resized browser windows).
- Budgets page: added an inline +/−/×/÷/= calculator next to each category's
  planned-amount field, so you can build up a number (e.g. rent + utilities)
  without doing the math elsewhere first. Click Save as usual once you're
  happy with the number.

## 0.1.4

- Fix `python-telegram-bot[job-queue]` extra missing from `requirements.txt` —
  APScheduler wasn't installed in the container, so the bot's heartbeat job
  silently never ran (logged as a `PTBUserWarning`), leaving the `/update`
  page's Bot status permanently "Unknown" there. Config loading is confirmed
  working as of 0.1.3 (unrelated to this).

## 0.1.3

- The custom supervisor works, but `TELEGRAM_BOT_TOKEN` came back empty even
  though Configuration was filled in. Added a one-time startup diagnostic
  line (presence/absence only, never values) to `config/settings.py` to see
  exactly what `/data/options.json` looks like at runtime instead of guessing.

## 0.1.2

- Replace s6-overlay service supervision with a small custom Python
  supervisor (`run_supervisor.py`). The explicit `ENTRYPOINT ["/init"]` fix in
  0.1.1 did not resolve `s6-overlay-suexec: fatal: can only run as pid 1` —
  rather than keep guessing at base-image-specific s6 conventions with no way
  to test against a real Supervisor from outside, the add-on now starts and
  supervises the bot and web processes itself, with no s6 dependency at all.

## 0.1.1

- Fix `s6-overlay-suexec: fatal: can only run as pid 1` on start — the
  Dockerfile now explicitly sets `ENTRYPOINT ["/init"]` instead of relying on
  the base image's default.

## 0.1.0

- Initial release: Telegram bot + web dashboard as a Home Assistant add-on, with
  an in-app `/update` page showing bot/web/Sheets status and a one-click update
  via the Supervisor API.
