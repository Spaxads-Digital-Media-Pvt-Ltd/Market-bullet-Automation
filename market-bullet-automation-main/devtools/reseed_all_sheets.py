#!/usr/bin/env python3
"""Clear the 4 offer sheets and write 5 unique validated Pending leads on each."""
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


# Fresh batch (Aug 2026) — different people than prior seeds so sites treat
# them as new applicants (email / phone / SSN / account all unique).
SHEETS: dict[str, list[dict]] = {
    "To Get Fast Cash": [
        _lead(
            **{"First Name": "Harper", "Last Name": "Voss", "Email Address": "harper.voss.test26@example.com",
             "Phone Number": "4158293647", "Date of Birth (DOB)": "04/14/1989", "SSN Full": "547-29-3816",
             "Street Address": "88 Spear St", "City": "San Francisco", "State": "CA", "ZIP Code": "94105",
             "ABA Routing Number": "121000248", "Account Number": "5829173640", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4500", "Credit Card Debt": "1200", "Years at Address": "3 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Bay Bridge Supply",
             "Driver License / ID Number": "V8820145", "Driver License State": "CA",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Jonah", "Last Name": "Reed", "Email Address": "jonah.reed.test26@example.com",
             "Phone Number": "7024819375", "Date of Birth (DOB)": "09/03/1992", "SSN Full": "530-41-7628",
             "Street Address": "210 Fremont St", "City": "Las Vegas", "State": "NV", "ZIP Code": "89101",
             "ABA Routing Number": "122400724", "Account Number": "7193048526", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "3600", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "2 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Desert Freight LLC",
             "Driver License / ID Number": "R5502198", "Driver License State": "NV",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Keira", "Last Name": "Stone", "Email Address": "keira.stone.test26@example.com",
             "Phone Number": "6173928461", "Date of Birth (DOB)": "01/22/1987", "SSN Full": "019-38-5247",
             "Street Address": "55 Boylston St", "City": "Boston", "State": "MA", "ZIP Code": "02116",
             "ABA Routing Number": "011000138", "Account Number": "4638201759", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "5200", "Credit Card Debt": "2800", "Years at Address": "5 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "yes",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Harbor Line Goods",
             "Driver License / ID Number": "S3391847", "Driver License State": "MA",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Bank of America"}
        ),
        _lead(
            **{"First Name": "Landon", "Last Name": "Pike", "Email Address": "landon.pike.test26@example.com",
             "Phone Number": "3037182946", "Date of Birth (DOB)": "06/19/1990", "SSN Full": "521-37-9048",
             "Street Address": "1400 Blake St", "City": "Denver", "State": "CO", "ZIP Code": "80202",
             "ABA Routing Number": "102000076", "Account Number": "9271843056", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "4100", "Credit Card Debt": "900", "Years at Address": "4 years",
             "Years at Employer": "3 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "Front Range Parts",
             "Driver License / ID Number": "P7712048", "Driver License State": "CO",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Mira", "Last Name": "Quinn", "Email Address": "mira.quinn.test26@example.com",
             "Phone Number": "5038291746", "Date of Birth (DOB)": "11/07/1994", "SSN Full": "541-28-6391",
             "Street Address": "400 SW 5th Ave", "City": "Portland", "State": "OR", "ZIP Code": "97204",
             "ABA Routing Number": "123000220", "Account Number": "3819472056", "Requested Loan Amount ($)": "10000",
             "Monthly Net Income ($)": "4800", "Credit Card Debt": "2100", "Years at Address": "3 years",
             "Years at Employer": "3 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "Cascade Tech Co",
             "Driver License / ID Number": "Q2281764", "Driver License State": "OR",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "US Bank"}
        ),
    ],
    "Rapid Pay Day Fund": [
        _lead(
            **{"First Name": "Noah", "Last Name": "Briggs", "Email Address": "noah.briggs.test26@example.com",
             "Phone Number": "2147309482", "Date of Birth (DOB)": "03/28/1988", "SSN Full": "449-31-8270",
             "Street Address": "1900 Elm St", "City": "Dallas", "State": "TX", "ZIP Code": "75201",
             "ABA Routing Number": "111000025", "Account Number": "6401829375", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4300", "Credit Card Debt": "1700", "Years at Address": "4 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Lone Star Hardware",
             "Driver License / ID Number": "B5502176", "Driver License State": "TX",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Bank of America"}
        ),
        _lead(
            **{"First Name": "Olive", "Last Name": "Grant", "Email Address": "olive.grant.test26@example.com",
             "Phone Number": "6462917384", "Date of Birth (DOB)": "08/11/1991", "SSN Full": "087-52-3914",
             "Street Address": "350 5th Ave", "City": "New York", "State": "NY", "ZIP Code": "10118",
             "ABA Routing Number": "021000021", "Account Number": "8129374650", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "6100", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Hudson Retail Co",
             "Driver License / ID Number": "G8821450", "Driver License State": "NY",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Chase"}
        ),
        _lead(
            **{"First Name": "Parker", "Last Name": "Diaz", "Email Address": "parker.diaz.test26@example.com",
             "Phone Number": "3057182936", "Date of Birth (DOB)": "12/05/1986", "SSN Full": "261-47-9382",
             "Street Address": "100 Biscayne Blvd", "City": "Miami", "State": "FL", "ZIP Code": "33132",
             "ABA Routing Number": "063107513", "Account Number": "2957183640", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "3900", "Credit Card Debt": "3100", "Years at Address": "5 years",
             "Years at Employer": "3 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Palm Grove Foods",
             "Driver License / ID Number": "D3391842", "Driver License State": "FL",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Quinn", "Last Name": "Hale", "Email Address": "quinn.hale.test26@example.com",
             "Phone Number": "3138204761", "Date of Birth (DOB)": "05/16/1993", "SSN Full": "367-41-8259",
             "Street Address": "600 Woodward Ave", "City": "Detroit", "State": "MI", "ZIP Code": "48226",
             "ABA Routing Number": "072000326", "Account Number": "5718293046", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "3500", "Credit Card Debt": "600", "Years at Address": "3 years",
             "Years at Employer": "2 years", "Years at Bank": "3 years", "Homeowner": "yes",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "Great Lakes Parts",
             "Driver License / ID Number": "H4419820", "Driver License State": "MI",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "Chase"}
        ),
        _lead(
            **{"First Name": "Rory", "Last Name": "Vance", "Email Address": "rory.vance.test26@example.com",
             "Phone Number": "8013928470", "Date of Birth (DOB)": "10/30/1985", "SSN Full": "528-36-1749",
             "Street Address": "15 S Main St", "City": "Salt Lake City", "State": "UT", "ZIP Code": "84111",
             "ABA Routing Number": "124000054", "Account Number": "8392017465", "Requested Loan Amount ($)": "10000",
             "Monthly Net Income ($)": "5500", "Credit Card Debt": "2400", "Years at Address": "6 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "Uinta Logistics",
             "Driver License / ID Number": "V1190843", "Driver License State": "UT",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Wells Fargo"}
        ),
    ],
    "Easy Cash Day": [
        _lead(
            **{"First Name": "Sienna", "Last Name": "Wade", "Email Address": "sienna.wade.test26@example.com",
             "Phone Number": "4802917385", "Date of Birth (DOB)": "02/18/1990", "SSN Full": "527-49-2618",
             "Street Address": "7014 E Camelback Rd", "City": "Scottsdale", "State": "AZ", "ZIP Code": "85251",
             "ABA Routing Number": "122105278", "Account Number": "4182937560", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4200", "Credit Card Debt": "1400", "Years at Address": "4 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Sonoran Ridge LLC",
             "Driver License / ID Number": "W5502198", "Driver License State": "AZ",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Theo", "Last Name": "Banks", "Email Address": "theo.banks.test26@example.com",
             "Phone Number": "2167401938", "Date of Birth (DOB)": "07/09/1987", "SSN Full": "273-58-1946",
             "Street Address": "200 Public Sq", "City": "Cleveland", "State": "OH", "ZIP Code": "44114",
             "ABA Routing Number": "041000124", "Account Number": "7628491035", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "3700", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "3 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Erie Shore Supply",
             "Driver License / ID Number": "B2281765", "Driver License State": "OH",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "KeyBank"}
        ),
        _lead(
            **{"First Name": "Uma", "Last Name": "Cross", "Email Address": "uma.cross.test26@example.com",
             "Phone Number": "9193827461", "Date of Birth (DOB)": "11/25/1992", "SSN Full": "237-64-8501",
             "Street Address": "301 Fayetteville St", "City": "Raleigh", "State": "NC", "ZIP Code": "27601",
             "ABA Routing Number": "053000219", "Account Number": "5839201746", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "4900", "Credit Card Debt": "2700", "Years at Address": "3 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Triangle Retail Co",
             "Driver License / ID Number": "C7702148", "Driver License State": "NC",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "Wells Fargo"}
        ),
        _lead(
            **{"First Name": "Vince", "Last Name": "York", "Email Address": "vince.york.test26@example.com",
             "Phone Number": "6124917382", "Date of Birth (DOB)": "04/02/1988", "SSN Full": "468-27-9350",
             "Street Address": "90 S 7th St", "City": "Minneapolis", "State": "MN", "ZIP Code": "55402",
             "ABA Routing Number": "091000019", "Account Number": "2948571630", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "4500", "Credit Card Debt": "1100", "Years at Address": "5 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "yes",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "North Star Goods",
             "Driver License / ID Number": "Y3391842", "Driver License State": "MN",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "US Bank"}
        ),
        _lead(
            **{"First Name": "Willa", "Last Name": "Moss", "Email Address": "willa.moss.test26@example.com",
             "Phone Number": "6158203947", "Date of Birth (DOB)": "09/14/1991", "SSN Full": "411-39-2748",
             "Street Address": "501 Broadway", "City": "Nashville", "State": "TN", "ZIP Code": "37203",
             "ABA Routing Number": "064000017", "Account Number": "7183942056", "Requested Loan Amount ($)": "10000",
             "Monthly Net Income ($)": "5300", "Credit Card Debt": "3500", "Years at Address": "4 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "Cumberland Retail",
             "Driver License / ID Number": "M3391847", "Driver License State": "TN",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Regions"}
        ),
    ],
    "PayDayEd": [
        _lead(
            **{"First Name": "Xander", "Last Name": "Cole", "Email Address": "xander.cole.test26@example.com",
             "Phone Number": "4047182935", "Date of Birth (DOB)": "06/21/1989", "SSN Full": "252-37-4819",
             "Street Address": "334 Peachtree St NE", "City": "Atlanta", "State": "GA", "ZIP Code": "30308",
             "ABA Routing Number": "061000052", "Account Number": "3958172460", "Requested Loan Amount ($)": "5000",
             "Monthly Net Income ($)": "4400", "Credit Card Debt": "1500", "Years at Address": "3 years",
             "Years at Employer": "4 years", "Years at Bank": "3 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/28/2026", "Employer Name": "Piedmont Retail",
             "Driver License / ID Number": "C1190843", "Driver License State": "GA",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Truist"}
        ),
        _lead(
            **{"First Name": "Yara", "Last Name": "Finn", "Email Address": "yara.finn.test26@example.com",
             "Phone Number": "8324019763", "Date of Birth (DOB)": "01/08/1993", "SSN Full": "456-28-7301",
             "Street Address": "1200 McKinney St", "City": "Houston", "State": "TX", "ZIP Code": "77010",
             "ABA Routing Number": "113000023", "Account Number": "6829173450", "Requested Loan Amount ($)": "2500",
             "Monthly Net Income ($)": "3800", "Credit Card Debt": "none", "Years at Address": "2 years",
             "Years at Employer": "2 years", "Years at Bank": "2 years", "Homeowner": "yes",
             "Pay Frequency": "semi-monthly", "Next Pay Date": "08/27/2026", "Employer Name": "Gulf Coast Logistics",
             "Driver License / ID Number": "F8821450", "Driver License State": "TX",
             "Credit Score Rating": "excellent", "Loan Purpose": "other", "Bank Name": "Bank of America"}
        ),
        _lead(
            **{"First Name": "Zane", "Last Name": "Holt", "Email Address": "zane.holt.test26@example.com",
             "Phone Number": "2068193740", "Date of Birth (DOB)": "08/27/1986", "SSN Full": "531-46-8207",
             "Street Address": "700 4th Ave", "City": "Seattle", "State": "WA", "ZIP Code": "98104",
             "ABA Routing Number": "125000024", "Account Number": "4719382056", "Requested Loan Amount ($)": "7500",
             "Monthly Net Income ($)": "5100", "Credit Card Debt": "2300", "Years at Address": "5 years",
             "Years at Employer": "4 years", "Years at Bank": "5 years", "Homeowner": "no",
             "Pay Frequency": "monthly", "Next Pay Date": "09/01/2026", "Employer Name": "Sound Tech Group",
             "Driver License / ID Number": "H9012348", "Driver License State": "WA",
             "Credit Score Rating": "fair", "Loan Purpose": "credit card", "Bank Name": "US Bank"}
        ),
        _lead(
            **{"First Name": "Ava", "Last Name": "Rhodes", "Email Address": "ava.rhodes.test26@example.com",
             "Phone Number": "6027401839", "Date of Birth (DOB)": "03/15/1991", "SSN Full": "529-58-1740",
             "Street Address": "200 W Washington St", "City": "Phoenix", "State": "AZ", "ZIP Code": "85003",
             "ABA Routing Number": "122101191", "Account Number": "8592017463", "Requested Loan Amount ($)": "3500",
             "Monthly Net Income ($)": "3600", "Credit Card Debt": "800", "Years at Address": "4 years",
             "Years at Employer": "3 years", "Years at Bank": "3 years", "Homeowner": "yes",
             "Pay Frequency": "weekly", "Next Pay Date": "08/25/2026", "Employer Name": "Valley Hardware Co",
             "Driver License / ID Number": "R4419820", "Driver License State": "AZ",
             "Credit Score Rating": "good", "Loan Purpose": "other", "Bank Name": "Chase"}
        ),
        _lead(
            **{"First Name": "Ben", "Last Name": "Soto", "Email Address": "ben.soto.test26@example.com",
             "Phone Number": "3128204759", "Date of Birth (DOB)": "12/12/1988", "SSN Full": "322-49-8613",
             "Street Address": "233 S Wacker Dr", "City": "Chicago", "State": "IL", "ZIP Code": "60606",
             "ABA Routing Number": "071000013", "Account Number": "3601849275", "Requested Loan Amount ($)": "10000",
             "Monthly Net Income ($)": "5600", "Credit Card Debt": "3200", "Years at Address": "6 years",
             "Years at Employer": "5 years", "Years at Bank": "4 years", "Homeowner": "no",
             "Pay Frequency": "bi-weekly", "Next Pay Date": "08/29/2026", "Employer Name": "River North Supply",
             "Driver License / ID Number": "S2281765", "Driver License State": "IL",
             "Credit Score Rating": "good", "Loan Purpose": "debt consolidation", "Bank Name": "Chase"}
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
    # Frozen header rows block delete_rows(2, row_count). Clear values instead.
    if ws.row_count > 1:
        end_col = gspread.utils.rowcol_to_a1(1, max(len(headers), ws.col_count)).rstrip("1234567890") or "ZZ"
        ws.batch_clear([f"A2:{end_col}{ws.row_count}"])
    if ws.row_count < 50:
        ws.add_rows(50 - ws.row_count)
    values = [[row.get(h, "") for h in headers] for row in rows]
    # Write into A2 (append_rows would skip cleared blank rows).
    end_a1 = gspread.utils.rowcol_to_a1(1 + len(values), len(headers))
    ws.update(values=values, range_name=f"A2:{end_a1}", value_input_option="USER_ENTERED")


def main() -> None:
    load_dotenv()
    print("Validating unique leads...")
    all_phones, all_ssns, all_accts = set(), set(), set()
    for label, rows in SHEETS.items():
        _validate(rows, label)
        for r in rows:
            all_phones.add(r["Phone Number"])
            all_ssns.add(r["SSN Full"])
            all_accts.add(r["Account Number"])
    if len(all_phones) != 20 or len(all_ssns) != 20 or len(all_accts) != 20:
        raise SystemExit("Leads are not unique across sheets")
    print("All 20 leads unique and valid.\n")

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
        print(f"Cleared + wrote 5 unique Pending rows -> '{ws_name}'")


if __name__ == "__main__":
    main()
