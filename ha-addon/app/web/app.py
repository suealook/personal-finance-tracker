import bleach
import hashlib
import io
import secrets
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import markdown as markdown_lib
import pandas as pd
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, url_for

from common import categories as categories_module
from common import sheets_client
from common import supervisor_client
from common import usage_tracker
from common.dateutil_helpers import current_month, last_n_months, month_bounds, previous_month, year_bounds
from common.heartbeat import heartbeat_age_seconds
from common.llm_analysis import compute_variance, dashboard_insights, generate_and_save_report
from config import settings

SPARKLINE_MONTHS = 6
MAX_GROUP_SLOTS = 6  # + one folded "Other" bucket = 7 visual segments max
LLM_CALL_COOLDOWN_SECONDS = 10  # guards /api/insights and /reports/generate against cost-abuse loops

ALLOWED_REPORT_TAGS = [
    "p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "h4",
    "blockquote", "code", "pre", "a", "table", "thead", "tbody", "tr", "th", "td",
]
ALLOWED_REPORT_ATTRS = {"a": ["href", "title"]}

WEB_STARTED_AT = datetime.now(timezone.utc)
BOT_HEARTBEAT_RUNNING_SECONDS = 90    # < this since last heartbeat: bot is fine
BOT_HEARTBEAT_STALE_SECONDS = 180     # < this: bot may be restarting/hung; >= this: not responding

_last_llm_call_at: dict[str, float] = {}


def _llm_rate_limited(key: str) -> bool:
    """True if this key's last call was too recent — used to blunt cost-abuse
    loops against the two routes that trigger real Anthropic API calls."""
    now = time.time()
    if now - _last_llm_call_at.get(key, 0.0) < LLM_CALL_COOLDOWN_SECONDS:
        return True
    _last_llm_call_at[key] = now
    return False


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


