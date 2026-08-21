"""One-time (idempotent) setup: creates the 5 tabs with correct headers in the
Google Sheet referenced by GOOGLE_SHEET_ID. Safe to re-run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gspread.exceptions import WorksheetNotFound  # noqa: E402

from common import sheets_client  # noqa: E402


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
    spreadsheet = sheets_client.get_spreadsheet()
    for tab_name, header in sheets_client.HEADERS.items():
        ensure_tab(spreadsheet, tab_name, header)
    print("\nDone. Verify in the browser:")
    print(f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit")


if __name__ == "__main__":
    main()
