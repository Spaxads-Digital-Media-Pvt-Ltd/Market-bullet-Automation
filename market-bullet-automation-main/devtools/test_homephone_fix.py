#!/usr/bin/env python3
"""Quick test: TGFC filler through homePhone on live site."""
import yaml
from core.form_filler_tgfc import FormFiller

row = {
    "First Name": "Alice", "Last Name": "Rivera", "Email Address": "alice.rivera@example.com",
    "Phone Number": "3105550101", "Date of Birth (DOB)": "03/22/1988", "SSN Full": "900223344",
    "Street Address": "742 Oak Street", "City": "Los Angeles", "State": "CA", "ZIP Code": "90210",
    "ABA Routing Number": "021000021", "Account Number": "445566778",
    "Requested Loan Amount ($)": "5000", "Monthly Net Income ($)": "4200",
    "Status": "Pending",
}

cfg = yaml.safe_load(open("config.yaml"))
cfg["target"]["url"] = "https://togetfastcash.com/"
f = FormFiller(cfg)
fields = f._parse_fields(row)
print("tgfc_phone:", fields.get("tgfc_phone"))
print("last_ssn:", fields.get("last_ssn"))

# Test only through homePhone using internal methods
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto(cfg["target"]["url"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    f._pick_loan_amount(page, fields)
    page.wait_for_timeout(2000)
    for _ in range(10):
        step = f._current_step(page)
        print("step:", step)
        if step == "homePhone":
            ok = f._fill_step_fields(page, step, fields)
            val = page.locator('input[name="phone"]').first.input_value()
            print("fill ok:", ok, "phone value:", val)
            break
        f._handle_step(page, step, fields)
        if step in ("loanAmount", "isMilitary", "isHomeOwner", "incomeSource", "incomeFrequency", "payType", "bankAccountType", "loanPurpose", "debt", "residenceMonths", "employedMonths", "bankMonths"):
            if f._await_step_change(page, step, timeout=2):
                continue
        f._click_next(page)
        f._await_step_change(page, step)
        page.wait_for_timeout(1500)
    browser.close()
