#!/usr/bin/env python3
"""Find how TGFC custom Input expects onChange for bankAccountNumber."""
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
acct = f["account_number"]

INSPECT = """(acct) => {
  const el = document.querySelector('input[name="bankAccountNumber"]');
  if (!el) return {err:'no input'};
  const out = {dom: el.value, tag: el.tagName, type: el.type, keys: Object.keys(el).filter(k => k.startsWith('__react'))};
  const propsKey = out.keys.find(k => k.startsWith('__reactProps'));
  if (propsKey) {
    const p = el[propsKey];
    out.propKeys = Object.keys(p||{});
    out.hasOnChange = typeof (p&&p.onChange) === 'function';
    out.hasOnInput = typeof (p&&p.onInput) === 'function';
  }
  // Try value-style onChange up the fiber tree
  const fiberKey = out.keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
  let fiber = fiberKey ? el[fiberKey] : null;
  const tries = [];
  for (let i = 0; i < 12 && fiber; i++, fiber = fiber.return) {
    const props = fiber.memoizedProps || {};
    if (typeof props.onChange === 'function') {
      tries.push('fiber-'+i);
      try { props.onChange({ target: { value: acct, name: 'bankAccountNumber' } }); tries.push('event-ok-'+i); } catch(e) { tries.push('event-fail-'+i+':'+e.message); }
      try { props.onChange(acct); tries.push('value-ok-'+i); } catch(e) { tries.push('value-fail-'+i+':'+e.message); }
    }
    if (props.name === 'bankAccountNumber' || props.label === 'Bank Account Number') {
      tries.push('named-'+i);
    }
  }
  out.tries = tries;
  out.domAfter = el.value;
  return out;
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    context = browser.new_context(
        viewport={"width": 430, "height": 900},
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
        is_mobile=True, has_touch=True, device_scale_factor=2.75,
        locale="en-US", timezone_id="America/Los_Angeles",
    )
    page = context.new_page()
    logs = []
    page.on("console", lambda m: logs.append(m.text))
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

        print("BEFORE", page.evaluate("() => ({bank: document.querySelector('input[name=bankName]')?.value, acct: document.querySelector('input[name=bankAccountNumber]')?.value})"))
        info = page.evaluate(INSPECT, acct)
        print("INSPECT", info)
        time.sleep(0.5)
        # click next via react
        filler._react_click(page, "button.f-wizard-step--buttons--next")
        time.sleep(2)
        print("hash", page.evaluate("location.hash"))
        print("compare", [x for x in logs if "compare" in x.lower()])
        print("errors", page.evaluate("""() => Array.from(document.querySelectorAll('*')).map(e => (e.childNodes && e.childNodes.length===1 && e.firstChild.nodeType===3) ? e.textContent.trim() : '').filter(t => /must be|required|cannot|invalid|digit/i.test(t)).slice(0,10)"""))
        time.sleep(3)
        break

    browser.close()
