#!/usr/bin/env python3
"""Reset Alice and run headed TGFC fill — verify bank exit / submit."""
from __future__ import annotations

import os
import sys
from dotenv import load_dotenv

load_dotenv()
os.environ["HEADLESS"] = "false"
os.environ["BROWSER_CHANNEL"] = "chrome"
os.environ["PYTHONUTF8"] = "1"

import gspread
import yaml
from google.oauth2.service_account import Credentials

from utils.sheet_handler import SheetHandler
from core.form_filler_tgfc import FormFiller, FormFillerError

# Reset Alice only
creds = Credentials.from_service_account_file(
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
ws = gspread.authorize(creds).open_by_url(os.getenv("SHEET_URL_TGFC")).worksheet(
    os.getenv("SHEET_WS_TGFC")
)
h = ws.row_values(1)
for r in range(2, 7):
    ws.update_cell(r, h.index("Status") + 1, "Pending" if r == 2 else "Skipped")
    ws.update_cell(r, h.index("Notes") + 1, "")
ws.update_cell(2, h.index("ABA Routing Number") + 1, "021000021")
print("Alice Pending")

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
cfg["target"]["url"] = "https://togetfastcash.com/"
cfg["browser"] = {"channel": "chrome"}
cfg.setdefault("screenshots", {})["enabled"] = True
cfg["screenshots"]["directory"] = "screenshots/tgfc_bank_fix"

sheet = SheetHandler(
    cfg,
    sheet_url=os.getenv("SHEET_URL_TGFC"),
    worksheet_name=os.getenv("SHEET_WS_TGFC", "To Get Fast Cash"),
)
row = sheet.get_pending_rows()[0]
row_num = row["_row_number"]
print("=" * 60)
print(f"  TEST row {row_num}: {row.get('First Name')} {row.get('Last Name')}")
print("=" * 60)
sheet.mark_in_progress(row_num)

filler = FormFiller(cfg)
fp = {
    "viewport": {"width": 430, "height": 900},
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 2.75,
    "locale": "en-US",
    "timezone_id": "America/Los_Angeles",
    "color_scheme": "light",
}

try:
    result = filler.process_row(row=row, fingerprint=fp, proxy_url=None, row_number=row_num)
    sheet.update_row(row_num, status="Success", notes=result.get("notes", ""), proxy_used="direct")
    print("\nSUCCESS:", result)
except FormFillerError as e:
    sheet.update_row(row_num, status="Failed", notes=f"[{e.error_type}] {e}", proxy_used="direct")
    print(f"\nFAILED [{e.error_type}]: {e}")
    sys.exit(1)
