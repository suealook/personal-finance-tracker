# Changelog

## 0.1.1

- Fix `s6-overlay-suexec: fatal: can only run as pid 1` on start — the
  Dockerfile now explicitly sets `ENTRYPOINT ["/init"]` instead of relying on
  the base image's default.

## 0.1.0

- Initial release: Telegram bot + web dashboard as a Home Assistant add-on, with
  an in-app `/update` page showing bot/web/Sheets status and a one-click update
  via the Supervisor API.
