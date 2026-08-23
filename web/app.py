import bleach
import hashlib
import io
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import markdown as markdown_lib
import pandas as pd
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from common import categories as categories_module
from common import gcp_info
from common import google_auth
from common import sheets_client
from common import usage_tracker
from common import users as users_module
from common.dateutil_helpers import current_month, last_n_months, month_bounds, previous_month, year_bounds
from common.heartbeat import heartbeat_age_seconds
from common.llm_analysis import compute_variance, dashboard_insights, generate_and_save_report
from config import settings

SPARKLINE_MONTHS = 6
MAX_GROUP_SLOTS = 6  # + one folded "Other" bucket = 7 visual segments max
LLM_CALL_COOLDOWN_SECONDS = 10  # guards /api/insights and /reports/generate against cost-abuse loops

# Every state-changing route in this app is POST (see the @app.route table)
# except this one -- a GET that triggers a real, billed Claude API call. The
# CSRF check below always covers non-GET/HEAD methods; this is what it
# additionally covers among GETs, by name, instead of blanket-covering every
# GET route including plain reads.
CSRF_PROTECTED_GET_ENDPOINTS = {"api_insights"}

ALLOWED_REPORT_TAGS = [
    "p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "h4",
    "blockquote", "code", "pre", "a", "table", "thead", "tbody", "tr", "th", "td",
]
ALLOWED_REPORT_ATTRS = {"a": ["href", "title"]}

WEB_STARTED_AT = datetime.now(timezone.utc)
BOT_HEARTBEAT_RUNNING_SECONDS = 90    # < this since last heartbeat: bot is fine
BOT_HEARTBEAT_STALE_SECONDS = 180     # < this: bot may be restarting/hung; >= this: not responding

# stat-value's CSS only defines .good/.warning/.bad — statuses speak "critical"
# (matching the nav bar's status-badge, which does support that name), so this
# translates for the one component that needs it instead of duplicating the
# state strings themselves.
_STATE_CSS = {"good": "good", "warning": "warning", "critical": "bad", "unknown": ""}

_last_llm_call_at: dict[str, float] = {}


def _llm_rate_limited(key: str) -> bool:
    """True if this key's last call was too recent — used to blunt cost-abuse
    loops against the two routes that trigger real Anthropic API calls."""
    now = time.time()
    if now - _last_llm_call_at.get(key, 0.0) < LLM_CALL_COOLDOWN_SECONDS:
        return True
    _last_llm_call_at[key] = now
    return False


def _authority(netloc: str, scheme: str) -> str:
    """Lowercased host[:port] with the scheme's own default port stripped, so
    "example.com" and "example.com:443" compare equal for https (and
    likewise :80 for http) — browsers never put a default port in an Origin
    header, but a "host[:port]" value arriving via a reverse proxy's
    X-Forwarded-Host isn't guaranteed to omit one. Comparing without this
    normalization is a real, reachable false-positive: Caddy sits in front
    of this app in every real deployment (see ProxyFix below), so the
    request side of the comparison always goes through a header whose exact
    port formatting isn't this app's to assume."""
    host = netloc.lower()
    default_port = {"https": "443", "http": "80"}.get(scheme)
    if default_port and host.endswith(f":{default_port}"):
        host = host[: -(len(default_port) + 1)]
    return host


