#!/usr/bin/env python3
"""Clear the 4 offer sheets and write 3 unique validated Pending leads on each."""
from __future__ import annotations

import os
import sys

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.lead_platform import (  # noqa: E402
    _aba_checksum_ok,
    _account_invalid_reason,
    _digits,
    _ssn_invalid_reason,
)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _lead(**kwargs) -> dict:
    kwargs.setdefault("Status", "Pending")
    kwargs.setdefault("Military", "no")
    kwargs.setdefault("Direct Deposit", "yes")
    kwargs.setdefault("Income Source", "employed")
    kwargs.setdefault("Account Type", "checking")
    kwargs["SSN Last 4"] = _digits(kwargs["SSN Full"])[-4:]
    return kwargs


# Fresh batch (14 Aug 2026 afternoon) — 3 unique people per offer.
SHEETS: dict[str, list[dict]] = {
    "To Get Fast Cash": [
        _lead(
            **{"First Name": "Owen", "Last Name": "Briggs", "Email Address": "owen.briggs.test27@example.com",
             "Phone Number": "5037182946", "Date of Birth (DOB)": "04/16/1989", "SSN Full": "541-28-3175",
             "Street Address": "1200 SW 5th Ave", "City": "Portland", "State": "OR", "ZIP Code": "97204",
             "ABA Routing Number": "123000220", "Account Number": "6291847352", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4300", "Credit Card Debt": "1400", "Years at Address": "3 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Willamette Supply",
             "Driver License / ID Number": "B4419827", "Driver License State": "OR",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "US Bank"}
        ),
        _lead(
            **{"First Name": "Priya", "Last Name": "Santos", "Email Address": "priya.santos.test27@example.com",
             "Phone Number": "6023918472", "Date of Birth (DOB)": "11/28/1992", "SSN Full": "526-41-8392",
             "Street Address": "1 E Washington St", "City": "Phoenix", "State": "AZ", "ZIP Code": "85004",
             "ABA Routing Number": "122101706", "Account Number": "8472916350", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "3700", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Desert Sun Goods",
             "Driver License / ID Number": "S2281769", "Driver License State": "AZ",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Chase"}
        ),
        _lead(
            **{"First Name": "Quinn", "Last Name": "Adler", "Email Address": "quinn.adler.test27@example.com",
             "Phone Number": "3038204761", "Date of Birth (DOB)": "07/03/1986", "SSN Full": "521-36-7481",
             "Street Address": "1670 Broadway", "City": "Denver", "State": "CO", "ZIP Code": "80202",
             "ABA Routing Number": "102000076", "Account Number": "3918472056", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "5400", "Credit Card Debt": "2600", "Years at Address": "5 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "yes",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Front Range Co",
             "Driver License / ID Number": "A3391851", "Driver License State": "CO",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Wells Fargo"}
        ),
    ],
    "Rapid Pay Day Fund": [
        _lead(
            **{"First Name": "Rafael", "Last Name": "Moss", "Email Address": "rafael.moss.test27@example.com",
             "Phone Number": "6153928471", "Date of Birth (DOB)": "09/14/1990", "SSN Full": "408-52-1739",
             "Street Address": "150 4th Ave N", "City": "Nashville", "State": "TN", "ZIP Code": "37219",
             "ABA Routing Number": "064000017", "Account Number": "5728391046", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4500", "Credit Card Debt": "1100", "Years at Address": "4 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Music City Retail",
             "Driver License / ID Number": "M8821457", "Driver License State": "TN",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Regions"}
        ),
        _lead(
            **{"First Name": "Sienna", "Last Name": "Park", "Email Address": "sienna.park.test27@example.com",
             "Phone Number": "8017401935", "Date of Birth (DOB)": "01/22/1988", "SSN Full": "528-47-2916",
             "Street Address": "15 W South Temple", "City": "Salt Lake City", "State": "UT", "ZIP Code": "84101",
             "ABA Routing Number": "124000054", "Account Number": "9184736250", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "4000", "Credit Card Debt": "800", "Years at Address": "3 years",
             "Years at Employer": "2 years", "Years at Bank": "3 years", "Homeowner": "yes",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "Wasatch Parts",
             "Driver License / ID Number": "P4419833", "Driver License State": "UT",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "Zions Bank"}
        ),
        _lead(
            **{"First Name": "Theo", "Last Name": "Reed", "Email Address": "theo.reed.test27@example.com",
             "Phone Number": "4042917385", "Date of Birth (DOB)": "05/07/1993", "SSN Full": "252-39-6841",
             "Street Address": "191 Peachtree St NE", "City": "Atlanta", "State": "GA", "ZIP Code": "30303",
             "ABA Routing Number": "061000104", "Account Number": "2847591630", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "4900", "Credit Card Debt": "2700", "Years at Address": "5 years",
             "Years at Employer": "3 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Peachtree Logistics",
             "Driver License / ID Number": "R1190851", "Driver License State": "GA",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "SunTrust"}
        ),
    ],
    "Easy Cash Day": [
        _lead(
            **{"First Name": "Uma", "Last Name": "Foster", "Email Address": "uma.foster.test27@example.com",
             "Phone Number": "2164019763", "Date of Birth (DOB)": "08/19/1987", "SSN Full": "268-41-7293",
             "Street Address": "200 Public Sq", "City": "Cleveland", "State": "OH", "ZIP Code": "44114",
             "ABA Routing Number": "041000124", "Account Number": "6391827450", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4200", "Credit Card Debt": "1600", "Years at Address": "4 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Lake Erie Retail",
             "Driver License / ID Number": "F5502204", "Driver License State": "OH",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "KeyBank"}
        ),
        _lead(
            **{"First Name": "Victor", "Last Name": "Lane", "Email Address": "victor.lane.test27@example.com",
             "Phone Number": "9137402936", "Date of Birth (DOB)": "12/02/1991", "SSN Full": "509-38-2647",
             "Street Address": "1100 Main St", "City": "Kansas City", "State": "KS", "ZIP Code": "66101",
             "ABA Routing Number": "101000019", "Account Number": "7519283640", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "3800", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Prairie Supply",
             "Driver License / ID Number": "L2281771", "Driver License State": "KS",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Commerce Bank"}
        ),
        _lead(
            **{"First Name": "Willa", "Last Name": "Cruz", "Email Address": "willa.cruz.test27@example.com",
             "Phone Number": "7023827461", "Date of Birth (DOB)": "03/25/1994", "SSN Full": "530-62-1849",
             "Street Address": "300 S 4th St", "City": "Las Vegas", "State": "NV", "ZIP Code": "89101",
             "ABA Routing Number": "122400779", "Account Number": "4827391056", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "4600", "Credit Card Debt": "2100", "Years at Address": "3 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Neon Desert Goods",
             "Driver License / ID Number": "C7702153", "Driver License State": "NV",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Bank of America"}
        ),
    ],
    "PayDayEd": [
        _lead(
            **{"First Name": "Xavier", "Last Name": "Holt", "Email Address": "xavier.holt.test27@example.com",
             "Phone Number": "6124917384", "Date of Birth (DOB)": "06/11/1988", "SSN Full": "468-27-9352",
             "Street Address": "800 Nicollet Mall", "City": "Minneapolis", "State": "MN", "ZIP Code": "55402",
             "ABA Routing Number": "091000019", "Account Number": "3857461920", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4400", "Credit Card Debt": "1300", "Years at Address": "5 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "yes",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "Twin Cities Parts",
             "Driver License / ID Number": "H3391847", "Driver License State": "MN",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "US Bank"}
        ),
        _lead(
            **{"First Name": "Yara", "Last Name": "Kim", "Email Address": "yara.kim.test27@example.com",
             "Phone Number": "2068203947", "Date of Birth (DOB)": "10/08/1990", "SSN Full": "531-39-2751",
             "Street Address": "1301 2nd Ave", "City": "Seattle", "State": "WA", "ZIP Code": "98101",
             "ABA Routing Number": "125000024", "Account Number": "8273641950", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "5100", "Credit Card Debt": "1800", "Years at Address": "4 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "Cascade Tech Co",
             "Driver License / ID Number": "K3391852", "Driver License State": "WA",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Zane", "Last Name": "Porter", "Email Address": "zane.porter.test27@example.com",
             "Phone Number": "5127182937", "Date of Birth (DOB)": "02/17/1985", "SSN Full": "449-46-8209",
             "Street Address": "600 Congress Ave", "City": "Austin", "State": "TX", "ZIP Code": "78701",
             "ABA Routing Number": "111000025", "Account Number": "5938472016", "Requested Loan Amount ($)": "10000",
             "Monthly Net Income ($)": "5600", "Credit Card Debt": "3000", "Years at Address": "6 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "Lone Star Supply",
             "Driver License / ID Number": "P9012351", "Driver License State": "TX",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Bank of America"}
        ),
    ],
}


def _phone_ok(raw: str) -> bool:
    d = _digits(raw)
    if len(d) != 10 or d[0] not in "23456789" or d[3] not in "23456789":
        return False
    if d[3:6] == "555":
        return False
    if d[:3] in {"800", "888", "877", "866", "855", "844", "833"}:
        return False
    return True


def _validate(rows: list[dict], label: str) -> None:
    seen_phone, seen_ssn, seen_acct = set(), set(), set()
    for r in rows:
        name = f"{r['First Name']} {r['Last Name']}"
        phone, ssn, aba, acct = r["Phone Number"], r["SSN Full"], r["ABA Routing Number"], r["Account Number"]
        if not _phone_ok(phone):
            raise SystemExit(f"{label} INVALID PHONE {name}: {phone}")
        err = _ssn_invalid_reason(ssn)
        if err:
            raise SystemExit(f"{label} INVALID SSN {name}: {ssn} ({err})")
        if not _aba_checksum_ok(aba):
            raise SystemExit(f"{label} INVALID ABA {name}: {aba}")
        err = _account_invalid_reason(acct, aba)
        if err:
            raise SystemExit(f"{label} INVALID ACCOUNT {name}: {acct} ({err})")
        if phone in seen_phone or ssn in seen_ssn or acct in seen_acct:
            raise SystemExit(f"{label} duplicate identity on {name}")
        seen_phone.add(phone)
        seen_ssn.add(ssn)
        seen_acct.add(acct)
        print(f"  OK  {label:20} {name:18} {phone}  {ssn}  {aba}  {acct}")


def _clear_and_write(ws, rows: list[dict]) -> None:
    headers = ws.row_values(1)
    if not headers:
        raise SystemExit(f"No headers on '{ws.title}'")
    if ws.row_count > 1:
        end_col = gspread.utils.rowcol_to_a1(1, max(len(headers), ws.col_count)).rstrip("1234567890") or "ZZ"
        ws.batch_clear([f"A2:{end_col}{ws.row_count}"])
    if ws.row_count < 50:
        ws.add_rows(50 - ws.row_count)
    values = [[row.get(h, "") for h in headers] for row in rows]
    end_a1 = gspread.utils.rowcol_to_a1(1 + len(values), len(headers))
    ws.update(values=values, range_name=f"A2:{end_a1}", value_input_option="USER_ENTERED")


def main() -> None:
    load_dotenv()
    print("Validating unique leads...")
    all_phones, all_ssns, all_accts = set(), set(), set()
    expected = 12
    for label, rows in SHEETS.items():
        if len(rows) != 3:
            raise SystemExit(f"{label} must have exactly 3 leads, got {len(rows)}")
        _validate(rows, label)
        for r in rows:
            all_phones.add(r["Phone Number"])
            all_ssns.add(r["SSN Full"])
            all_accts.add(r["Account Number"])
    if len(all_phones) != expected or len(all_ssns) != expected or len(all_accts) != expected:
        raise SystemExit("Leads are not unique across sheets")
    print(f"All {expected} leads unique and valid.\n")

    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json"),
        scopes=_SCOPES,
    )
    client = gspread.authorize(creds)
    url = os.getenv("GOOGLE_SHEET_URL", "")
    mapping = {
        os.getenv("SHEET_WS_TGFC", "To Get Fast Cash"): (
            os.getenv("SHEET_URL_TGFC") or url, "To Get Fast Cash"),
        os.getenv("SHEET_WS_RPDF", "Rapid Pay Day Fund"): (
            os.getenv("SHEET_URL_RPDF") or url, "Rapid Pay Day Fund"),
        os.getenv("SHEET_WS_ECD", "Easy Cash Day"): (
            os.getenv("SHEET_URL_ECD") or url, "Easy Cash Day"),
        os.getenv("SHEET_WS_PDE", "PayDayEd"): (
            os.getenv("SHEET_URL_PDE") or url, "PayDayEd"),
    }
    for ws_name, (sheet_url, key) in mapping.items():
        ws = client.open_by_url(sheet_url).worksheet(ws_name)
        _clear_and_write(ws, SHEETS[key])
        print(f"Cleared + wrote 3 unique Pending rows -> '{ws_name}'")


if __name__ == "__main__":
    main()
