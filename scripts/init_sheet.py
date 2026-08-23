"""One-time (idempotent) setup: creates the 5 tabs with correct headers in a
Google Sheet. Safe to re-run.

Usage: python scripts/init_sheet.py [sheet-id]
With no argument, falls back to GOOGLE_SHEET_ID in .env — useful for the
first/only sheet during initial setup. When onboarding an additional user,
pass their sheet's id explicitly instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gspread.exceptions import WorksheetNotFound  # noqa: E402

from common import sheets_client  # noqa: E402
from config import settings  # noqa: E402


def ensure_tab(spreadsheet, tab_name: str, header: list[str]):
    try:
        ws = spreadsheet.worksheet(tab_name)
        print(f"Tab '{tab_name}' already exists.")
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=max(len(header), 10))
        print(f"Created tab '{tab_name}'.")

    existing_header = ws.row_values(1)
    if existing_header != header:
        ws.update([header], "A1")
        print(f"  Set header for '{tab_name}': {header}")
    else:
        print(f"  Header already correct for '{tab_name}'.")


def main():
    sheet_id = sys.argv[1] if len(sys.argv) > 1 else settings.GOOGLE_SHEET_ID
    if not sheet_id:
        print("Usage: python scripts/init_sheet.py [sheet-id]  (or set GOOGLE_SHEET_ID in .env)")
        sys.exit(1)
    sheets_client.set_current_sheet(sheet_id)
    spreadsheet = sheets_client.get_spreadsheet()
    for tab_name, header in sheets_client.HEADERS.items():
        ensure_tab(spreadsheet, tab_name, header)
    print("\nDone. Verify in the browser:")
    print(f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit")


if __name__ == "__main__":
    main()