def create_app() -> Flask:
    if settings.RUNNING_UNDER_HOME_ASSISTANT and not settings.DASHBOARD_PASSWORD:
        raise RuntimeError(
            "dashboard_password is not set. Set it in the add-on's Configuration "
            "tab before starting — the dashboard binds to 0.0.0.0 (LAN-reachable) "
            "under Home Assistant and must not be served without a password."
        )

    app = Flask(__name__)

    # Cache-busting for static assets: without this, style.css is served from a
    # fixed URL forever, so a browser that already cached an old copy has no
    # signal to ever refetch it after an update. Hashing the file content means
    # the URL only changes when the CSS actually does.
    css_path = Path(app.static_folder) / "style.css"
    try:
        app.jinja_env.globals["asset_version"] = hashlib.sha256(css_path.read_bytes()).hexdigest()[:10]
    except OSError:
        app.jinja_env.globals["asset_version"] = str(int(WEB_STARTED_AT.timestamp()))

    @app.before_request
    def _security_gate():
        # CSRF: reject cross-origin state-changing requests. Checked before auth,
        # and regardless of whether a password is configured, since a forged POST
        # from another site is a risk independent of authentication.
        if request.method == "POST":
            origin = request.headers.get("Origin") or request.headers.get("Referer")
            if origin:
                origin_host = urlparse(origin).netloc
                if origin_host and origin_host != request.host:
                    return Response("Cross-origin request rejected.", status=403)

        # Auth: required whenever a password is configured (always true under
        # Home Assistant, per the fail-closed check above; optional for local
        # dev, which is bound to 127.0.0.1 only).
        if settings.DASHBOARD_PASSWORD:
            auth = request.authorization
            if not auth or not secrets.compare_digest(auth.password or "", settings.DASHBOARD_PASSWORD):
                return Response(
                    "Authentication required.",
                    status=401,
                    headers={"WWW-Authenticate": 'Basic realm="Personal Finance Tracker"'},
                )

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

        return render_template(
            "dashboard.html",
            month=month,
            rows=rows,
            chart_rows=chart_rows,
            total_planned=total_planned,
            total_actual=total_actual,
            group_summary=group_summary,
            group_segments=group_segments,
            income_total=income_total,
            spend_total=spend_total,
            net=net,
            income_delta=income_total - income_prev,
            spend_delta=spend_total - spend_prev,
            income_delta_class=_delta_class(income_total - income_prev, up_is_good=True),
            spend_delta_class=_delta_class(spend_total - spend_prev, up_is_good=False),
            budget_used_pct=budget_used_pct,
            sparkline=sparkline,
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
            active_records = categories_module.get_active_category_records()
            for c in active_records:
                category = c["Category"]

                amount_field = f"amount_{category}"
                if amount_field in request.form and request.form[amount_field].strip() != "":
                    try:
                        amount = float(request.form[amount_field])
                    except ValueError:
                        pass
                    else:
                        sheets_client.upsert_planned(month, category, amount)

                group_field = f"group_{category}"
                if group_field in request.form:
                    new_group = request.form[group_field].strip()
                    if new_group != (c.get("Group") or ""):
                        categories_module.rename_or_retype_category(category, new_group=new_group)

            return redirect(url_for("budgets", month=month))

        active_records = categories_module.get_active_category_records()
        planned_rows = {r["Category"]: r["PlannedAmount"] for r in sheets_client.get_planned(month)}
        return render_template(
            "budgets.html",
            month=month,
            categories=active_records,
            planned=planned_rows,
            prev_month=previous_month(month),
        )

    @app.route("/budgets/copy_previous", methods=["POST"])
    def budgets_copy_previous():
        month = request.form.get("month", current_month())
        prev = previous_month(month)
        for row in sheets_client.get_planned(prev):
            amount = float(row.get("PlannedAmount") or 0)
            sheets_client.upsert_planned(month, row["Category"], amount, row.get("Notes", ""))
        return redirect(url_for("budgets", month=month))

    @app.route("/categories")
    def categories_page():
        return render_template("categories.html", categories=categories_module.get_all_categories())

    @app.route("/categories/add", methods=["POST"])
    def categories_add():
        name = request.form.get("name", "").strip()
        type_ = request.form.get("type", "Expense")
        notes = request.form.get("notes", "")
        group = request.form.get("group", "")
        if name:
            try:
                categories_module.add_category(name, type_, notes, group)
            except ValueError:
                pass
        return redirect(url_for("categories_page"))

    @app.route("/categories/edit", methods=["POST"])
    def categories_edit():
        name = request.form.get("name", "")
        new_name = request.form.get("new_name", "").strip()
        type_ = request.form.get("type") or None
        notes = request.form.get("notes")
        group = request.form.get("group")
        if name:
            if new_name and new_name != name:
                try:
                    categories_module.rename_category(name, new_name)
                    name = new_name  # subsequent updates target the row under its new name
                except ValueError:
                    pass  # duplicate/invalid name -- keep old name, other fields still apply below
            categories_module.rename_or_retype_category(
                name, new_type=type_, new_notes=notes, new_group=group
            )
        return redirect(url_for("categories_page"))

    @app.route("/categories/move_up", methods=["POST"])
    def categories_move_up():
        name = request.form.get("name", "")
        if name:
            categories_module.move_category(name, "up")
        return redirect(url_for("categories_page"))

    @app.route("/categories/move_down", methods=["POST"])
    def categories_move_down():
        name = request.form.get("name", "")
        if name:
            categories_module.move_category(name, "down")
        return redirect(url_for("categories_page"))

    @app.route("/categories/delete", methods=["POST"])
    def categories_delete():
        name = request.form.get("name", "")
        if name:
            categories_module.deactivate_category(name)
        return redirect(url_for("categories_page"))

    @app.route("/categories/activate", methods=["POST"])
    def categories_activate():
        name = request.form.get("name", "")
        if name:
            categories_module.activate_category(name)
        return redirect(url_for("categories_page"))

    @app.route("/categories/remove", methods=["POST"])
    def categories_remove():
        name = request.form.get("name", "")
        if name:
            categories_module.remove_category(name)
        return redirect(url_for("categories_page"))

    @app.route("/categories/bulk_delete", methods=["POST"])
    def categories_bulk_delete():
        names = request.form.getlist("category_names")
        by_name = {c["Category"]: c for c in categories_module.get_all_categories()}
        for name in names:
            cat = by_name.get(name)
            if not cat:
                continue
            # Same rule as the single-row buttons: active -> deactivate (soft,
            # reversible), already-inactive -> permanently remove.
            if str(cat.get("Active", "")).strip().upper() == "TRUE":
                categories_module.deactivate_category(name)
            else:
                categories_module.remove_category(name)
        return redirect(url_for("categories_page"))

    @app.route("/reports")
    def reports_page():
        reports = sorted(sheets_client.get_reports(), key=lambda r: r.get("Month", ""), reverse=True)
        return render_template("reports.html", reports=reports, current_month=current_month())

    @app.route("/reports/generate", methods=["POST"])
    def reports_generate():
        month = request.form.get("month", current_month())
        if not _llm_rate_limited(f"report:{month}"):
            generate_and_save_report(month)
        return redirect(url_for("report_detail", month=month))

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
        supervisor_available = supervisor_client.is_available()
        addon_info = None
        supervisor_error = None
        if supervisor_available:
            try:
                addon_info = supervisor_client.get_self_info()
            except Exception as e:
                supervisor_error = str(e)

        return render_template(
            "update.html",
            web_status={
                "state": "good",
                "label": "Running",
                "detail": f"Up since {WEB_STARTED_AT.strftime('%Y-%m-%d %H:%M UTC')}",
            },
            bot_status=_bot_status(),
            sheets_status=_sheets_status(),
            supervisor_available=supervisor_available,
            addon_info=addon_info,
            supervisor_error=supervisor_error,
            claude_usage=usage_tracker.get_claude_usage_summary(),
            sheets_call_count=sheets_client.get_sheets_call_count(),
            claude_model=settings.CLAUDE_MODEL,
        )

    @app.route("/update/run", methods=["POST"])
    def update_run():
        if not supervisor_client.is_available():
            return jsonify({"ok": False, "error": "Not running under Home Assistant."}), 400

        def _do_update():
            try:
                supervisor_client.trigger_update()
            except Exception:
                app.logger.exception("Supervisor update call failed")

        threading.Thread(target=_do_update, daemon=True).start()
        return jsonify({"ok": True, "message": "Update triggered — the app will restart shortly."})

    @app.route("/update/status")
    def update_status():
        return jsonify({"ok": True, "web_started_at": WEB_STARTED_AT.isoformat()})

    return app
