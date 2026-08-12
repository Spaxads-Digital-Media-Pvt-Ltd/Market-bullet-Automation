#!/usr/bin/env python3
"""Dump live bankAccountNumber step DOM + validation after fill."""
from __future__ import annotations

import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
os.environ["HEADLESS"] = "false"

from utils.sheet_handler import SheetHandler
from core.form_filler_tgfc import FormFiller
import yaml

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
cfg["target"]["url"] = "https://togetfastcash.com/"
cfg["browser"] = {"channel": "chrome"}
sheet = SheetHandler(cfg, sheet_url=os.getenv("SHEET_URL_TGFC"), worksheet_name=os.getenv("SHEET_WS_TGFC"))
row = sheet.get_pending_rows()[0] if sheet.get_pending_rows() else None
if not row:
    # force read row 2
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"), scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"])
    ws = gspread.authorize(creds).open_by_url(os.getenv("SHEET_URL_TGFC")).worksheet(os.getenv("SHEET_WS_TGFC"))
    h = ws.row_values(1)
    vals = ws.row_values(2)
    row = dict(zip(h, vals + [""] * (len(h) - len(vals))))
    row["_row_number"] = 2

filler = FormFiller(cfg)
f = filler._parse_fields(row)
print("routing", f.get("routing_number"), "account", f.get("account_number"))

fp = {
    "viewport": {"width": 430, "height": 900},
    "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 2.75,
    "locale": "en-US",
    "timezone_id": "America/Los_Angeles",
    "color_scheme": "light",
}

DUMP = """() => {
  const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
  const inputs = Array.from(document.querySelectorAll('input,select,textarea')).filter(e => vis(e) && e.type!=='hidden').map(e => ({
    name: e.name||'', id: e.id||'', type: e.type||'', ph: e.placeholder||'',
    value: e.value||'', disabled: !!e.disabled,
    ariaInvalid: e.getAttribute('aria-invalid'),
    className: e.className||'',
    maxLength: e.maxLength,
  }));
  const btns = Array.from(document.querySelectorAll('button')).filter(vis).map(b => ({
    text: (b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40),
    disabled: !!b.disabled,
    ariaDisabled: b.getAttribute('aria-disabled'),
    className: (b.className||'').slice(0,80),
  }));
  const errs = Array.from(document.querySelectorAll('[class*=error],[class*=invalid],.invalid-feedback,[role=alert]'))
    .map(e => (e.innerText||'').trim()).filter(Boolean).slice(0,10);
  return {hash: (location.hash||'').replace(/^#/,''), inputs, btns, errs, body: (document.body.innerText||'').slice(0,600)};
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    context = browser.new_context(**{k: v for k, v in fp.items() if k in (
        "viewport","user_agent","is_mobile","has_touch","device_scale_factor","locale","timezone_id","color_scheme"
    )})
    page = context.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded")
    time.sleep(2)

    # Drive with filler handlers until bankAccountNumber
    for i in range(40):
        step = filler._current_step(page)
        print(f"step {i}: {step}")
        if not step:
            time.sleep(1)
            continue
        if step == "bankAccountNumber":
            print("REACHED ACCOUNT STEP — dumping before fill")
            print(page.evaluate(DUMP))
            ok = filler._fill_bank_step(page, f)
            print("filled", ok)
            time.sleep(1)
            print("AFTER FILL:")
            dump = page.evaluate(DUMP)
            print(dump)
            # try next
            filler._click_next(page)
            time.sleep(3)
            print("AFTER NEXT hash", filler._current_step(page))
            print(page.evaluate(DUMP))
            page.screenshot(path="screenshots/bank_account_probe.png", full_page=True)
            time.sleep(8)
            break
        handled = filler._handle_step(page, step, f)
        print("  handled", handled)
        if step in ("loanAmount", "isMilitary", "isHomeOwner", "incomeSource",
                    "incomeFrequency", "payType", "bankAccountType", "loanPurpose",
                    "debt", "residenceMonths", "employedMonths", "bankMonths",
                    "incomeNextDate", "incomeNetMonthly"):
            if filler._await_step_change(page, step, timeout=4):
                continue
        filler._click_next(page)
        filler._await_step_change(page, step, timeout=8)
    browser.close()
