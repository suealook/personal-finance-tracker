"""Convenience wrappers around common.sheets_client for category management."""

from common import sheets_client

VALID_TYPES = ["Expense", "Income", "Savings", "Debt"]


def _as_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _sort_key(r: dict):
    return (_as_int(r.get("SortOrder")), r.get("Category", ""))


def get_all_categories(use_cache: bool = False) -> list[dict]:
    records = sheets_client.get_categories(active_only=False, use_cache=use_cache)
    return sorted(records, key=_sort_key)


def get_active_category_records(use_cache: bool = False) -> list[dict]:
    return [c for c in get_all_categories(use_cache=use_cache) if str(c.get("Active", "")).strip().upper() == "TRUE"]


def get_active_categories() -> list[str]:
    return [c["Category"] for c in get_active_category_records()]


def add_category(name: str, type_: str, notes: str = "", group: str = ""):
    name = name.strip()
    type_ = type_.strip().title()
    if type_ not in VALID_TYPES:
        raise ValueError(f"type must be one of {VALID_TYPES}, got {type_!r}")
    existing = {r["Category"].lower() for r in get_all_categories()}
    if name.lower() in existing:
        raise ValueError(f"Category {name!r} already exists")
    sheets_client.add_category(name, type_, notes, group)


def rename_or_retype_category(
    name: str, new_type: str = None, new_notes: str = None, new_group: str = None
):
    sheets_client.update_category(name, new_type=new_type, new_notes=new_notes, new_group=new_group)


def set_groups_batch(group_changes: dict):
    """Batched Group update for multiple categories at once (e.g. every
    changed row on a single /budgets save), instead of one round trip per
    category via rename_or_retype_category."""
    sheets_client.update_categories_batch(group_changes)


def rename_category(old_name: str, new_name: str):
    """Changes the category's own name (distinct from rename_or_retype_category
    above, which only touches type/notes/group). Existing Planned/Actual/RawLog
    rows keep showing the old name — same "history isn't rewritten" principle
    as remove_category."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("New name can't be empty")
    if new_name.lower() == old_name.lower():
        return
    existing = {r["Category"].lower() for r in get_all_categories()}
    if new_name.lower() in existing:
        raise ValueError(f"Category {new_name!r} already exists")
    sheets_client.rename_category(old_name, new_name)


def deactivate_category(name: str):
    sheets_client.set_category_active(name, active=False)


def deactivate_categories_batch(names: list[str]):
    """Batched deactivate for multiple categories at once (e.g. bulk-delete
    on the Categories page), instead of one round trip per category."""
    sheets_client.deactivate_categories_batch(names)


def remove_categories_batch(names: list[str]):
    """Batched permanent delete for multiple already-inactive categories at
    once, instead of one round trip per category."""
    sheets_client.remove_categories_batch(names)


def activate_category(name: str):
    sheets_client.set_category_active(name, active=True)


def remove_category(name: str):
    """Permanently deletes the category row (not a soft-delete)."""
    sheets_client.delete_category_row(name)


def move_category(name: str, direction: str):
    """direction: 'up' or 'down'. No-op if the category is already at that edge.

    Swaps SortOrder with the adjacent category in the current priority order.
    Relies on existing SortOrder values being distinct, which add_category()
    maintains by always assigning max(existing) + 10 to new categories.
    """
    ordered = get_all_categories()
    idx = next((i for i, c in enumerate(ordered) if c["Category"] == name), None)
    if idx is None:
        raise ValueError(f"Category {name!r} not found")
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(ordered):
        return
    a, b = ordered[idx], ordered[swap_idx]
    order_a, order_b = _as_int(a.get("SortOrder")), _as_int(b.get("SortOrder"))
    sheets_client.set_category_sort_order(a["Category"], order_b)
    sheets_client.set_category_sort_order(b["Category"], order_a)


def backfill_sort_order():
    """One-off migration helper: assigns distinct SortOrder values (10, 20, 30, ...)
    to every category in its current sheet-row order. Safe to re-run."""
    records = sheets_client.get_categories(active_only=False, use_cache=False)
    order = 10
    for r in records:
        sheets_client.set_category_sort_order(r["Category"], order)
        order += 10
