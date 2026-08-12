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

REACT_CLICK = """() => {
  const btn = document.querySelector('button.f-wizard-step--buttons--next');
  if (!btn) return 'no-btn';
  const key = Object.keys(btn).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
  if (!key) return 'no-fiber';
  let fiber = btn[key];
  for (let i = 0; i < 8 && fiber; i++, fiber = fiber.return) {
    const props = fiber.memoizedProps || fiber.pendingProps || {};
    if (typeof props.onClick === 'function') {
      props.onClick({ preventDefault() {}, stopPropagation() {}, target: btn, currentTarget: btn });
      return 'fiber-onclick-' + i;
    }
  }
  // fallback
  btn.click();
  return 'dom-click';
}"""

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

        loc = page.locator('input[name="bankAccountNumber"]').first
        loc.click()
        page.keyboard.type(f["account_number"], delay=50)
        time.sleep(0.3)
        # also fire input via React on bank field
        page.evaluate(
            """(v) => {
              const el = document.querySelector('input[name=bankAccountNumber]');
              const key = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactProps'));
              // set via props onChange if present
              const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
              if (propsKey && el[propsKey] && el[propsKey].onChange) {
                el[propsKey].onChange({ target: { value: v } });
                return 'props-onchange';
              }
              return 'no-props';
            }""",
            f["account_number"],
        )
        time.sleep(0.2)
        result = page.evaluate(REACT_CLICK)
        print("react click", result)
        time.sleep(2)
        print("hash", page.evaluate("location.hash"))
        print("compare logs", [x for x in logs if "compare" in x.lower()])
        print("all recent", logs[-10:])
        time.sleep(4)
        break

    browser.close()
