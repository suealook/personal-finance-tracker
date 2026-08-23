"""Thin data-access layer over the Google Sheet backing the whole app.

Both the Telegram bot and the Flask dashboard import this module rather than
talking to gspread directly, so there is exactly one place that knows the
sheet's tab/column layout.
"""

import contextlib
import re
import sys
import threading
import time
from typing import Callable, Optional

import gspread
from google.oauth2.service_account import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings

if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # Windows local dev only; the deployed target (the add-on container) is always Linux.


@contextlib.contextmanager
def _sheet_write_lock():
    """Cross-process advisory lock serializing read-then-write sequences
    against the sheet. The bot and web dashboard run as two separate OS
    processes sharing no memory, so an in-process lock (threading.Lock)
    wouldn't stop one process's write from landing on row positions the
    other read before either wrote — e.g. the bot adding a category via
    Telegram while the web dashboard batch-writes Group changes, where the
    web process's cached row numbers go stale mid-write and the wrong row
    gets updated. A file lock (flock) is visible across processes, which an
    in-memory lock isn't. No-op on Windows, where this is only ever local
    dev with a single process talking to the sheet."""
    if fcntl is None:
        yield
        return
    lock_path = settings.HEARTBEAT_DIR / "sheets_write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TAB_CATEGORIES = "Categories"
TAB_PLANNED = "Planned"
TAB_ACTUAL = "Actual"
TAB_RAWLOG = "RawLog"
TAB_REPORTS = "Reports"

HEADERS = {
    TAB_CATEGORIES: ["Category", "Type", "Active", "Notes", "Group", "SortOrder"],
    TAB_PLANNED: ["Month", "Category", "PlannedAmount", "Notes"],
    TAB_ACTUAL: [
        "TransactionID", "Date", "Amount", "Category", "Note",
        "Source", "LoggedAt", "TelegramMsgID", "Status",
    ],
    TAB_RAWLOG: [
        "Timestamp", "TelegramUserID", "TelegramUsername", "RawText",
        "ParseStatus", "LinkedTransactionID",
    ],
    TAB_REPORTS: ["Month", "GeneratedAt", "ReportText", "ModelUsed"],
}

_retry = retry(
    retry=retry_if_exception_type(gspread.exceptions.APIError),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(5),
    reraise=True,
)

_sheets_call_count = 0
_sheets_call_count_lock = threading.Lock()


def _retryable(func):
    """Retry on transient Sheets API errors, and count the call for the
    /update page's usage display (per-process; resets on restart)."""
    retried = _retry(func)

    def wrapper(*args, **kwargs):
        global _sheets_call_count
        with _sheets_call_count_lock:
            _sheets_call_count += 1
        return retried(*args, **kwargs)

    wrapper.__name__ = getattr(func, "__name__", "wrapped")
    return wrapper


def get_sheets_call_count() -> int:
    return _sheets_call_count


# Cell values starting with one of these are live formulas under
# USER_ENTERED — a leading apostrophe forces Sheets to treat the value as
# plain text instead (hidden in the UI, doesn't change what's displayed).
_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_INJECTION_PREFIXES):
        return "'" + value
    return value


_client = None
_spreadsheet = None
_category_cache: Optional[list] = None
_category_cache_at: float = 0.0
CATEGORY_CACHE_TTL_SECONDS = 30


@_retryable
def get_client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


@_retryable
def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        _spreadsheet = get_client().open_by_key(settings.GOOGLE_SHEET_ID)
    return _spreadsheet


@_retryable
def get_worksheet(tab_name: str):
    return get_spreadsheet().worksheet(tab_name)