def _safe_next_url(next_url: str) -> Optional[str]:
    """Only a same-site relative path is safe to redirect to post-login —
    never an attacker-suppliable absolute or protocol-relative URL, which
    would turn the login flow into an open-redirect phishing vector."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return None


def _bot_status() -> dict:
    age = heartbeat_age_seconds("bot")
    if age is None:
        return {"state": "unknown", "label": "Unknown", "detail": "No heartbeat recorded yet."}
    if age < BOT_HEARTBEAT_RUNNING_SECONDS:
        return {"state": "good", "label": "Running", "detail": f"Last heartbeat {int(age)}s ago."}
    if age < BOT_HEARTBEAT_STALE_SECONDS:
        return {"state": "warning", "label": "Stale", "detail": f"Last heartbeat {int(age)}s ago."}
    return {"state": "critical", "label": "Not responding", "detail": f"Last heartbeat {int(age)}s ago."}


def _sheets_status() -> dict:
    try:
        spreadsheet = sheets_client.get_spreadsheet()
        return {"state": "good", "label": "Connected", "detail": spreadsheet.title}
    except Exception as e:
        return {"state": "critical", "label": "Not connected", "detail": str(e)}


def _gather_status() -> dict:
    """Every live check the Status page shows, gathered in one place so
    landing on the page and clicking "Retrieve status" run the exact same
    code path — nothing polls this on an interval, it only ever runs on a
    page load or an explicit click, to keep Sheets/metadata-server calls to
    a minimum."""
    web = {
        "state": "good",
        "label": "Running",
        "detail": f"Up since {WEB_STARTED_AT.strftime('%Y-%m-%d %H:%M UTC')}",
    }
    bot = _bot_status()
    sheets = _sheets_status()
    vm = gcp_info.get_vm_status()
    for status in (web, bot, sheets, vm):
        status["css"] = _STATE_CSS.get(status["state"], "")
    return {
        "web_status": web,
        "bot_status": bot,
        "sheets_status": sheets,
        "vm_status": vm,
        "cost_estimate": gcp_info.get_cost_estimate(),
        "claude_usage": usage_tracker.get_claude_usage_summary(),
        "sheets_call_count": sheets_client.get_sheets_call_count(),
        "claude_model": settings.CLAUDE_MODEL,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _income_and_spend(txns: list[dict], cat_types: dict[str, str]) -> tuple[float, float]:
    income = 0.0
    spend = 0.0
    for t in txns:
        amt = float(t.get("Amount") or 0)
        if cat_types.get(t.get("Category", "")) == "Income":
            income += amt
        else:
            spend += amt
    return income, spend


def _status_redirect(endpoint: str, message: str, status: str = "success", **url_kwargs):
    """Redirect carrying a status+message for the site-wide toast (base.html)
    to show once the destination page loads. Every mutating route (Save,
    Add, Delete, ...) should return through this instead of a bare
    redirect(), so the user always gets a clear success/failure signal
    instead of a silent page refresh."""
    return redirect(url_for(endpoint, status=status, message=message, **url_kwargs))


def _build_budget_sections(active_records: list[dict], planned_rows: dict[str, float]) -> list[dict]:
    """Groups active categories by Type into the Budgets page's sections, each
    with its own planned-amount total. Category order within a section
    follows the existing priority order from the Categories page.

    Groups by whatever Type values actually appear on active categories,
    rather than a fixed 4-value list — the live sheet can (and does) carry
    Type strings the add/edit forms' dropdown doesn't offer (e.g. "Variable
    Expense" / "Fixed Expense" instead of "Expense"), and a fixed list would
    silently drop every category with an unrecognized Type off the page
    entirely. Income sorts first since it's the inflow section everything
    else is budgeted against; the rest sort alphabetically after it."""
    by_type: dict[str, list[dict]] = {}
    for c in active_records:
        by_type.setdefault(c.get("Type") or "Other", []).append(c)

    def section_order(type_name: str):
        return (0, "") if type_name == "Income" else (1, type_name)

    sections = []
    for type_name in sorted(by_type, key=section_order):
        cats = by_type[type_name]
        total = sum(float(planned_rows.get(c["Category"], 0) or 0) for c in cats)
        sections.append({"type": type_name, "categories": cats, "total": total})
    return sections


def _delta_class(delta: float, up_is_good: bool) -> str:
    if delta == 0:
        return "neutral"
    is_up = delta > 0
    return "good" if (is_up == up_is_good) else "bad"


def _build_group_segments(group_totals: dict[str, dict[str, float]]) -> list[dict]:
    """Part-to-whole segments for the spending-by-group bar. Color slots are
    assigned by alphabetical order (a stable identity), not by this month's
    ranking, so a given group keeps its color across months even as amounts
    change. Display order is still by size (largest first). Beyond
    MAX_GROUP_SLOTS distinct groups, the smallest are folded into "Other"."""
    entries = [(g, v["actual"]) for g, v in group_totals.items() if v["actual"] > 0]
    if not entries:
        return []
    slot_for = {g: idx for idx, g in enumerate(sorted(name for name, _ in entries))}

    entries.sort(key=lambda e: e[1], reverse=True)
    if len(entries) > MAX_GROUP_SLOTS + 1:
        kept = entries[:MAX_GROUP_SLOTS]
        other_total = sum(v for _, v in entries[MAX_GROUP_SLOTS:])
        entries = kept + [("Other", other_total)]

    total = sum(v for _, v in entries)
    segments = []
    for name, value in entries:
        idx = slot_for.get(name)
        slot_class = f"slot-{idx + 1}" if idx is not None else "slot-other"
        segments.append(
            {"group": name, "actual": value, "pct": round((value / total) * 100, 1), "slot": slot_class}
        )
    return segments


def _build_donut_segments(group_segments: list[dict]) -> list[dict]:
    """Adds cumulative start/end percentages (for a CSS conic-gradient) and
    the matching --series-N custom property name to each segment, so the
    template builds one donut chart without doing running-total math or
    slot-to-color lookups in Jinja."""
    segments = []
    cursor = 0.0
    for seg in group_segments:
        start = cursor
        cursor += seg["pct"]
        color_var = seg["slot"].replace("slot-", "--series-")
        segments.append({**seg, "start_pct": round(start, 3), "end_pct": round(cursor, 3), "color_var": color_var})
    return segments


def create_app() -> Flask:
    # Fail-closed tied to actual network exposure, not an environment guess:
    # anything other than loopback-only means the dashboard is reachable by
    # someone other than this machine (LAN or public internet), so it must
    # not run without Google Sign-In configured and at least one allowed user.
    not_loopback = settings.WEB_BIND_HOST not in ("127.0.0.1", "localhost")
    if not_loopback and not (settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET):
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET are not set. The "
            f"dashboard is bound to {settings.WEB_BIND_HOST!r} (not loopback-only), "
            "so it must not run without Google Sign-In configured. See SETUP.md."
        )
    if not_loopback and not users_module.any_users_configured():
        raise RuntimeError(
            "No users configured in data/users.json. The dashboard is bound to "
            f"{settings.WEB_BIND_HOST!r} (not loopback-only), so it must not run "
            "without at least one allowed user. See SETUP.md."
        )

    app = Flask(__name__)
    app.secret_key = settings.FLASK_SECRET_KEY
    app.permanent_session_lifetime = timedelta(days=3)

    # Caddy proxies to this Flask process over plain HTTP on loopback (see
    # deploy/Caddyfile) and sets X-Forwarded-Proto/Host (its default
    # reverse_proxy behavior) — trust exactly one hop of those so
    # url_for(_external=True) reports https and the real host instead of
    # Flask's own view of the connection. Deliberately NOT conditioned on
    # WEB_BIND_HOST: per this deployment's design, Flask stays loopback-bound
    # even in production (Caddy is what's actually reachable from the
    # internet), so a not_loopback check here would never fire — the same
    # trap FLASK_DEBUG above already had to be rewritten to avoid. Always
    # applying this is safe: without an actual proxy in front (local dev),
    # the X-Forwarded-* headers simply aren't present and it's a no-op.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Same reasoning — tied to whether Google Sign-In is configured (the
    # real "this is a live deployment, not local dev" signal) rather than
    # bind host, which stays loopback here even in production.
    if settings.GOOGLE_OAUTH_CLIENT_ID:
        app.config["SESSION_COOKIE_SECURE"] = True

    # Cache-busting for static assets: without this, style.css is served from a
    # fixed URL forever, so a browser that already cached an old copy has no
    # signal to ever refetch it after an update. Hashing the file content means
    # the URL only changes when the CSS actually does.
    css_path = Path(app.static_folder) / "style.css"
    try:
        app.jinja_env.globals["asset_version"] = hashlib.sha256(css_path.read_bytes()).hexdigest()[:10]
    except OSError:
        app.jinja_env.globals["asset_version"] = str(int(WEB_STARTED_AT.timestamp()))

    # Just whether Google Sign-In is configured, never any secret — lets
    # base.html show/hide the Log out button without templates touching
    # settings directly.
    app.jinja_env.globals["auth_enabled"] = bool(settings.GOOGLE_OAUTH_CLIENT_ID)

    @app.context_processor
    def _inject_bot_status():
        # Powers the nav bar's live status badge on every page — reuses the
        # same heartbeat-age logic the /update page already shows in detail.
        return {"nav_bot_status": _bot_status()}

    @app.before_request
    def _security_gate():
        # CSRF: reject cross-origin requests on every state-changing method
        # (POST/PUT/DELETE/PATCH — every one of them in this app), plus the
        # one named GET route that isn't safe (CSRF_PROTECTED_GET_ENDPOINTS
        # above). Deliberately NOT every GET: a plain read (the dashboard,
        # /budgets, /categories, ...) has nothing for a forged cross-site
        # request to gain by hitting it, and blanket-checking every GET is
        # what caused a real false-positive here — a browser tags the Origin
        # header as the literal string "null" on a request that's the tail
        # end of a redirect chain that crossed an origin boundary anywhere
        # earlier in that chain (our site -> Google -> our own callback ->
        # our own redirect to "/"), per the Fetch spec's "tainted origin"
        # handling, and that's indistinguishable from the actual attack this
        # check exists for (a sandboxed iframe, which also sends "null").
        # Scoping to where a forged request could actually do something
        # makes that ambiguity irrelevant instead of trying to resolve it.
        # Comparing origin_host != request_host directly (not "if
        # origin_host and...") means a present-but-unparseable Origin is
        # still rejected as a mismatch on the routes this does apply to,
        # rather than silently passing through. A request with neither
        # header at all (plain navigation, most non-browser clients) is
        # still let through unchecked, same as before. Both sides go
        # through _authority() so a default-port formatting difference
        # between the browser's Origin and this app's (proxied) request.host
        # can't produce a false-positive either — see that helper's
        # docstring.
        needs_csrf_check = request.method not in ("GET", "HEAD") or request.endpoint in CSRF_PROTECTED_GET_ENDPOINTS
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        # A real Google redirect back to /auth/google/callback arrives with an
        # external Referer (accounts.google.com) — that's expected there, and
        # that route's own defense against a forged callback is the OAuth
        # `state` parameter it checks itself, not this generic same-site check.
        if needs_csrf_check and origin and request.endpoint != "auth_google_callback":
            parsed_origin = urlparse(origin)
            origin_host = _authority(parsed_origin.netloc, parsed_origin.scheme)
            request_host = _authority(request.host, request.scheme)
            if origin_host != request_host:
                return Response("Cross-origin request rejected.", status=403)

        # Auth: Google Sign-In + signed session cookie, required whenever it's
        # configured (always true once bound beyond loopback, per the
        # fail-closed check above; optional for local dev, which is bound to
        # 127.0.0.1 only). Re-resolves the session's email against
        # data/users.json on every request — not just checking a cookie flag —
        # so removing someone from that file actually revokes their access
        # instead of leaving an old session usable. /login, the OAuth routes,
        # and static assets stay reachable without a session.
        if request.endpoint == "static":
            return
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            # No login gate configured (local dev, matching how an unset
            # DASHBOARD_PASSWORD used to leave the app fully open) — fall
            # back to the single sheet from .env, same as before multi-user
            # accounts existed.
            sheets_client.set_current_sheet(settings.GOOGLE_SHEET_ID)
            return
        if request.endpoint not in ("login", "auth_google_start", "auth_google_callback"):
            user = users_module.get_user_by_email(session.get("user_email", ""))
            if user is None:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Authentication required"}), 401
                next_path = request.full_path if request.query_string else request.path
                return redirect(url_for("login", next=next_path))
            sheets_client.set_current_sheet(user["sheet_id"])

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            return redirect(url_for("dashboard"))
        return render_template("login.html", next=request.values.get("next") or "")

    @app.route("/auth/google/start", methods=["POST"])
    def auth_google_start():
        state = secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        session["oauth_state"] = state
        session["oauth_code_verifier"] = code_verifier
        session["oauth_remember_me"] = bool(request.form.get("remember_me"))
        session["oauth_next"] = request.form.get("next") or ""
        flow = google_auth.build_flow(
            url_for("auth_google_callback", _external=True), state=state, code_verifier=code_verifier
        )
        authorization_url, _ = flow.authorization_url(access_type="online", prompt="select_account")
        return redirect(authorization_url)

    @app.route("/auth/google/callback")
    def auth_google_callback():
        expected_state = session.pop("oauth_state", None)
        code_verifier = session.pop("oauth_code_verifier", None)
        if not expected_state or not code_verifier or request.args.get("state") != expected_state:
            return Response("Invalid or expired sign-in attempt — please try again.", status=400)

        remember_me = session.pop("oauth_remember_me", False)
        next_url = session.pop("oauth_next", "")

        flow = google_auth.build_flow(
            url_for("auth_google_callback", _external=True), state=expected_state, code_verifier=code_verifier
        )
        try:
            claims = google_auth.exchange_code(flow, request.url)
        except Exception:
            app.logger.exception("Google OAuth code exchange failed")
            return Response("Google sign-in failed — please try again.", status=400)

        email = claims.get("email")
        if not claims.get("email_verified") or not email:
            return Response("Your Google account's email isn't verified.", status=403)

        user = users_module.get_user_by_email(email)
        if user is None:
            return render_template("login.html", next="", error=f"{email} isn't authorized for this app.")

        session.clear()
        session["user_email"] = user["email"]
        session.permanent = remember_me

        return redirect(_safe_next_url(next_url) or url_for("dashboard"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def dashboard():
        month = request.args.get("month", current_month())
        prev_month = previous_month(month)
        months_window = last_n_months(month, SPARKLINE_MONTHS)

        fetch_start, _ = month_bounds(months_window[0])
        _, fetch_end = month_bounds(month)
        all_txns = sheets_client.get_actual(start_date=fetch_start, end_date=fetch_end)
        txns_by_month: dict[str, list[dict]] = {}
        for t in all_txns:
            txns_by_month.setdefault((t.get("Date") or "")[:7], []).append(t)

        cats = categories_module.get_all_categories(use_cache=True)
        cat_types = {c["Category"]: c["Type"] for c in cats}
        cat_group = {c["Category"]: c.get("Group", "") for c in cats}

        rows = compute_variance(month, actual=txns_by_month.get(month, []))
        total_planned = sum(r["planned"] for r in rows)
        total_actual = sum(r["actual"] for r in rows)

        income_total, spend_total = _income_and_spend(txns_by_month.get(month, []), cat_types)
        income_prev, spend_prev = _income_and_spend(txns_by_month.get(prev_month, []), cat_types)
        net = income_total - spend_total
        budget_used_pct = round((spend_total / total_planned) * 100, 1) if total_planned > 0 else None

        sparkline = []
        for m in months_window:
            _, s = _income_and_spend(txns_by_month.get(m, []), cat_types)
            sparkline.append({"month": m, "spend": s, "is_current": m == month})
        max_spark = max((pt["spend"] for pt in sparkline), default=0)
        for pt in sparkline:
            pt["height_pct"] = round((pt["spend"] / max_spark) * 100, 1) if max_spark > 0 else 0

        chart_rows = [dict(r) for r in rows if r["planned"] or r["actual"]]
        chart_rows.sort(key=lambda r: r["actual"], reverse=True)
        max_chart_value = max((max(r["planned"], r["actual"]) for r in chart_rows), default=0)
        for r in chart_rows:
            r["planned_pct"] = round((r["planned"] / max_chart_value) * 100, 1) if max_chart_value else 0
            r["actual_pct"] = round((r["actual"] / max_chart_value) * 100, 1) if max_chart_value else 0

        group_totals: dict[str, dict[str, float]] = {}
        for r in rows:
            group = cat_group.get(r["category"], "")
            if not group:
                continue
            g = group_totals.setdefault(group, {"planned": 0.0, "actual": 0.0})
            g["planned"] += r["planned"]
            g["actual"] += r["actual"]
        group_summary = [
            {"group": g, "planned": v["planned"], "actual": v["actual"], "variance": v["actual"] - v["planned"]}
            for g, v in sorted(group_totals.items())
        ]
        group_segments = _build_group_segments(group_totals)
        donut_segments = _build_donut_segments(group_segments)

        recent_txns = sorted(
            txns_by_month.get(month, []),
            key=lambda t: (t.get("Date") or "", t.get("LoggedAt") or ""),
            reverse=True,
        )[:8]
        for t in recent_txns:
            t["is_income"] = cat_types.get(t.get("Category", "")) == "Income"

        budget_limits = sorted(
            (r for r in rows if r["planned"] > 0),
            key=lambda r: (r["actual"] / r["planned"]),
            reverse=True,
        )
        for r in budget_limits:
            r["used_pct"] = round((r["actual"] / r["planned"]) * 100, 1)

        return render_template(
            "dashboard.html",
            month=month,
            rows=rows,
            chart_rows=chart_rows,
            total_planned=total_planned,
            total_actual=total_actual,
            group_summary=group_summary,
            group_segments=group_segments,
            donut_segments=donut_segments,
            income_total=income_total,
            spend_total=spend_total,
            net=net,
            income_delta=income_total - income_prev,
            spend_delta=spend_total - spend_prev,
            income_delta_class=_delta_class(income_total - income_prev, up_is_good=True),
            spend_delta_class=_delta_class(spend_total - spend_prev, up_is_good=False),
            budget_used_pct=budget_used_pct,
            sparkline=sparkline,
            recent_txns=recent_txns,
            budget_limits=budget_limits,
            claude_model=settings.CLAUDE_MODEL,
        )

    @app.route("/api/insights")
    def api_insights():
        if _llm_rate_limited("insights"):
            return jsonify({"insights": [], "error": "Please wait a few seconds and try again."}), 429
        month = request.args.get("month", current_month())
        try:
            insights = dashboard_insights(month)
        except Exception:
            app.logger.exception("dashboard_insights failed for month=%s", month)
            return jsonify({"insights": [], "error": "Could not generate insights right now."}), 502
        return jsonify({"insights": insights})

    @app.route("/budgets", methods=["GET", "POST"])
    def budgets():
        month = request.args.get("month") or request.form.get("month") or current_month()
        if request.method == "POST":
            # Iterate the SUBMITTED fields, not a freshly-fetched category
            # list — the rendered form's field names (amount_<name>,
            # group_<name>) are keyed by whatever names were current when
            # the page loaded. If a category gets renamed elsewhere between
            # load and submit, fetching active_records fresh here would look
            # for amount_<newname> in a form that only has amount_<oldname>,
            # silently dropping that edit while still reporting success.
            # Reading the form directly and cross-checking against the
            # CURRENT active list catches exactly that mismatch instead.
            active_by_name = {c["Category"]: c for c in categories_module.get_active_category_records()}

            amounts = {}
            group_changes = {}
            skipped = set()
            for key, value in request.form.items():
                if key.startswith("amount_"):
                    category = key[len("amount_"):]
                    if value.strip() == "":
                        continue
                    if category not in active_by_name:
                        skipped.add(category)
                        continue
                    try:
                        amounts[category] = float(value)
                    except ValueError:
                        skipped.add(category)
                elif key.startswith("group_"):
                    category = key[len("group_"):]
                    cat = active_by_name.get(category)
                    if cat is None:
                        skipped.add(category)
                        continue
                    new_group = value.strip()
                    if new_group != (cat.get("Group") or ""):
                        group_changes[category] = new_group

            try:
                sheets_client.upsert_planned_batch(month, amounts)
                categories_module.set_groups_batch(group_changes)
            except Exception:
                app.logger.exception("budgets save failed for month=%s", month)
                return _status_redirect(
                    "budgets", "Could not save budgets — please try again.", status="error", month=month
                )

            if skipped:
                shown = ", ".join(sorted(skipped)[:3])
                more = "" if len(skipped) <= 3 else f" and {len(skipped) - 3} more"
                return _status_redirect(
                    "budgets",
                    f"Saved, but skipped {shown}{more} — reload the page and try again for those.",
                    status="error",
                    month=month,
                )

            return _status_redirect("budgets", f"Budgets saved for {month}.", month=month)

        active_records = categories_module.get_active_category_records()
        planned_rows = {r["Category"]: r["PlannedAmount"] for r in sheets_client.get_planned(month)}
        sections = _build_budget_sections(active_records, planned_rows)

        income_total = next((s["total"] for s in sections if s["type"] == "Income"), 0.0)
        outflow_total = sum(s["total"] for s in sections if s["type"] != "Income")

        return render_template(
            "budgets.html",
            month=month,
            sections=sections,
            planned=planned_rows,
            prev_month=previous_month(month),
            income_total=income_total,
            outflow_total=outflow_total,
            net_planned=income_total - outflow_total,
        )

    @app.route("/budgets/copy_previous", methods=["POST"])
    def budgets_copy_previous():
        month = request.form.get("month", current_month())
        prev = previous_month(month)
        try:
            prev_rows = sheets_client.get_planned(prev)
            amounts = {row["Category"]: float(row.get("PlannedAmount") or 0) for row in prev_rows}
            notes = {row["Category"]: row.get("Notes", "") for row in prev_rows if row.get("Notes")}
            sheets_client.upsert_planned_batch(month, amounts, notes)
        except Exception:
            app.logger.exception("budgets_copy_previous failed for month=%s", month)
            return _status_redirect(
                "budgets", "Could not copy last month's budgets — please try again.", status="error", month=month
            )
        if not amounts:
            return _status_redirect("budgets", f"{prev} has no budgets to copy.", status="error", month=month)
        return _status_redirect("budgets", f"Copied {prev}'s budgets into {month}.", month=month)

    @app.route("/categories")
    def categories_page():
        return render_template("categories.html", categories=categories_module.get_all_categories())

    @app.route("/categories/add", methods=["POST"])
    def categories_add():
        name = request.form.get("name", "").strip()
        type_ = request.form.get("type", "Expense")
        notes = request.form.get("notes", "")
        group = request.form.get("group", "")
        if not name:
            return _status_redirect("categories_page", "Category name is required.", status="error")
        try:
            categories_module.add_category(name, type_, notes, group)
        except ValueError as e:
            return _status_redirect("categories_page", str(e), status="error")
        except Exception:
            app.logger.exception("categories_add failed for name=%s", name)
            return _status_redirect("categories_page", "Could not add the category — please try again.", status="error")
        return _status_redirect("categories_page", f'Added "{name}".')

    @app.route("/categories/edit", methods=["POST"])
    def categories_edit():
        name = request.form.get("name", "")
        new_name = request.form.get("new_name", "").strip()
        type_ = request.form.get("type") or None
        notes = request.form.get("notes")
        group = request.form.get("group")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            if new_name and new_name != name:
                categories_module.rename_category(name, new_name)
                name = new_name  # subsequent updates target the row under its new name
            categories_module.rename_or_retype_category(
                name, new_type=type_, new_notes=notes, new_group=group
            )
        except ValueError as e:
            return _status_redirect("categories_page", str(e), status="error")
        except Exception:
            app.logger.exception("categories_edit failed for name=%s", name)
            return _status_redirect("categories_page", "Could not save changes — please try again.", status="error")
        return _status_redirect("categories_page", f'Saved "{name}".')

    @app.route("/categories/move_up", methods=["POST"])
    def categories_move_up():
        name = request.form.get("name", "")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            categories_module.move_category(name, "up")
        except Exception:
            app.logger.exception("categories_move_up failed for name=%s", name)
            return _status_redirect("categories_page", "Could not reorder — please try again.", status="error")
        return _status_redirect("categories_page", f'Moved "{name}" up.')

    @app.route("/categories/move_down", methods=["POST"])
    def categories_move_down():
        name = request.form.get("name", "")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            categories_module.move_category(name, "down")
        except Exception:
            app.logger.exception("categories_move_down failed for name=%s", name)
            return _status_redirect("categories_page", "Could not reorder — please try again.", status="error")
        return _status_redirect("categories_page", f'Moved "{name}" down.')

    @app.route("/categories/delete", methods=["POST"])
    def categories_delete():
        name = request.form.get("name", "")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            categories_module.deactivate_category(name)
        except Exception:
            app.logger.exception("categories_delete failed for name=%s", name)
            return _status_redirect("categories_page", "Could not deactivate — please try again.", status="error")
        return _status_redirect("categories_page", f'Deactivated "{name}".')

    @app.route("/categories/activate", methods=["POST"])
    def categories_activate():
        name = request.form.get("name", "")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            categories_module.activate_category(name)
        except Exception:
            app.logger.exception("categories_activate failed for name=%s", name)
            return _status_redirect("categories_page", "Could not activate — please try again.", status="error")
        return _status_redirect("categories_page", f'Activated "{name}".')

    @app.route("/categories/remove", methods=["POST"])
    def categories_remove():
        name = request.form.get("name", "")
        if not name:
            return _status_redirect("categories_page", "No category specified.", status="error")
        try:
            categories_module.remove_category(name)
        except Exception:
            app.logger.exception("categories_remove failed for name=%s", name)
            return _status_redirect("categories_page", "Could not remove — please try again.", status="error")
        return _status_redirect("categories_page", f'Removed "{name}" permanently.')

    @app.route("/categories/bulk_delete", methods=["POST"])
    def categories_bulk_delete():
        names = request.form.getlist("category_names")
        by_name = {c["Category"]: c for c in categories_module.get_all_categories()}
        # Same rule as the single-row buttons: active -> deactivate (soft,
        # reversible), already-inactive -> permanently remove. Split into two
        # batches instead of one Sheets round trip per category — the same
        # per-row API-call pattern that was fixed for the Budgets Save
        # button, still present here until now.
        to_deactivate = [n for n in names if by_name.get(n) and str(by_name[n].get("Active", "")).strip().upper() == "TRUE"]
        to_remove = [n for n in names if by_name.get(n) and str(by_name[n].get("Active", "")).strip().upper() != "TRUE"]
        try:
            categories_module.deactivate_categories_batch(to_deactivate)
            categories_module.remove_categories_batch(to_remove)
        except Exception:
            app.logger.exception("categories_bulk_delete failed")
            return _status_redirect("categories_page", "Could not delete the selected categories — please try again.", status="error")
        count = len(to_deactivate) + len(to_remove)
        if count == 0:
            return _status_redirect("categories_page", "No categories selected.", status="error")
        return _status_redirect("categories_page", f"Deleted {count} categor{'y' if count == 1 else 'ies'}.")

    @app.route("/reports")
    def reports_page():
        reports = sorted(sheets_client.get_reports(), key=lambda r: r.get("Month", ""), reverse=True)
        return render_template("reports.html", reports=reports, current_month=current_month())

    @app.route("/reports/generate", methods=["POST"])
    def reports_generate():
        month = request.form.get("month", current_month())
        # Keyed globally, not per-month — a per-month key lets the cooldown be
        # bypassed entirely by requesting a different month each time, since
        # month is attacker-suppliable form input. Matches how /api/insights
        # already rate-limits itself with a single fixed key.
        if _llm_rate_limited("report"):
            return _status_redirect(
                "report_detail",
                "Please wait a few seconds before generating another report.",
                status="error",
                month=month,
            )
        try:
            generate_and_save_report(month)
        except Exception:
            app.logger.exception("generate_and_save_report failed for month=%s", month)
            return _status_redirect(
                "report_detail", "Could not generate the report right now.", status="error", month=month
            )
        return _status_redirect("report_detail", f"Report generated for {month}.", month=month)

    @app.route("/reports/<month>")
    def report_detail(month):
        report = sheets_client.get_report(month)
        if report:
            raw_html = markdown_lib.markdown(report["ReportText"])
            html = bleach.clean(raw_html, tags=ALLOWED_REPORT_TAGS, attributes=ALLOWED_REPORT_ATTRS, strip=True)
        else:
            html = None
        return render_template("report_detail.html", month=month, report=report, report_html=html)

    @app.route("/export")
    def export_page():
        return render_template("export.html", today=date.today().isoformat())

    @app.route("/export/download")
    def export_download():
        range_type = request.args.get("range_type", "month")
        fmt = request.args.get("format", "csv")

        if range_type == "day":
            d = request.args.get("date", date.today().isoformat())
            start, end = d, d
            label = d
        elif range_type == "year":
            y = request.args.get("year", str(date.today().year))
            start, end = year_bounds(y)
            label = y
        else:
            m = request.args.get("month", current_month())
            start, end = month_bounds(m)
            label = m

        rows = sheets_client.get_actual(start_date=start, end_date=end)
        df = pd.DataFrame(rows, columns=["TransactionID", "Date", "Amount", "Category", "Note", "Source", "LoggedAt"])

        filename = f"transactions_{label}.{fmt}"
        if fmt == "xlsx":
            buf = io.BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            buf.seek(0)
            return send_file(
                buf,
                as_attachment=True,
                download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            return Response(
                df.to_csv(index=False),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )

    @app.route("/update")
    def update_page():
        # Status only -- no remote-update trigger. A web app that can pull
        # git changes and restart its own services is a privilege-escalation
        # smell on a public VM; updating here is a manual `git pull` +
        # `systemctl restart` over SSH, same as any other self-managed host.
        return render_template("update.html", **_gather_status())

    @app.route("/api/status/refresh", methods=["POST"])
    def api_status_refresh():
        # The one place all these checks re-run after the initial page load —
        # deliberately button-triggered only, no client-side polling, so a
        # tab left open doesn't keep re-hitting the Sheets API or the
        # metadata server on a timer.
        return jsonify(_gather_status())

    return app
