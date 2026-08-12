#!/usr/bin/env python3
"""Reset failed TGFC rows back to Pending for re-testing."""
from __future__ import annotations

import os
import time

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main() -> None:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
    sheet_url = os.getenv("SHEET_URL_TGFC") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_TGFC", "To Get Fast Cash")

    creds = Credentials.from_service_account_file(cred_path, scopes=_SCOPES)
    ws = gspread.authorize(creds).open_by_url(sheet_url).worksheet(ws_name)
    records = ws.get_all_records()
    headers = ws.row_values(1)
    status_col = headers.index("Status") + 1
    notes_col = headers.index("Notes") + 1

    reset = 0
    for i, row in enumerate(records, start=2):
        status = str(row.get("Status", "")).strip().lower()
        if status in ("failed", "retry"):
            ws.update_cell(i, status_col, "Pending")
            ws.update_cell(i, notes_col, "")
            reset += 1
            print(f"Reset row {i}: {row.get('First Name')} {row.get('Last Name')}")
        time.sleep(0.5)  # avoid Sheets API rate limit

    print(f"Reset {reset} failed row(s) to Pending.")


if __name__ == "__main__":
    main()
