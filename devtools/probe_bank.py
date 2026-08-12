#!/usr/bin/env python3
"""Inspect bank routing/account steps on live TGFC."""
import sys, json, time, yaml
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright
from core.form_filler_tgfc import FormFiller

row = {
    "First Name": "Alice", "Last Name": "Rivera", "Email Address": "alice.rivera@example.com",
    "Phone Number": "3105550101", "Date of Birth (DOB)": "03/22/1988", "SSN Full": "900223344",
    "Street Address": "742 Oak Street", "City": "Los Angeles", "State": "CA", "ZIP Code": "90210",
    "ABA Routing Number": "021000021", "Account Number": "445566778",
    "Requested Loan Amount ($)": "5000", "Monthly Net Income ($)": "4200",
    "Credit Card Debt": "2500", "Years at Address": "5", "Years at Employer": "4",
    "Years at Bank": "3", "Homeowner": "no", "Military": "no", "Direct Deposit": "yes",
    "Income Source": "employed", "Pay Frequency": "bi-weekly", "Next Pay Date": "08/25/2026",
    "Employer Name": "Pacific Retail Co", "Driver License / ID Number": "D8829103",
    "Driver License State": "CA", "Account Type": "checking", "Credit Score Rating": "good",
    "Loan Purpose": "debt consolidation", "Bank Name": "Chase",
}
cfg = yaml.safe_load(open("config.yaml"))
cfg["target"]["url"] = "https://togetfastcash.com/"
filler = FormFiller(cfg)
fields = filler._parse_fields(row)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    for i in range(45):
        step = filler._current_step(page)
        print(i, step)
        if step in ("bankRoutingNumber", "bankAccountNumber", "finish"):
            detail = page.evaluate("""() => {
              const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              return {
                title:(document.querySelector('.f-wizard-step--title')||{}).innerText,
                body:(document.querySelector('.f-wizard-step--body')||{}).innerText?.slice(0,500),
                inputs: Array.from(document.querySelectorAll('input,select')).filter(e=>vis(e)).map(e=>({name:e.name,id:e.id,ph:e.placeholder,val:e.value,type:e.type,html:e.outerHTML.slice(0,200)})),
                errors: Array.from(document.querySelectorAll('.error,.f-error,[class*=error],.f-input--error')).map(e=>e.innerText).slice(0,5)
              };
            }""")
            print(json.dumps(detail, indent=2)[:3000])
            if step == "finish":
                break
        ok = filler._handle_step(page, step, fields) if step else False
        print("  handled", ok)
        if step in ("loanAmount","isMilitary","isHomeOwner","incomeSource","incomeFrequency","payType","bankAccountType","loanPurpose","debt","residenceMonths","employedMonths","bankMonths","incomeNextDate","incomeNetMonthly"):
            if filler._await_step_change(page, step, timeout=3):
                continue
        filler._click_next(page)
        if not filler._await_step_change(page, step or "", timeout=8):
            if step in ("bankRoutingNumber","bankAccountNumber"):
                print("stuck detail above")
                page.wait_for_timeout(8000)
                break
    browser.close()
