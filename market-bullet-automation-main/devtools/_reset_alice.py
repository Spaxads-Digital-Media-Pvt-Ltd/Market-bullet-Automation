#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()
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
si, ni = h.index("Status") + 1, h.index("Notes") + 1
# Put Alice first as only Pending; others Failed so demo picks Alice.
for r in range(2, 7):
    ws.update_cell(r, si, "Pending" if r == 2 else "Skipped")
    ws.update_cell(r, ni, "")
ws.update_cell(2, h.index("ABA Routing Number") + 1, "021000021")
print("Alice Pending; others Skipped")
