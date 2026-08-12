#!/usr/bin/env python3
"""Normalize SSN + account numbers on TGFC / RPDF / ECD / PDE sheets."""
from __future__ import annotations

import os
import re
import sys

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.lead_platform import (  # noqa: E402
    _account_invalid_reason,
    _sheet_digits,
    _ssn_format,
    _ssn_invalid_reason,
)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Known test leads — valid-looking SSN + 10-digit account (not sequential/repeating).
TEST_FIX = {
    "alice": ("478-21-5836", "3847261059"),
    "brian": ("356-18-2947", "8192045736"),
    "carla": ("512-34-8691", "2671584309"),
    "david": ("247-65-3182", "5918372640"),
    "emily": ("419-73-2568", "7403928156"),
    "frank": ("456-78-1234", "3019284756"),
    "gina": ("321-65-4987", "6281740395"),
    "hector": ("512-88-7334", "9152638470"),
    "ivy": ("234-56-8912", "4738291056"),
    "james": ("478-21-3690", "1860472935"),
}


def _fix_ws(client, sheet_url: str, ws_name: str) -> None:
    ws = client.open_by_url(sheet_url).worksheet(ws_name)
    headers = ws.row_values(1)
    idx = {h: i for i, h in enumerate(headers)}
    first_i = idx.get("First Name")
    ssn_i = idx.get("SSN Full")
    last4_i = idx.get("SSN Last 4")
    acct_i = idx.get("Account Number")
    if first_i is None or ssn_i is None:
        print(f"{ws_name}: missing First Name / SSN Full — skipped")
        return
    rows = ws.get_all_values()
    print(f"\n{ws_name}:")
    for rno, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue

        def cell(i):
            return row[i] if i is not None and i < len(row) else ""

        name = (cell(first_i) or "").strip()
        key = name.lower()
        old_ssn = cell(ssn_i)
        old_acct = cell(acct_i) if acct_i is not None else ""

        if key in TEST_FIX:
            new_ssn, new_acct = TEST_FIX[key]
        else:
            reason = _ssn_invalid_reason(old_ssn)
            new_ssn = _ssn_format(old_ssn) if not reason else old_ssn
            acct_digits = _sheet_digits(old_acct)
            if acct_i is not None and _account_invalid_reason(acct_digits):
                # Don't invent a real lead's account — just keep digits as text.
                new_acct = acct_digits or old_acct
            else:
                new_acct = acct_digits or old_acct

        updates = []
        if ssn_i is not None and new_ssn and new_ssn != old_ssn:
            ws.update_cell(rno, ssn_i + 1, new_ssn)
            updates.append(f"ssn {old_ssn!r}->{new_ssn}")
        if last4_i is not None and new_ssn and re.search(r"\d{4}$", new_ssn):
            last4 = re.sub(r"\D", "", new_ssn)[-4:]
            if cell(last4_i) != last4:
                ws.update_cell(rno, last4_i + 1, last4)
                updates.append(f"last4={last4}")
        if acct_i is not None and new_acct and new_acct != old_acct:
            ws.update_cell(rno, acct_i + 1, new_acct)
            updates.append(f"acct {old_acct!r}->{new_acct}")
        print(f"  row {rno} {name}: {'; '.join(updates) if updates else 'ok'}")


def main() -> None:
    load_dotenv()
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json"),
        scopes=_SCOPES,
    )
    client = gspread.authorize(creds)
    jobs = [
        (os.getenv("SHEET_URL_TGFC") or os.getenv("GOOGLE_SHEET_URL", ""),
         os.getenv("SHEET_WS_TGFC", "To Get Fast Cash")),
        (os.getenv("SHEET_URL_RPDF") or os.getenv("GOOGLE_SHEET_URL", ""),
         os.getenv("SHEET_WS_RPDF", "Rapid Pay Day Fund")),
        (os.getenv("SHEET_URL_ECD") or os.getenv("GOOGLE_SHEET_URL", ""),
         os.getenv("SHEET_WS_ECD", "Easy Cash Day")),
        (os.getenv("SHEET_URL_PDE") or os.getenv("GOOGLE_SHEET_URL", ""),
         os.getenv("SHEET_WS_PDE", "PayDayEd")),
    ]
    for url, name in jobs:
        if url:
            _fix_ws(client, url, name)


if __name__ == "__main__":
    main()
