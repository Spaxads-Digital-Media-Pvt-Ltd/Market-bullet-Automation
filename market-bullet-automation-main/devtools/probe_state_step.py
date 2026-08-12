#!/usr/bin/env python3
"""Inspect TGFC #state step DOM."""
import sys, time, json
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    page.locator("button", has_text="5,000").first.click()
    page.wait_for_timeout(2000)

    # email
    page.locator('input[name="email"]').first.fill("alice.rivera@example.com")
    page.locator("button", has_text="NEXT").first.click()
    page.wait_for_timeout(1500)
    # name
    if (page.evaluate("() => location.hash") or "").endswith("lastName"):
        page.locator('input[name="firstName"]').first.fill("Alice")
        page.locator('input[name="lastName"]').first.fill("Rivera")
        page.locator("button", has_text="NEXT").first.click()
        page.wait_for_timeout(1500)
    # phone
    if (page.evaluate("() => location.hash") or "").endswith("homePhone"):
        loc = page.locator('input[name="phone"]').first
        loc.click()
        loc.press_sequentially("3105550101", delay=50)
        page.locator("button", has_text="NEXT").first.click()
        page.wait_for_timeout(1500)
    # military
    if (page.evaluate("() => location.hash") or "").endswith("isMilitary"):
        page.locator("button", has_text="No").first.click()
        page.wait_for_timeout(1500)
    # address
    if (page.evaluate("() => location.hash") or "").endswith("address"):
        page.locator('input[name="address"]').first.fill("742 Oak Street")
        page.locator("button", has_text="NEXT").first.click()
        page.wait_for_timeout(2000)

    h = page.evaluate("() => location.hash")
    print("HASH:", h)
    detail = page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const all = Array.from(document.querySelectorAll('input,select,button,div,li,span')).filter(vis).slice(0,80);
      return {
        inputs: Array.from(document.querySelectorAll('input,select')).filter(vis).map(e => ({
          tag:e.tagName, name:e.name, id:e.id, type:e.type, ph:e.placeholder, role:e.getAttribute('role'),
          cls:(e.className||'').toString().slice(0,60), html:e.outerHTML.slice(0,200)
        })),
        buttons: Array.from(document.querySelectorAll('button')).filter(vis).map(b => (b.innerText||'').trim()).slice(0,20),
        wizard: (document.querySelector('#f-wizard-form')||{}).innerHTML?.slice(0,2500)
      };
    }""")
    print(json.dumps(detail, indent=2)[:5000])
    page.wait_for_timeout(8000)
    browser.close()
