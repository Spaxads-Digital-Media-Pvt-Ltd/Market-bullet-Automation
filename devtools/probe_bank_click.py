#!/usr/bin/env python3
from __future__ import annotations

import os
import time
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
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2.75,
        locale="en-US",
        timezone_id="America/Los_Angeles",
    )
    page = context.new_page()
    logs = []
    page.on("console", lambda msg: logs.append(msg.text))
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

        print("on account step")
        loc = page.locator('input[name="bankAccountNumber"]').first
        loc.click()
        page.keyboard.type(f["account_number"], delay=60)
        time.sleep(0.4)

        # Hook button onclick by wrapping
        page.evaluate(
            """() => {
              const btn = document.querySelector('button.f-wizard-step--buttons--next');
              window.__nextClicks = 0;
              if (btn) btn.addEventListener('click', () => { window.__nextClicks++; console.log('NATIVE_CLICK', window.__nextClicks); }, true);
            }"""
        )

        btn = page.locator("button.f-wizard-step--buttons--next").first
        box = btn.bounding_box()
        print("box", box, "disabled", btn.is_disabled())

        # Try tap (touch)
        try:
            btn.tap(timeout=5000)
            print("tapped")
        except Exception as e:
            print("tap fail", e)
            btn.click(force=True)
            print("force clicked")

        time.sleep(1.5)
        print("hash", page.evaluate("location.hash"))
        print("nativeClicks", page.evaluate("window.__nextClicks"))
        print("logs:", [x for x in logs if "compare" in x or "NATIVE" in x or "CLICK" in x])
        # Try calling React props via fiber? dump error nodes
        print(
            page.evaluate(
                """() => Array.from(document.querySelectorAll('*')).map(e => e.innerText||'')
                  .filter(t => /must be|required|cannot be|invalid/i.test(t)).slice(0,8)"""
            )
        )

        # Last resort: press Enter in the input
        loc.click()
        page.keyboard.press("Enter")
        time.sleep(1.5)
        print("after enter hash", page.evaluate("location.hash"))
        print("logs2:", [x for x in logs if "compare" in x or "NATIVE" in x])
        time.sleep(3)
        break

    browser.close()
