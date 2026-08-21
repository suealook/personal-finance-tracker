# Changelog

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