class SheetTab:
    """Header-aware wrapper around a single worksheet."""

    def __init__(self, tab_name: str):
        self.tab_name = tab_name
        self._header = HEADERS[tab_name]

    @property
    def ws(self):
        return get_worksheet(self.tab_name)

    @_retryable
    def all_records(self) -> list[dict]:
        return self.ws.get_all_records(expected_headers=self._header)

    @_retryable
    def append(self, row_dict: dict) -> int:
        """Appends a row and returns its 1-indexed sheet row number.

        Note: deliberately does NOT look the row back up by matching field values —
        Sheets silently reformats some values on write (e.g. ISO timestamps with a
        "T" separator become space-separated), so a post-hoc value match can miss.
        The row number is instead parsed straight from the append API response.
        """
        row = [_sanitize_cell(row_dict.get(col, "")) for col in self._header]
        result = self.ws.append_row(row, value_input_option="USER_ENTERED")
        updated_range = result["updates"]["updatedRange"]  # e.g. "RawLog!A3:F3"
        match = re.search(r"!\D+(\d+)", updated_range)
        return int(match.group(1))

    def find_row_index(self, predicate: Callable[[dict], bool]) -> Optional[int]:
        """1-indexed sheet row number of the first record matching predicate, or None."""
        for i, rec in enumerate(self.all_records()):
            if predicate(rec):
                return i + 2  # +1 header row, +1 to move from 0-index to 1-index
        return None

    def find_last_row_index(self, predicate: Callable[[dict], bool]) -> Optional[int]:
        """1-indexed sheet row number of the LAST record matching predicate, or None."""
        match = None
        for i, rec in enumerate(self.all_records()):
            if predicate(rec):
                match = i + 2
        return match

    @_retryable
    def update_cell(self, row_index: int, col_name: str, value):
        col_index = self._header.index(col_name) + 1
        self.ws.update_cell(row_index, col_index, _sanitize_cell(value))

    @_retryable
    def get_record_at(self, row_index: int) -> dict:
        values = self.ws.row_values(row_index)
        return dict(zip(self._header, values))

    @_retryable
    def delete_row(self, row_index: int):
        self.ws.delete_rows(row_index)

    @_retryable
    def delete_rows_batch(self, row_indices: list[int]):
        """Deletes multiple rows in one Sheets API call via a single
        batchUpdate with one deleteDimension request per row. Callers must
        pass row_indices sorted descending — Sheets applies the requests in
        the given order within the batch, and deleting a lower row first
        would shift the row numbers the later requests in the same call
        still refer to."""
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": self.ws.id,
                        "dimension": "ROWS",
                        "startIndex": row_index - 1,  # deleteDimension ranges are 0-indexed
                        "endIndex": row_index,
                    }
                }
            }
            for row_index in row_indices
        ]
        self.ws.spreadsheet.batch_update({"requests": requests})

    @_retryable
    def batch_update_cells(self, cells: list["gspread.Cell"]):
        self.ws.update_cells(cells, value_input_option="USER_ENTERED")

    @_retryable
    def append_rows(self, rows: list[dict]):
        values = [[_sanitize_cell(row_dict.get(col, "")) for col in self._header] for row_dict in rows]
        self.ws.append_rows(values, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def get_categories(active_only: bool = False, use_cache: bool = True) -> list[dict]:
    global _category_cache, _category_cache_at
    now = time.time()
    if use_cache and _category_cache is not None and (now - _category_cache_at) < CATEGORY_CACHE_TTL_SECONDS:
        records = _category_cache
    else:
        records = SheetTab(TAB_CATEGORIES).all_records()
        _category_cache = records
        _category_cache_at = now
    if active_only:
        records = [r for r in records if str(r.get("Active", "")).strip().upper() == "TRUE"]
    return records


def invalidate_category_cache():
    global _category_cache
    _category_cache = None


def _next_sort_order() -> int:
    records = SheetTab(TAB_CATEGORIES).all_records()
    max_order = 0
    for r in records:
        try:
            v = int(r.get("SortOrder") or 0)
        except (TypeError, ValueError):
            v = 0
        max_order = max(max_order, v)
    return max_order + 10


def add_category(name: str, type_: str, notes: str = "", group: str = ""):
    tab = SheetTab(TAB_CATEGORIES)
    sort_order = _next_sort_order()
    tab.append(
        {
            "Category": name,
            "Type": type_,
            "Active": "TRUE",
            "Notes": notes,
            "Group": group,
            "SortOrder": sort_order,
        }
    )
    invalidate_category_cache()


def set_category_active(name: str, active: bool):
    tab = SheetTab(TAB_CATEGORIES)
    row = tab.find_row_index(lambda r: r.get("Category") == name)
    if row is None:
        raise ValueError(f"Category {name!r} not found")
    tab.update_cell(row, "Active", "TRUE" if active else "FALSE")
    invalidate_category_cache()


def update_category(
    name: str,
    new_type: Optional[str] = None,
    new_notes: Optional[str] = None,
    new_group: Optional[str] = None,
):
    tab = SheetTab(TAB_CATEGORIES)
    row = tab.find_row_index(lambda r: r.get("Category") == name)
    if row is None:
        raise ValueError(f"Category {name!r} not found")
    if new_type is not None:
        tab.update_cell(row, "Type", new_type)
    if new_notes is not None:
        tab.update_cell(row, "Notes", new_notes)
    if new_group is not None:
        tab.update_cell(row, "Group", new_group)
    invalidate_category_cache()


def rename_category(old_name: str, new_name: str):
    """Renames the category going forward only — existing Planned/Actual/RawLog
    rows keep the old name text (they're not rewritten), same "history is
    preserved as-is" principle as delete_category_row below."""
    tab = SheetTab(TAB_CATEGORIES)
    row = tab.find_row_index(lambda r: r.get("Category") == old_name)
    if row is None:
        raise ValueError(f"Category {old_name!r} not found")
    tab.update_cell(row, "Category", new_name)
    invalidate_category_cache()


def set_category_sort_order(name: str, sort_order: int):
    tab = SheetTab(TAB_CATEGORIES)
    row = tab.find_row_index(lambda r: r.get("Category") == name)
    if row is None:
        raise ValueError(f"Category {name!r} not found")
    tab.update_cell(row, "SortOrder", sort_order)
    invalidate_category_cache()


def delete_category_row(name: str):
    """Permanently removes the category row. Safe with respect to other tabs:
    Planned/Actual reference categories by name (text), not by row position, so
    historical transactions/budgets keep displaying correctly even after their
    category is removed from the Categories tab."""
    tab = SheetTab(TAB_CATEGORIES)
    row = tab.find_row_index(lambda r: r.get("Category") == name)
    if row is None:
        raise ValueError(f"Category {name!r} not found")
    tab.delete_row(row)
    invalidate_category_cache()


# ---------------------------------------------------------------------------
# Planned budgets
# ---------------------------------------------------------------------------

def get_planned(month: str) -> list[dict]:
    return [r for r in SheetTab(TAB_PLANNED).all_records() if r.get("Month") == month]


def upsert_planned(month: str, category: str, amount: float, notes: str = ""):
    tab = SheetTab(TAB_PLANNED)
    row = tab.find_row_index(lambda r: r.get("Month") == month and r.get("Category") == category)
    if row is None:
        tab.append({"Month": month, "Category": category, "PlannedAmount": amount, "Notes": notes})
    else:
        tab.update_cell(row, "PlannedAmount", amount)
        if notes:
            tab.update_cell(row, "Notes", notes)


def upsert_planned_batch(month: str, amounts: dict, notes: Optional[dict] = None):
    """Batched version of upsert_planned for writing many categories' planned
    amounts at once. One read plus one batched cell-update call for existing
    rows and one batched append call for new rows — a fixed 2-3 API calls
    regardless of category count, instead of one read+write round trip per
    category (what made a /budgets save with N categories cost ~2N
    sequential Sheets API calls, the actual reason Save was slow)."""
    if not amounts:
        return
    notes = notes or {}
    with _sheet_write_lock():
        tab = SheetTab(TAB_PLANNED)
        existing = tab.all_records()
        row_by_category = {
            r["Category"]: i + 2
            for i, r in enumerate(existing)
            if r.get("Month") == month
        }
        amount_col = tab._header.index("PlannedAmount") + 1
        notes_col = tab._header.index("Notes") + 1

        cells = []
        new_rows = []
        for category, amount in amounts.items():
            row_index = row_by_category.get(category)
            note = notes.get(category, "")
            if row_index is not None:
                cells.append(gspread.Cell(row_index, amount_col, amount))
                if note:
                    cells.append(gspread.Cell(row_index, notes_col, _sanitize_cell(note)))
            else:
                new_rows.append({"Month": month, "Category": category, "PlannedAmount": amount, "Notes": note})

        if cells:
            tab.batch_update_cells(cells)
        if new_rows:
            tab.append_rows(new_rows)


def update_categories_batch(group_changes: dict):
    """Batched version of update_category's Group-only path. One read of the
    Categories tab plus one batched cell-update call, instead of a
    read+write round trip per changed category."""
    if not group_changes:
        return
    with _sheet_write_lock():
        tab = SheetTab(TAB_CATEGORIES)
        existing = tab.all_records()
        row_by_category = {r["Category"]: i + 2 for i, r in enumerate(existing)}
        col_index = tab._header.index("Group") + 1

        cells = [
            gspread.Cell(row_by_category[category], col_index, _sanitize_cell(new_group))
            for category, new_group in group_changes.items()
            if category in row_by_category
        ]
        if cells:
            tab.batch_update_cells(cells)
    invalidate_category_cache()


def deactivate_categories_batch(names: list[str]):
    """Batched version of set_category_active(active=False) for many
    categories at once — one read plus one batched cell-update call,
    instead of a read+write round trip per category."""
    if not names:
        return
    with _sheet_write_lock():
        tab = SheetTab(TAB_CATEGORIES)
        existing = tab.all_records()
        row_by_category = {r["Category"]: i + 2 for i, r in enumerate(existing)}
        col_index = tab._header.index("Active") + 1

        cells = [
            gspread.Cell(row_by_category[name], col_index, "FALSE")
            for name in names
            if name in row_by_category
        ]
        if cells:
            tab.batch_update_cells(cells)
    invalidate_category_cache()


def remove_categories_batch(names: list[str]):
    """Batched permanent delete for many categories at once — a single
    batchUpdate call instead of one delete_rows API call per category."""
    if not names:
        return
    with _sheet_write_lock():
        tab = SheetTab(TAB_CATEGORIES)
        existing = tab.all_records()
        row_by_category = {r["Category"]: i + 2 for i, r in enumerate(existing)}
        row_indices = sorted(
            (row_by_category[name] for name in names if name in row_by_category),
            reverse=True,
        )
        if row_indices:
            tab.delete_rows_batch(row_indices)
    invalidate_category_cache()


# ---------------------------------------------------------------------------
# Actual transactions
# ---------------------------------------------------------------------------

def append_transaction(row_dict: dict):
    SheetTab(TAB_ACTUAL).append(row_dict)


def get_actual(start_date: Optional[str] = None, end_date: Optional[str] = None, active_only: bool = True) -> list[dict]:
    records = SheetTab(TAB_ACTUAL).all_records()
    if active_only:
        records = [r for r in records if r.get("Status") == "active"]
    if start_date:
        records = [r for r in records if r.get("Date", "") >= start_date]
    if end_date:
        records = [r for r in records if r.get("Date", "") <= end_date]
    return records


def get_last_transaction_for_source(source: str = "telegram") -> Optional[dict]:
    tab = SheetTab(TAB_ACTUAL)
    row = tab.find_last_row_index(lambda r: r.get("Source") == source and r.get("Status") == "active")
    if row is None:
        return None
    record = tab.get_record_at(row)
    record["_row"] = row
    return record


def get_transaction_by_id(transaction_id: str) -> Optional[dict]:
    """Looks up one specific transaction regardless of recency — used by the
    bot's inline Undo button, which targets the exact row it was attached to
    rather than "whatever's last" (which could have changed by the time it's tapped)."""
    tab = SheetTab(TAB_ACTUAL)
    row = tab.find_row_index(lambda r: r.get("TransactionID") == transaction_id)
    if row is None:
        return None
    record = tab.get_record_at(row)
    record["_row"] = row
    return record


def undo_transaction(row_index: int):
    SheetTab(TAB_ACTUAL).update_cell(row_index, "Status", "undone")


def update_transaction_field(row_index: int, field: str, value):
    SheetTab(TAB_ACTUAL).update_cell(row_index, field, value)


# ---------------------------------------------------------------------------
# Raw log
# ---------------------------------------------------------------------------

def append_raw_log(row_dict: dict) -> int:
    """Appends and returns the new row's 1-indexed row number."""
    return SheetTab(TAB_RAWLOG).append(row_dict)


def update_raw_log(row_index: int, parse_status: str, linked_transaction_id: str = ""):
    tab = SheetTab(TAB_RAWLOG)
    tab.update_cell(row_index, "ParseStatus", parse_status)
    if linked_transaction_id:
        tab.update_cell(row_index, "LinkedTransactionID", linked_transaction_id)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def append_report(row_dict: dict):
    SheetTab(TAB_REPORTS).append(row_dict)


def get_reports() -> list[dict]:
    return SheetTab(TAB_REPORTS).all_records()


def get_report(month: str) -> Optional[dict]:
    for r in get_reports():
        if r.get("Month") == month:
            return r
    return None
