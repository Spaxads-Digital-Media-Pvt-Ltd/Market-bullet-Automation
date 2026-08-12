#!/usr/bin/env python3
"""Quick dump of #debt and following steps using fixed filler helpers."""
import sys, json, time, yaml
from datetime import datetime, timedelta
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright
from core.form_filler_tgfc import FormFiller

row = {
    "First Name": "Alice", "Last Name": "Rivera", "Email Address": "alice.rivera@example.com",
    "Phone Number": "3105550101", "Date of Birth (DOB)": "03/22/1988", "SSN Full": "900223344",
    "Street Address": "742 Oak Street", "City": "Los Angeles", "State": "CA", "ZIP Code": "90210",
    "ABA Routing Number": "021000021", "Account Number": "445566778",
    "Requested Loan Amount ($)": "5000", "Monthly Net Income ($)": "4200",
    "Credit Card Debt": "2500", "Years at Address": "5 years", "Years at Employer": "4 years",
    "Years at Bank": "3 years", "Homeowner": "no", "Military": "no", "Direct Deposit": "yes",
    "Income Source": "employed", "Pay Frequency": "bi-weekly", "Next Pay Date": "08/25/2026",
    "Employer Name": "Pacific Retail Co", "Driver License / ID Number": "D8829103",
    "Driver License State": "CA", "Account Type": "checking", "Credit Score Rating": "good",
    "Loan Purpose": "debt consolidation",
}

cfg = yaml.safe_load(open("config.yaml"))
cfg["target"]["url"] = "https://togetfastcash.com/"
f = FormFiller(cfg)
fields = f._parse_fields(row)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    # drive to debt using filler handlers
    for _ in range(40):
        step = f._current_step(page)
        print("step", step)
        if step in ("debt", "payType", "bankMonths", "bankAccountType", "bankRoutingNumber", "bankAccountNumber", "finish"):
            detail = page.evaluate("""() => {
              const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              return {
                title:(document.querySelector('.f-wizard-step--title')||{}).innerText,
                buttons: Array.from(document.querySelectorAll('button')).filter(vis).map(b => (b.innerText||'').replace(/\\s+/g,' ').trim()).filter(Boolean),
                inputs: Array.from(document.querySelectorAll('input,select')).filter(e=>vis(e)&&e.type!=='hidden').map(e=>({name:e.name,tag:e.tagName,ph:e.placeholder||'',opts:e.tagName==='SELECT'?Array.from(e.options).map(o=>o.value+'|'+o.text.trim()):null}))
              };
            }""")
            print(json.dumps(detail, indent=2)[:2500])
            if step == "finish":
                break
            # fill and continue for remaining dumps
            f._handle_step(page, step, fields)
            if step in ("debt","payType","bankMonths","bankAccountType"):
                f._await_step_change(page, step, timeout=3)
            else:
                f._click_next(page)
                f._await_step_change(page, step)
            continue
        if not step:
            time.sleep(0.5); continue
        f._handle_step(page, step, fields)
        if step in ("loanAmount","isMilitary","isHomeOwner","incomeSource","incomeFrequency","payType","bankAccountType","loanPurpose","debt","residenceMonths","employedMonths","bankMonths","incomeNextDate","incomeNetMonthly"):
            if f._await_step_change(page, step, timeout=3):
                continue
        f._click_next(page)
        f._await_step_change(page, step)
    browser.close()
