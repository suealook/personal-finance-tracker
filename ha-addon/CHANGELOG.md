# Changelog

## 0.4.3 — budgets page gets the same table treatment as categories

- `/budgets` now uses the same real-table-above-phone-width layout as the
  categories page (0.4.2), instead of always card-stacking: category name is
  visually primary, Group is a muted secondary field (same `.group-input`
  style as categories, reused rather than redefined), and the table uses
  `table-layout: fixed` with percentage columns so it can never overflow its
  container. The shared plumbing (`.data-table`, the card-stack breakpoint)
  moved out of the categories-only CSS into one place both pages draw from.
- Fixed a regression caught before shipping, not after: the new generic
  "inputs fill their table cell" rule would have also stretched the
  budgets page's +/−/×/÷ calculator's number field to the full column width,
  breaking its layout — excluded via `:not(.calc-input)` so the calculator
  keeps its fixed width on both pages.

## 0.4.2 — simplified budgets table + categories UX overhaul

- **`/budgets` reverted to a flat table**: the 0.4.1 grouped-card layout (per-
  group sections, live subtotals, inline quick-add) was more different from
  the rest of the app than it needed to be. Back to one table — Category,
  Group, Planned amount — where Group is just an editable column value, not
  a section. Renaming/adding/removing categories now happens only on the
  Categories page, so there's one place responsible for category identity
  instead of two.
- **Categories page redesigned for actual desktop use, not just fixed
  again**: the table was rendering as ~35 tall stacked cards on every screen
  size (the 0.3.1 "always stack" fix traded the horizontal-scroll bug for a
  very long vertical scroll on desktop). It's now a real compact table above
  the phone breakpoint:
  - Active/Inactive collapses from three separate controls (a status column
    plus Deactivate *and* Activate buttons) into one colored status pill —
    click it to toggle.
  - Type is a color-coded badge instead of a plain dropdown, so a row's kind
    (Expense/Income/Savings/Debt) reads at a glance.
  - The category name is visually primary; Group and Notes are visually
    secondary (smaller, muted) so the row doesn't shout equally everywhere.
  - Per-row Save stays dimmed until that row actually has an unsaved edit,
    instead of 35 equally-loud Save buttons on an untouched page.
  - The table uses `table-layout: fixed` with percentage columns rather than
    letting content dictate width — this is the actual fix for the
    horizontal-scroll bug across *all* three previous attempts (0.2.0 wider
    breakpoint, 0.3.1 "always stack"): the table's rendered width can now
    never exceed its container at any viewport size, so there's no
    in-between width left to overflow at. Below ~780px it still card-stacks,
    matching how every other table in the app already behaves on phones.

## 0.4.1 — bottom-up sub-category budgets

- `/budgets` now clusters categories under their existing `Group` tag (the
  same field that already powers the dashboard's group rollup), with a
  live, client-side bottom-up total per group that updates as you type or
  use the inline calculator.
- Each group gets an inline "+ Add" quick-form (pre-filled with that
  group's dominant Type) and a per-row remove button, both reusing the
  existing add/deactivate routes — no new category-management logic.
- New capability that didn't exist anywhere before: renaming a category
  (`common/categories.py::rename_category`, `POST /categories/rename`).
  Like removing a category, it only affects new activity going forward —
  existing Planned/Actual/RawLog rows keep the old name text.

## 0.4.0 — five convenience features

- **Receipt photo logging**: send the bot a photo of a receipt (with or
  without a caption) and it logs the transaction the same way a text
  message would — same tool schema, same category-confirmation flow.
  `common/llm_parse.py` refactored so text and photo parsing share one
  system-prompt builder and one extraction/usage-tracking call, instead of
  duplicating either.
- **Inline Undo button**: every transaction confirmation now carries a
  one-tap Undo button, keyed to that specific transaction's ID (not
  "whatever's last") so it stays correct even if you log something else
  before tapping it.
- **Copy last month's budgets**: one button on `/budgets` clones the
  previous month's planned amounts into the selected month, behind a
  confirm dialog since it overwrites.
- **Add to Home Screen**: a proper web manifest + generated icons, so the
  dashboard can be added as a home-screen app on phones.
- **Telegram command menu**: `/help` and Telegram's native "/" command menu
  now both read from one command table in `bot/telegram_bot.py`, so they
  can't drift out of sync with each other.

## 0.3.1

- **Actually fix** the categories page horizontal scroller (3rd attempt): the
  card-stacking layout no longer depends on a viewport-width breakpoint at
  all — it always stacks, at any screen size, so there's no threshold left
  to mistune.
- Static CSS is now served with a content-hash query string
  (`style.css?v=<hash>`), so a browser that cached an old copy is guaranteed
  to refetch after an update — a stale cache was a real candidate for why
  earlier CSS fixes didn't visibly land.
- Categories page: added multi-select checkboxes + a "Delete selected"
  button with a confirm dialog. Matches the existing per-row semantics —
  active categories are deactivated (reversible), already-inactive ones are
  permanently removed.

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
