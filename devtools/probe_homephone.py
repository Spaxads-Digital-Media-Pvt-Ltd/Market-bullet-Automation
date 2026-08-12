#!/usr/bin/env python3
"""Reach homePhone on live TGFC and inspect the input."""
from playwright.sync_api import sync_playwright
import json
import time


def snap(page):
    return page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      return {
        hash: (location.hash||'').replace(/^#/,''),
        inputs: Array.from(document.querySelectorAll('input,select')).filter(e => vis(e) && e.type!=='hidden').map(e => ({
          name: e.name, id: e.id, type: e.type, ph: e.placeholder, val: e.value, max: e.maxLength
        })),
        btns: Array.from(document.querySelectorAll('button')).filter(vis).map(b => (b.innerText||'').trim()).filter(Boolean)
      };
    }""")


def type_field(page, name, value, sequential=False):
    loc = page.locator(f'input[name="{name}"]').first
    if loc.count() == 0:
        return False
    loc.wait_for(state="visible", timeout=8000)
    loc.click()
    loc.fill("")
    if sequential:
        loc.press_sequentially(value, delay=80)
    else:
        loc.fill(value)
    return loc.input_value()


def click_next(page):
    page.locator("button", has_text="NEXT").first.click(timeout=5000)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.locator("button", has_text="5,000").first.click()
    page.wait_for_timeout(2500)

    # email
    type_field(page, "email", "alice.rivera@example.com")
    click_next(page)
    page.wait_for_timeout(2000)
    print("after email", json.dumps(snap(page), indent=2))

    # ssnEC - type 4 digits sequentially
    s = snap(page)
    if s["hash"] == "ssnEC":
        type_field(page, "ssnEC", "1234", sequential=True)
        page.wait_for_timeout(2000)
        print("after ssnEC type", json.dumps(snap(page), indent=2))
        if snap(page)["hash"] == "ssnEC":
            click_next(page)
            page.wait_for_timeout(2000)

    # walk until homePhone
    for i in range(20):
        s = snap(page)
        h = s["hash"]
        print(f"\niter {i} {h}", json.dumps(s, indent=2))
        if h == "homePhone":
            # try different fill methods
            for method in ["sequential", "fill", "eval"]:
                page.reload()
                # too heavy - just test on current page
                break
            loc = page.locator('input[name="homePhone"]').first
            print("homePhone count", page.locator('input[name="homePhone"]').count())
            print("any phone inputs", page.evaluate("""() => {
              const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
              return Array.from(document.querySelectorAll('input')).filter(e => vis(e)).map(e => ({
                name: e.name, ph: e.placeholder, type: e.type, id: e.id
              }));
            }"""))
            # try sequential typing
            if page.locator('input[name="homePhone"]').count():
                type_field(page, "homePhone", "(310)555-0101", sequential=True)
                print("value after type:", page.locator('input[name="homePhone"]').first.input_value())
            else:
                # find by placeholder
                ph = page.locator('input[placeholder*="Phone" i], input[placeholder*="phone" i]').first
                print("placeholder loc count", ph.count())
                if ph.count():
                    ph.click()
                    ph.press_sequentially("3105550101", delay=80)
                    print("ph value", ph.input_value())
            break
        if h == "lastName":
            type_field(page, "firstName", "Alice")
            type_field(page, "lastName", "Rivera")
        elif h == "email":
            type_field(page, "email", "alice.rivera@example.com")
        elif h == "ssnEC":
            type_field(page, "ssnEC", "1234", sequential=True)
        click_next(page)
        page.wait_for_timeout(2500)

    browser.close()
