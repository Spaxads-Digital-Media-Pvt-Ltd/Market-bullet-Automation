#!/usr/bin/env python3
"""Confirm whether React state or DOM is the bank-account blocker."""
from __future__ import annotations

import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import yaml

load_dotenv()
os.environ["HEADLESS"] = "false"

from utils.sheet_handler import SheetHandler
from core.form_filler_tgfc import FormFiller

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
cfg["target"]["url"] = "https://togetfastcash.com/"
cfg["browser"] = {"channel": "chrome"}
sheet = SheetHandler(
    cfg,
    sheet_url=os.getenv("SHEET_URL_TGFC"),
    worksheet_name=os.getenv("SHEET_WS_TGFC"),
)
pending = sheet.get_pending_rows()
row = pending[0]
filler = FormFiller(cfg)
f = filler._parse_fields(row)
print("account", f["account_number"], "routing", f["routing_number"])

fp = {
    "viewport": {"width": 430, "height": 900},
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 2.75,
    "locale": "en-US",
    "timezone_id": "America/Los_Angeles",
    "color_scheme": "light",
}

REACT_SET = """([name, value]) => {
  const el = document.querySelector(`input[name="${name}"]`);
  if (!el) return 'missing';
  const proto = window.HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  const last = el.value;
  desc.set.call(el, value);
  if (el._valueTracker) el._valueTracker.setValue(last);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return el.value;
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    context = browser.new_context(
        viewport=fp["viewport"],
        user_agent=fp["user_agent"],
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2.75,
        locale="en-US",
        timezone_id="America/Los_Angeles",
        color_scheme="light",
    )
    page = context.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded")
    time.sleep(2)

    for i in range(40):
        step = filler._current_step(page)
        print("step", i, step)
        if step == "bankAccountNumber":
            # leave bankName alone; set account via React tracker
            before = page.evaluate(
                """() => ({
                  bank: (document.querySelector('input[name=bankName]')||{}).value,
                  acct: (document.querySelector('input[name=bankAccountNumber]')||{}).value,
                })"""
            )
            print("BEFORE", before)
            got = page.evaluate(REACT_SET, ["bankAccountNumber", f["account_number"]])
            print("SET", got)
            time.sleep(0.5)
            # click NEXT via Playwright locator (not evaluate)
            page.locator("button.f-wizard-step--buttons--next").click()
            time.sleep(2)
            after = page.evaluate(
                """() => ({
                  hash: location.hash,
                  bank: (document.querySelector('input[name=bankName]')||{}).value,
                  acct: (document.querySelector('input[name=bankAccountNumber]')||{}).value,
                  body: (document.body.innerText||'').slice(0,900),
                })"""
            )
            print("AFTER", after)
            time.sleep(5)
            break

        handled = filler._handle_step(page, step, f)
        print(" handled", handled)
        if step in (
            "loanAmount", "isMilitary", "isHomeOwner", "incomeSource",
            "incomeFrequency", "payType", "bankAccountType", "loanPurpose",
            "debt", "residenceMonths", "employedMonths", "bankMonths",
            "incomeNextDate", "incomeNetMonthly",
        ):
            if filler._await_step_change(page, step, timeout=4):
                continue
        filler._click_next(page)
        filler._await_step_change(page, step, timeout=10)

    browser.close()
