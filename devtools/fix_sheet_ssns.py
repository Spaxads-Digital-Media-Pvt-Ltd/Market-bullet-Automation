#!/usr/bin/env python3
"""Rewrite SSN Full / SSN Last 4 on TGFC + RPDF sheets to valid XXX-XX-XXXX values."""
from __future__ import annotations

import os
import re

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Name -> formatted SSN (area not 000/666/900-999).
SSN_BY_FIRST = {
    "Alice": "478-21-5836",
    "Brian": "356-18-2947",
    "Carla": "512-34-8691",
    "David": "247-65-3182",
    "Emily": "419-73-2568",
    "Frank": "456-78-1234",
    "Gina": "321-65-4987",
    "Hector": "512-88-7334",
    "Ivy": "234-56-8912",
    "James": "478-21-3690",
}


def _format_or_replace(name: str, current: str) -> str:
    mapped = SSN_BY_FIRST.get((name or "").strip())
    if mapped:
        return mapped
    digits = re.sub(r"\D", "", current or "")
    if len(digits) == 9:
        area = int(digits[:3])
        if area not in (0, 666) and area < 900 and digits[3:5] != "00" and digits[5:] != "0000":
            return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return "356-18-2947"


def _fix_ws(client, sheet_url: str, ws_name: str) -> None:
    ws = client.open_by_url(sheet_url).worksheet(ws_name)
    headers = ws.row_values(1)
    first_col = headers.index("First Name") + 1
    ssn_col = headers.index("SSN Full") + 1
    last4_col = headers.index("SSN Last 4") + 1 if "SSN Last 4" in headers else None
    rows = ws.get_all_values()
    print(f"\n{ws_name}:")
    for i, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue
        name = row[first_col - 1] if len(row) >= first_col else ""
        old = row[ssn_col - 1] if len(row) >= ssn_col else ""
        new = _format_or_replace(name, old)
        last4 = new[-4:]
        ws.update_cell(i, ssn_col, new)
        if last4_col:
            ws.update_cell(i, last4_col, last4)
        print(f"  row {i} {name}: {old!r} -> {new}")


def main() -> None:
    load_dotenv()
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json"),
        scopes=_SCOPES,
    )
    client = gspread.authorize(creds)
    _fix_ws(
        client,
        os.getenv("SHEET_URL_TGFC") or os.getenv("GOOGLE_SHEET_URL", ""),
        os.getenv("SHEET_WS_TGFC", "To Get Fast Cash"),
    )
    _fix_ws(
        client,
        os.getenv("SHEET_URL_RPDF") or os.getenv("GOOGLE_SHEET_URL", ""),
        os.getenv("SHEET_WS_RPDF", "Rapid Pay Day Fund"),
    )


if __name__ == "__main__":
    main()
