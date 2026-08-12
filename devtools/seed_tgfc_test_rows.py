#!/usr/bin/env python3
"""Add synthetic Pending test rows to the To Get Fast Cash worksheet."""
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
        "First Name": "Alice", "Last Name": "Rivera", "Email Address": "alice.rivera@example.com",
        "Phone Number": "3105550101", "Date of Birth (DOB)": "03/22/1988", "SSN Full": "478-21-5836",
        "Street Address": "742 Oak Street", "City": "Los Angeles", "State": "CA", "ZIP Code": "90210",
        "ABA Routing Number": "021000021", "Account Number": "3847261059", "Requested Loan Amount ($)": "5000",
        "Monthly Net Income ($)": "4200", "Credit Card Debt": "2500", "Years at Address": "5 years",
        "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/22/2026", "Employer Name": "Pacific Retail Co",
        "Driver License / ID Number": "D8829103", "Driver License State": "CA", "Account Type": "checking",
        "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Chase",
        "Status": "Pending",
    },
    {
        "First Name": "Brian", "Last Name": "Nguyen", "Email Address": "brian.nguyen@example.com",
        "Phone Number": "4155550102", "Date of Birth (DOB)": "11/08/1992", "SSN Full": "356-18-2947",
        "Street Address": "118 Pine Avenue", "City": "San Francisco", "State": "CA", "ZIP Code": "94102",
        "ABA Routing Number": "121000358", "Account Number": "8192045736", "Requested Loan Amount ($)": "2500",
        "Monthly Net Income ($)": "3800", "Credit Card Debt": "none", "Years at Address": "2 years",
        "Years at Employer": "2 years", "Years at Bank": "2 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "semi-monthly",
        "Next Pay Date": "08/20/2026", "Employer Name": "Bay Logistics LLC",
        "Driver License / ID Number": "N4451209", "Driver License State": "CA", "Account Type": "checking",
        "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Wells Fargo",
        "Status": "Pending",
    },
    {
        "First Name": "Carla", "Last Name": "Mitchell", "Email Address": "carla.mitchell@example.com",
        "Phone Number": "5125550103", "Date of Birth (DOB)": "07/14/1985", "SSN Full": "512-34-8691",
        "Street Address": "903 Cedar Lane", "City": "Austin", "State": "TX", "ZIP Code": "78701",
        "ABA Routing Number": "111000025", "Account Number": "2671584309", "Requested Loan Amount ($)": "10000",
        "Monthly Net Income ($)": "5500", "Credit Card Debt": "8000", "Years at Address": "6 years",
        "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "yes", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "monthly",
        "Next Pay Date": "09/01/2026", "Employer Name": "Lone Star Services",
        "Driver License / ID Number": "M3398712", "Driver License State": "TX", "Account Type": "checking",
        "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Bank of America",
        "Status": "Pending",
    },
    {
        "First Name": "David", "Last Name": "Brooks", "Email Address": "david.brooks@example.com",
        "Phone Number": "3055550104", "Date of Birth (DOB)": "01/30/1990", "SSN Full": "247-65-3182",
        "Street Address": "56 Palm Drive", "City": "Miami", "State": "FL", "ZIP Code": "33101",
        "ABA Routing Number": "063107513", "Account Number": "5918372640", "Requested Loan Amount ($)": "3500",
        "Monthly Net Income ($)": "3200", "Credit Card Debt": "1500", "Years at Address": "3 years",
        "Years at Employer": "3 years", "Years at Bank": "3 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "weekly",
        "Next Pay Date": "08/15/2026", "Employer Name": "Coastal Foods Inc",
        "Driver License / ID Number": "B7723401", "Driver License State": "FL", "Account Type": "savings",
        "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "SunTrust",
        "Status": "Pending",
    },
    {
        "First Name": "Emily", "Last Name": "Chen", "Email Address": "emily.chen@example.com",
        "Phone Number": "2065550105", "Date of Birth (DOB)": "09/05/1995", "SSN Full": "419-73-2568",
        "Street Address": "220 Maple Court", "City": "Seattle", "State": "WA", "ZIP Code": "98101",
        "ABA Routing Number": "125000024", "Account Number": "7403928156", "Requested Loan Amount ($)": "7500",
        "Monthly Net Income ($)": "4800", "Credit Card Debt": "4000", "Years at Address": "4 years",
        "Years at Employer": "4 years", "Years at Bank": "5 years", "Homeowner": "no", "Military": "no",
        "Direct Deposit": "yes", "Income Source": "employed", "Pay Frequency": "bi-weekly",
        "Next Pay Date": "08/25/2026", "Employer Name": "Northwest Tech Group",
        "Driver License / ID Number": "C9012345", "Driver License State": "WA", "Account Type": "checking",
        "Credit Score Rating": "not sure", "Loan Purpose": "debt consolidation", "Bank Name": "US Bank",
        "Status": "Pending",
    },
]


def main() -> None:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
    sheet_url = os.getenv("SHEET_URL_TGFC") or os.getenv("GOOGLE_SHEET_URL", "")
    ws_name = os.getenv("SHEET_WS_TGFC", "To Get Fast Cash")

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
