#!/usr/bin/env python3
"""Add synthetic Pending test rows to the Easy Cash Day worksheet."""
from __future__ import annotations

import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ROWS = [
    {
        "First Name": "Kara", "Last Name": "Bennett", "Email Address": "kara.bennett@example.com",
        "Phone Number": "2165550121", "Date of Birth (DOB)": "05/08/1986", "SSN Full": "368-24-7159",
        "Street Address": "19 Harbor Ave", "City": "Cleveland", "State": "OH", "ZIP Code": "44101",
        "ABA Routing Number": "041000124", "Account Number": "5829173640", "Requested Loan Amount ($)": "5000",
        "Monthly Net Income ($)": "4000", "Credit Card Debt": "1800", "Years at Address": "5 years",
        "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/21/2026", "Employer Name": "Lake Erie Supply",
        "Driver License / ID Number": "B2281764", "Driver License State": "OH", "Account Type": "checking",
        "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Chase",
        "Status": "Pending",
    },
    {
        "First Name": "Leo", "Last Name": "Santos", "Email Address": "leo.santos@example.com",
        "Phone Number": "7205550122", "Date of Birth (DOB)": "09/14/1991", "SSN Full": "524-18-6732",
        "Street Address": "440 Colfax St", "City": "Denver", "State": "CO", "ZIP Code": "80202",
        "ABA Routing Number": "102000076", "Account Number": "7193840265", "Requested Loan Amount ($)": "2500",
        "Monthly Net Income ($)": "3700", "Credit Card Debt": "none", "Years at Address": "2 years",
        "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "semi-monthly",
        "Next Pay Date": "08/19/2026", "Employer Name": "Front Range Logistics",
        "Driver License / ID Number": "S4419023", "Driver License State": "CO", "Account Type": "checking",
        "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Wells Fargo",
        "Status": "Pending",
    },
    {
        "First Name": "Maya", "Last Name": "Brooks", "Email Address": "maya.brooks@example.com",
        "Phone Number": "9195550123", "Date of Birth (DOB)": "01/27/1988", "SSN Full": "241-67-3580",
        "Street Address": "88 Oakwood Dr", "City": "Raleigh", "State": "NC", "ZIP Code": "27601",
        "ABA Routing Number": "053000219", "Account Number": "4061829375", "Requested Loan Amount ($)": "7500",
        "Monthly Net Income ($)": "4900", "Credit Card Debt": "3200", "Years at Address": "4 years",
        "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/26/2026", "Employer Name": "Piedmont Retail Co",
        "Driver License / ID Number": "M7702148", "Driver License State": "NC", "Account Type": "checking",
        "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Bank of America",
        "Status": "Pending",
    },
]


def main() -> None:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
    sheet_url = os.getenv("SHEET_URL_ECD") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_ECD", "Easy Cash Day")

    creds = Credentials.from_service_account_file(cred_path, scopes=_SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_url(sheet_url).worksheet(ws_name)
    headers = ws.row_values(1)

    values = [[row.get(h, "") for h in headers] for row in ROWS]
    ws.append_rows(values, value_input_option="USER_ENTERED")
    print(f"Added {len(ROWS)} Pending test rows to '{ws_name}'.")
    for i, r in enumerate(ROWS, 1):
        print(f"  {i}. {r['First Name']} {r['Last Name']} — {r['Email Address']}")


if __name__ == "__main__":
    main()
