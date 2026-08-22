# Changelog

## 0.4.7 — real login page instead of the browser's Basic Auth popup

- **New login page** (`/login`) replaces the raw browser Basic Auth prompt:
  username + password fields, a proper session cookie (signed with a
  random key generated once and persisted in the add-on's data volume —
  never typed by anyone, never in git), a "Forgot your password?" note
  pointing at the add-on's own Configuration tab (the only place the
  password is actually stored), and a 30-day session so you're not asked
  to sign in on every visit.
- **New optional `dashboard_username` config option** — if left blank, the
  login page accepts any username alongside the correct password (same
  behavior as before). Both username and password are compared with
  constant-time comparison, same as the old Basic Auth check.
- **Login attempts are rate-limited**: 5 failed attempts from the same
  source lock out further attempts for 30 seconds, blunting brute-force
  guessing now that login goes through a real form instead of the
  browser's own auth dialog.
- Local dev behavior is unchanged: with no `dashboard_password` set (the
  default when not running under Home Assistant), every page loads
  directly with no login screen at all, same as before.

## 0.4.6 — full infrastructure review: 10 fixes (security, races, reliability)

A user-requested full review across security, every file, and architecture
(5 parallel agents + manual verification of every finding before fixing).
All 10 confirmed findings fixed:

- **CSRF bypass via `Origin: null`**: the cross-origin check only rejected
  requests when the parsed origin host was truthy, so a sandboxed-iframe
  auto-submit (which sends the literal `Origin: null`) parsed to an empty
  string and slipped through unchecked. Now a present-but-mismatched
  (including empty/unparseable) origin is always rejected.
- **CSRF check was POST-only**: GET routes, including `/api/insights` (a
  real, billed Claude API call), had zero cross-site protection. Now
  checked on every method.
- **Debug-mode exposure**: Werkzeug's debugger (arbitrary code execution)
  was gated only on `RUNNING_UNDER_HOME_ASSISTANT`, not on whether the app
  was actually bound to loopback — setting `WEB_BIND_HOST=0.0.0.0` for
  local LAN testing without going through HA would have silently exposed
  it. Now also checks the bind host.
- **Report-generation rate limit was bypassable**: keyed per-month, so
  requesting a different month each time skipped the cost-abuse cooldown
  entirely. Now a single global key, matching how `/api/insights` already
  worked.
- **Bulk-delete on Categories still did one Sheets round trip per
  category** — the exact slowness pattern just fixed for Budgets Save,
  missed on its sibling page. New `deactivate_categories_batch` /
  `remove_categories_batch` (the latter via a real Sheets `batchUpdate`
  with multiple `deleteDimension` requests in one call) fix it the same
  way.
- **Race conditions in this session's own new batched writes**:
  `update_categories_batch` and `upsert_planned_batch` each read row
  positions once and wrote to them later with no lock — a concurrent
  write from the bot process (which shares nothing in memory with the web
  process) could land on a since-shifted row, or two overlapping saves
  could both decide a category was "new" and both append a duplicate row.
  Fixed with a cross-process file lock (`fcntl.flock`, no-op on Windows
  local dev) serializing every Categories/Planned batch write.
- **Budgets form silently dropped edits after a category rename**: the
  POST handler re-fetched current category names and looked for form
  fields keyed by them, but the submitted form was rendered under
  whatever names were current at page-load time — a rename in another
  tab meant that category's edit vanished with no error, and the page
  still reported "Budgets saved." Now reads the submitted fields directly
  and reports exactly which ones were skipped instead of claiming
  false success.
- **`/correct category <value>` wrote an unvalidated category name** —
  the same bug class as the income-miscategorization fix in 0.4.5, just
  through a second, unpatched entry point (the manual correction command
  instead of the automatic Claude-parsed path). Now validated the same
  way, with casing normalized on a match.
- **Any single process crash killed the whole add-on container**:
  `run_supervisor.py` used to call `shutdown(1)` — killing both bot and
  web — the instant either one exited for any reason, including a
  transient network blip. Now restarts just the failed process in place,
  only giving up (and letting Docker/Supervisor restart the container)
  after 5 restarts within 60 seconds of the same process.

## 0.4.5 — fixed a real income-miscategorization bug

- **Root-caused "income doesn't show on the dashboard"**: a logged income
  transaction ("Earn 78,000 in Salary...") got written under Category =
  "Salary", which isn't an actual category — the two real Income categories
  are "Fixed Income" and "Additional Income". Because the dashboard (and
  budgets, and variance reports) only count a transaction as income when its
  Category's Type is exactly "Income", an unrecognized category name falls
  through and gets silently counted as an ordinary **expense** instead.
  Corrected the one existing transaction to "Fixed Income".
- **Fixed why this could happen at all**: the bot trusted Claude's own
  `category_is_new` flag at face value. Claude can judge a category "close
  enough" to an existing one and report `category_is_new: false` while
  still returning a category string that doesn't literally match anything
  (here, "Salary" instead of "Fixed Income") — silently orphaning the
  transaction from every Type-based rollup with no confirmation prompt and
  no error. `bot/handlers.py::_resolve_category` is now the actual
  authority: it checks the model's category string against the real active
  category list itself (case-insensitively, normalizing casing on a match)
  instead of trusting the model's self-report. A category that doesn't
  really exist now always triggers the existing "isn't an existing
  category — create it?" confirmation, regardless of what Claude claimed.

## 0.4.4 — fixed slow Save, site-wide toasts, budget sections, two data bugs

- **Fixed the slow `/budgets` Save**: it was doing a read-then-write Google
  Sheets API round trip *per category* (roughly 2×29 = 58 sequential API
  calls for a full save). New `sheets_client.upsert_planned_batch` /
  `update_categories_batch` do it in a fixed 2-4 calls total — one read,
  one batched cell update, one batched append for brand-new rows — instead
  of one per category. A full save dropped from tens of seconds to about
  2.5s in testing.
- **Site-wide save/delete/add feedback**: every mutating action now shows a
  top-right toast — "Saving…" the instant you click (no AJAX rewrite
  needed: the browser keeps rendering the current page, toast included,
  until the next one is ready), then "✓ done" or "✕ failed with a reason"
  once the destination page loads. Every Categories and Budgets route now
  returns through one `_status_redirect` helper instead of a bare redirect,
  so nothing fails silently anymore.
- **Budgets grouped into sections with totals**: categories are now grouped
  by Type (Income, Expense, Debt, Savings, ...) with each section showing
  its own total, plus an Income / Outflow / Net summary at the top — Income
  counted as inflow and everything else as outflow, matching the sign
  convention the dashboard's own Net figure already uses.
- **Fixed a real bug found while building the above**: the section grouping
  was first written against an assumed 4-value Type enum (Expense/Income/
  Savings/Debt), but the live sheet actually has 5 distinct values —
  "Variable Expense" and "Fixed Expense" instead of a plain "Expense". The
  fixed list would have silently dropped 15 categories off the Budgets page
  entirely. Fixed to group by whatever Type values are actually present.
- **Fixed a related data-loss risk on the Categories page**: the Type
  dropdown only ever offered 4 canonical options, so a row whose real Type
  was "Variable Expense" or "Fixed Expense" showed none selected — clicking
  Save on that row without touching Type would have silently downgraded it
  to plain "Expense". The dropdown now preserves the real value as its own
  option when it isn't one of the 4. Type badges are also color-coded
  correctly for these values now (previously fell back to unstyled, since
  "Variable Expense" produced an invalid two-token CSS class).

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
