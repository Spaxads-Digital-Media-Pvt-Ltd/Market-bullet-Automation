#!/usr/bin/env python3
"""Add synthetic Pending test rows to the PayDayEd worksheet."""
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
        "First Name": "Nora", "Last Name": "Quinn", "Email Address": "nora.quinn@example.com",
        "Phone Number": "6155550131", "Date of Birth (DOB)": "03/08/1989", "SSN Full": "415-26-8371",
        "Street Address": "72 Music Row", "City": "Nashville", "State": "TN", "ZIP Code": "37203",
        "ABA Routing Number": "064000017", "Account Number": "6291847350", "Requested Loan Amount ($)": "5000",
        "Monthly Net Income ($)": "4100", "Credit Card Debt": "2100", "Years at Address": "5 years",
        "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/21/2026", "Employer Name": "Cumberland Retail",
        "Driver License / ID Number": "Q3391842", "Driver License State": "TN", "Account Type": "checking",
        "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Chase",
        "Status": "Pending",
    },
    {
        "First Name": "Owen", "Last Name": "Park", "Email Address": "owen.park@example.com",
        "Phone Number": "5035550132", "Date of Birth (DOB)": "11/19/1990", "SSN Full": "541-38-2694",
        "Street Address": "210 Burnside St", "City": "Portland", "State": "OR", "ZIP Code": "97204",
        "ABA Routing Number": "123000220", "Account Number": "8472019365", "Requested Loan Amount ($)": "2500",
        "Monthly Net Income ($)": "3600", "Credit Card Debt": "none", "Years at Address": "2 years",
        "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "semi-monthly",
        "Next Pay Date": "08/19/2026", "Employer Name": "Willamette Tech",
        "Driver License / ID Number": "P8821450", "Driver License State": "OR", "Account Type": "checking",
        "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "US Bank",
        "Status": "Pending",
    },
    {
        "First Name": "Priya", "Last Name": "Shah", "Email Address": "priya.shah@example.com",
        "Phone Number": "4805550133", "Date of Birth (DOB)": "07/03/1987", "SSN Full": "527-14-9083",
        "Street Address": "15 Camelback Rd", "City": "Scottsdale", "State": "AZ", "ZIP Code": "85251",
        "ABA Routing Number": "122105278", "Account Number": "3915728460", "Requested Loan Amount ($)": "7500",
        "Monthly Net Income ($)": "5200", "Credit Card Debt": "4000", "Years at Address": "4 years",
        "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/26/2026", "Employer Name": "Sonoran Services LLC",
        "Driver License / ID Number": "S5502198", "Driver License State": "AZ", "Account Type": "checking",
        "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Wells Fargo",
        "Status": "Pending",
    },
]


def main() -> None:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
    sheet_url = os.getenv("SHEET_URL_PDE") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_PDE", "PayDayEd")

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
