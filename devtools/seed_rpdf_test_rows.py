#!/usr/bin/env python3
"""Add synthetic Pending test rows to the Rapid Pay Day Fund worksheet."""
from __future__ import annotations

import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Synthetic data only — SSA-valid area (not 000/666/900-999), 555-01xx phones, @example.com.
ROWS = [
    {
        "First Name": "Frank", "Last Name": "Hale", "Email Address": "frank.hale@example.com",
        "Phone Number": "6025550111", "Date of Birth (DOB)": "04/18/1987", "SSN Full": "456-78-1234",
        "Street Address": "184 Desert View Rd", "City": "Phoenix", "State": "AZ", "ZIP Code": "85001",
        "ABA Routing Number": "122105278", "Account Number": "3019284756", "Requested Loan Amount ($)": "5000",
        "Monthly Net Income ($)": "4100", "Credit Card Debt": "2200", "Years at Address": "5 years",
        "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/21/2026", "Employer Name": "Valley Hardware Inc",
        "Driver License / ID Number": "H4419820", "Driver License State": "AZ", "Account Type": "checking",
        "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Chase",
        "Status": "Pending",
    },
    {
        "First Name": "Gina", "Last Name": "Patel", "Email Address": "gina.patel@example.com",
        "Phone Number": "3125550112", "Date of Birth (DOB)": "12/03/1991", "SSN Full": "321-65-4987",
        "Street Address": "77 Lake Shore Dr", "City": "Chicago", "State": "IL", "ZIP Code": "60601",
        "ABA Routing Number": "071000013", "Account Number": "6281740395", "Requested Loan Amount ($)": "2500",
        "Monthly Net Income ($)": "3600", "Credit Card Debt": "none", "Years at Address": "2 years",
        "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "semi-monthly",
        "Next Pay Date": "08/19/2026", "Employer Name": "Midwest Supply Co",
        "Driver License / ID Number": "P2281765", "Driver License State": "IL", "Account Type": "checking",
        "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Bank of America",
        "Status": "Pending",
    },
    {
        "First Name": "Hector", "Last Name": "Ortiz", "Email Address": "hector.ortiz@example.com",
        "Phone Number": "7025550113", "Date of Birth (DOB)": "06/27/1984", "SSN Full": "512-88-7334",
        "Street Address": "409 Sunset Blvd", "City": "Las Vegas", "State": "NV", "ZIP Code": "89101",
        "ABA Routing Number": "122400724", "Account Number": "9152638470", "Requested Loan Amount ($)": "10000",
        "Monthly Net Income ($)": "5300", "Credit Card Debt": "7500", "Years at Address": "6 years",
        "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "monthly",
        "Next Pay Date": "09/01/2026", "Employer Name": "Desert Logistics LLC",
        "Driver License / ID Number": "O6639012", "Driver License State": "NV", "Account Type": "checking",
        "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Wells Fargo",
        "Status": "Pending",
    },
    {
        "First Name": "Ivy", "Last Name": "Walsh", "Email Address": "ivy.walsh@example.com",
        "Phone Number": "4045550114", "Date of Birth (DOB)": "02/11/1993", "SSN Full": "234-56-8912",
        "Street Address": "12 Peachtree St", "City": "Atlanta", "State": "GA", "ZIP Code": "30303",
        "ABA Routing Number": "061000052", "Account Number": "4738291056", "Requested Loan Amount ($)": "3500",
        "Monthly Net Income ($)": "3100", "Credit Card Debt": "1200", "Years at Address": "3 years",
        "Years at Employer": "2 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "weekly",
        "Next Pay Date": "08/18/2026", "Employer Name": "Peach State Retail",
        "Driver License / ID Number": "W1190843", "Driver License State": "GA", "Account Type": "savings",
        "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "SunTrust",
        "Status": "Pending",
    },
    {
        "First Name": "James", "Last Name": "Kim", "Email Address": "james.kim@example.com",
        "Phone Number": "5035550115", "Date of Birth (DOB)": "10/09/1989", "SSN Full": "478-21-3690",
        "Street Address": "880 River Rd", "City": "Portland", "State": "OR", "ZIP Code": "97201",
        "ABA Routing Number": "123000220", "Account Number": "1860472935", "Requested Loan Amount ($)": "7500",
        "Monthly Net Income ($)": "4700", "Credit Card Debt": "3800", "Years at Address": "4 years",
        "Years at Employer": "4 years", "Years at Bank": "5 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/26/2026", "Employer Name": "Cascade Tech Group",
        "Driver License / ID Number": "K5502178", "Driver License State": "OR", "Account Type": "checking",
        "Credit Score Rating": "not sure", "Loan Purpose": "debt consolidation", "Bank Name": "US Bank",
        "Status": "Pending",
    },
]


def main() -> None:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
    sheet_url = os.getenv("SHEET_URL_RPDF") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_RPDF", "Rapid Pay Day Fund")

    creds = Credentials.from_service_account_file(cred_path, scopes=_SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_url(sheet_url).worksheet(ws_name)
    headers = ws.row_values(1)

    values = []
    for row in ROWS:
        values.append([row.get(h, "") for h in headers])

    ws.append_rows(values, value_input_option="USER_ENTERED")
    print(f"Added {len(ROWS)} Pending test rows to '{ws_name}'.")
    for i, r in enumerate(ROWS, 1):
        print(f"  {i}. {r['First Name']} {r['Last Name']} — {r['Email Address']}")


if __name__ == "__main__":
    main()
