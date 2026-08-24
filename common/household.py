"""Combines shared-category spending across every configured user's own
Google Sheet into one household picture, for the /household dashboard page.

Each user's sheet stays completely separate — this module never writes
across sheets, it only reads each one in turn (via sheets_client's existing
per-sheet functions) and merges the results in Python. A category only ever
contributes here because that user's own Categories row has Shared=TRUE;
name collisions with another user's unshared categories can't leak data in,
since the Shared filter is applied per-sheet before any cross-user matching.
"""

from common import categories as categories_module
from common import sheets_client
from common import users as users_module
from common.llm_analysis import compute_variance


def _is_shared(cat_row: dict) -> bool:
    return str(cat_row.get("Shared", "")).strip().upper() == "TRUE"


def _effective_key(cat_row: dict) -> str:
    override = (cat_row.get("HouseholdCategory") or "").strip()
    return override or cat_row["Category"]


def _person_label(user: dict, viewer_email: str) -> str:
    """"You" for the viewer's own entry; everyone else is shown by the local
    part of their email, never by their own `label` field. `label` can't be
    trusted for anyone but the viewer -- each person's entry in
    data/users.json is typically self-described (the sample entry uses
    "You"), so a non-viewer's label is often written from *their own*
    perspective, not the current viewer's, and displaying it verbatim would
    show "You" to the wrong person."""
    if user["email"].strip().lower() == viewer_email.strip().lower():
        return "You"
    return user["email"].split("@")[0].capitalize()


def _one_user_shared_totals(month: str) -> dict:
    """Everything needed from whichever sheet is currently set_current_sheet'd:
    per-effective-key planned/actual totals restricted to this sheet's own
    Shared=TRUE categories (same-key categories on this one sheet already
    summed together), this sheet's shared-category income/spend split, and
    which raw category name(s) fed each key (so a naming mismatch between
    two people's sheets is visible on the household page instead of just
    silently under-merging)."""
    cats = categories_module.get_all_categories(use_cache=True)
    shared_cats = [c for c in cats if _is_shared(c)]
    if not shared_cats:
        return {"by_key": {}, "income": 0.0, "spend": 0.0, "source_categories": {}}

    key_by_category = {c["Category"]: _effective_key(c) for c in shared_cats}
    type_by_category = {c["Category"]: c.get("Type") for c in shared_cats}
    source_categories: dict[str, list[str]] = {}
    for c in shared_cats:
        source_categories.setdefault(_effective_key(c), []).append(c["Category"])

    rows = compute_variance(month)
    by_key: dict[str, dict[str, float]] = {}
    income = spend = 0.0
    for r in rows:
        key = key_by_category.get(r["category"])
        if key is None:
            continue  # not flagged Shared on this sheet -- stays private
        bucket = by_key.setdefault(key, {"planned": 0.0, "actual": 0.0})
        bucket["planned"] += r["planned"]
        bucket["actual"] += r["actual"]
        if type_by_category.get(r["category"]) == "Income":
            income += r["actual"]
        else:
            spend += r["actual"]
    return {"by_key": by_key, "income": income, "spend": spend, "source_categories": source_categories}


def compute_household_summary(month: str, viewer_email: str) -> dict:
    """Planned-vs-actual totals for `month`, merged across every configured
    user's Shared=TRUE categories, keyed by HouseholdCategory-or-Category so
    two people's differently-named categories can still combine. Restores
    the caller's original current-sheet afterward."""
    users = users_module.get_all_users()
    original_sheet_id = sheets_client.get_current_sheet_id()

    per_user: dict[str, dict] = {}
    try:
        for user in users:
            sheets_client.set_current_sheet(user["sheet_id"])
            per_user[_person_label(user, viewer_email)] = _one_user_shared_totals(month)
    finally:
        sheets_client.set_current_sheet(original_sheet_id)

    person_labels = [_person_label(u, viewer_email) for u in users]
    person_labels.sort(key=lambda label: label != "You")  # viewer's own "You" always shown first
    all_keys = sorted({k for data in per_user.values() for k in data["by_key"]})

    rows = []
    for key in all_keys:
        by_person: dict[str, dict] = {}
        source_categories: dict[str, list[str]] = {}
        planned = actual = 0.0
        for label in person_labels:
            entry = per_user[label]["by_key"].get(key, {"planned": 0.0, "actual": 0.0})
            by_person[label] = entry
            planned += entry["planned"]
            actual += entry["actual"]
            src = per_user[label]["source_categories"].get(key)
            if src:
                source_categories[label] = src
        rows.append(
            {
                "household_category": key,
                "planned": planned,
                "actual": actual,
                "variance": actual - planned,
                "by_person": by_person,
                "source_categories": source_categories,
                "single_contributor": len(source_categories) == 1,
            }
        )
    rows.sort(key=lambda r: r["actual"], reverse=True)

    income_by_person = {label: per_user[label]["income"] for label in person_labels}
    spend_by_person = {label: per_user[label]["spend"] for label in person_labels}
    income_total = sum(income_by_person.values())
    spend_total = sum(spend_by_person.values())
    total_planned = sum(r["planned"] for r in rows)
    total_actual = sum(r["actual"] for r in rows)
    budget_used_pct = round((total_actual / total_planned) * 100, 1) if total_planned > 0 else None

    return {
        "rows": rows,
        "person_labels": person_labels,
        "total_planned": total_planned,
        "total_actual": total_actual,
        "income_total": income_total,
        "spend_total": spend_total,
        "net": income_total - spend_total,
        "income_by_person": income_by_person,
        "spend_by_person": spend_by_person,
        "budget_used_pct": budget_used_pct,
    }
