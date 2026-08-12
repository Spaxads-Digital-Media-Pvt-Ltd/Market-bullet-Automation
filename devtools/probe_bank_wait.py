#!/usr/bin/env python3
from __future__ import annotations
import os, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import yaml
load_dotenv()
from utils.sheet_handler import SheetHandler
from core.form_filler_tgfc import FormFiller

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
cfg["target"]["url"] = "https://togetfastcash.com/"
cfg["browser"] = {"channel": "chrome"}
row = SheetHandler(cfg, sheet_url=os.getenv("SHEET_URL_TGFC"), worksheet_name=os.getenv("SHEET_WS_TGFC")).get_pending_rows()[0]
filler = FormFiller(cfg)
f = filler._parse_fields(row)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    context = browser.new_context(
        viewport={"width": 430, "height": 900},
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        is_mobile=True, has_touch=True, device_scale_factor=2.75,
        locale="en-US", timezone_id="America/Los_Angeles",
    )
    page = context.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded")
    time.sleep(2)
    for i in range(40):
        step = filler._current_step(page)
        if step != "bankAccountNumber":
            filler._handle_step(page, step, f)
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
            continue
        print("fill", filler._react_set_input(page, "bankAccountNumber", f["account_number"]))
        time.sleep(0.8)
        print("click", filler._react_click(page, "button.f-wizard-step--buttons--next"))
        time.sleep(2)
        print("hash", page.evaluate("location.hash"))
        time.sleep(3)
        break
    browser.close()
