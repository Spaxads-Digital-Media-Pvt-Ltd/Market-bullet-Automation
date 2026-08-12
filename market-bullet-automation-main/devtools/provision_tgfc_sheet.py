#!/usr/bin/env python3
"""
devtools/provision_tgfc_sheet.py — create the To Get Fast Cash worksheet tab.

Adds a new tab to the existing spreadsheet with the same lead columns as the other offers
plus TGFC-only ``Next Pay Date``.  Safe to re-run: skips creation if the tab
already exists (unless --force-headers is passed).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "First Name",
    "Last Name",
    "Email Address",
    "Phone Number",
    "Date of Birth (DOB)",
    "SSN Full",
    "SSN Last 4",
    "Street Address",
    "City",
    "State",
    "ZIP Code",
    "ABA Routing Number",
    "Account Number",
    "Requested Loan Amount ($)",
    "Monthly Net Income ($)",
    "Credit Card Debt",
    "Years at Address",
    "Years at Employer",
    "Years at Bank",
    "Homeowner",
    "Military",
    "Direct Deposit",
    "Income Source",
    "Pay Frequency",
    "Next Pay Date",
    "Employer Name",
    "Driver License / ID Number",
    "Driver License State",
    "Account Type",
    "Credit Score Rating",
    "Loan Purpose",
    "Bank Name",
    "Use_Custom_Device",
    "Device_Model",
    "Android_Version",
    "Orientation",
    "Status",
    "Notes",
    "Proxy_Used",
    "IP",
    "Last_Attempt",
    "Retry_Count",
    "Submission_ID",
]


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-headers", action="store_true",
                    help="Overwrite row 1 even if the worksheet already exists")
    args = ap.parse_args()

    sheet_url = os.getenv("SHEET_URL_TGFC") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_TGFC", "To Get Fast Cash")
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")

    if not sheet_url:
        print("ERROR: Set SHEET_URL_TGFC or GOOGLE_SHEET_URL in .env", file=sys.stderr)
        sys.exit(1)
    if not Path(cred_path).exists():
        print(f"ERROR: Credentials not found at {cred_path}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_service_account_file(cred_path, scopes=_SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(sheet_url) if sheet_url.startswith("http") else client.open_by_key(sheet_url)

    try:
        worksheet = spreadsheet.worksheet(ws_name)
        created = False
        print(f"Worksheet '{ws_name}' already exists.")
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=ws_name, rows=1000, cols=len(HEADERS) + 5)
        created = True
        print(f"Created worksheet '{ws_name}'.")

    existing = worksheet.row_values(1)
    if created or args.force_headers or not existing:
        worksheet.update(values=[HEADERS], range_name="A1")
        print(f"Wrote {len(HEADERS)} column headers.")
    else:
        print(f"Headers present ({len(existing)} cols) — use --force-headers to overwrite.")

    print(f"Spreadsheet: {sheet_url}")
    print(f"Tab: {ws_name}")


if __name__ == "__main__":
    main()
