#!/usr/bin/env python3
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
row = sheet.get_pending_rows()[0]
filler = FormFiller(cfg)
f = filler._parse_fields(row)

fp = {
    "viewport": {"width": 430, "height": 900},
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
}

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
    )
    page = context.new_page()
    logs = []
    page.on("console", lambda msg: logs.append(f"{msg.type}: {msg.text}"))

    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded")
    time.sleep(2)

    for i in range(40):
        step = filler._current_step(page)
        print("step", i, step)
        if step == "bankAccountNumber":
            loc = page.locator('input[name="bankAccountNumber"]').first
            loc.click()
            loc.fill("")
            # Real keyboard — fires React onChange on custom Input
            page.keyboard.type(f["account_number"], delay=80)
            time.sleep(0.5)
            print("DOM", loc.input_value())
            page.locator("button.f-wizard-step--buttons--next").click()
            time.sleep(2)
            print("hash", page.evaluate("location.hash"))
            print("body snippet:", page.evaluate("document.body.innerText").split("NEXT")[0][-200:])
            print("--- console ---")
            for line in logs[-20:]:
                if "compare" in line.lower() or "error" in line.lower() or "bank" in line.lower() or "invalid" in line.lower():
                    print(line)
            for line in logs[-8:]:
                print(line)
            time.sleep(4)
            break

        handled = filler._handle_step(page, step, f)
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
