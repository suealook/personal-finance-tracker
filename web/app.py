import io
import threading
from datetime import date, datetime, timezone

import markdown as markdown_lib
import pandas as pd
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, url_for

from common import categories as categories_module
from common import sheets_client
from common import supervisor_client
from common.dateutil_helpers import current_month, last_n_months, month_bounds, previous_month, year_bounds
from common.heartbeat import heartbeat_age_seconds
from common.llm_analysis import compute_variance, dashboard_insights, generate_and_save_report

SPARKLINE_MONTHS = 6
MAX_GROUP_SLOTS = 6  # + one folded "Other" bucket = 7 visual segments max

WEB_STARTED_AT = datetime.now(timezone.utc)
BOT_HEARTBEAT_RUNNING_SECONDS = 90    # < this since last heartbeat: bot is fine
BOT_HEARTBEAT_STALE_SECONDS = 180     # < this: bot may be restarting/hung; >= this: not responding


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
    app = Flask(__name__)

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
            for category in categories_module.get_active_categories():
                field = f"amount_{category}"
                if field in request.form and request.form[field].strip() != "":
                    try:
                        amount = float(request.form[field])
                    except ValueError:
                        continue
                    sheets_client.upsert_planned(month, category, amount)
            return redirect(url_for("budgets", month=month))

        active_categories = categories_module.get_active_categories()
        planned_rows = {r["Category"]: r["PlannedAmount"] for r in sheets_client.get_planned(month)}
        return render_template(
            "budgets.html", month=month, categories=active_categories, planned=planned_rows
        )

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
        type_ = request.form.get("type") or None
        notes = request.form.get("notes")
        group = request.form.get("group")
        if name:
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

    @app.route("/reports")
    def reports_page():
        reports = sorted(sheets_client.get_reports(), key=lambda r: r.get("Month", ""), reverse=True)
        return render_template("reports.html", reports=reports, current_month=current_month())

    @app.route("/reports/generate", methods=["POST"])
    def reports_generate():
        month = request.form.get("month", current_month())
        generate_and_save_report(month)
        return redirect(url_for("report_detail", month=month))

    @app.route("/reports/<month>")
    def report_detail(month):
        report = sheets_client.get_report(month)
        html = markdown_lib.markdown(report["ReportText"]) if report else None
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
