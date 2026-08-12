#!/usr/bin/env python3
"""Map TGFC hash steps to actual input names on live site."""
from playwright.sync_api import sync_playwright
import json
import time

ORDER = []


def snap(page):
    return page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      return {
        hash: (location.hash||'').replace(/^#/,''),
        inputs: Array.from(document.querySelectorAll('input,select,textarea')).filter(e => vis(e) && e.type!=='hidden').map(e => ({
          name: e.name||'', ph: e.placeholder||'', type: e.type||''
        })),
      };
    }""")


def fill_step(page, s):
    h = s["hash"]
    for inp in s["inputs"]:
        n = inp["name"]
        if not n:
            continue
        val = {
            "email": "test@example.com", "firstName": "John", "lastName": "Tester",
            "phone": "3105550101", "homePhone": "3105550101",
            "address": "123 Main St", "ssn": "900112233", "ssnEC": "1234",
            "employerName": "Acme", "incomeNetMonthly": "3500",
            "incomeNextDate": "08/25/2026", "driverLicense": "D1234567",
            "bankRoutingNumber": "021000021", "bankAccountNumber": "123456789",
            "dobM": "01", "dobD": "15", "dobY": "1990",
        }.get(n, "test")
        loc = page.locator(f'input[name="{n}"], select[name="{n}"]').first
        if loc.count():
            try:
                loc.click()
                loc.fill("")
                loc.press_sequentially(str(val), delay=60)
            except Exception:
                pass
    if h in ("isMilitary", "isHomeOwner", "incomeSource", "incomeFrequency", "payType", "bankAccountType", "loanPurpose", "debt", "residenceMonths", "employedMonths", "bankMonths"):
        for label in ["No", "Yes", "Employed", "Bi-Weekly", "Checking", "Other", "None", "5 years", "Own", "Rent"]:
            try:
                page.locator("button", has_text=label).first.click(timeout=1000)
                break
            except Exception:
                pass
    if h in ("state", "driverLicenseState"):
        try:
            page.locator('select[name="state"], select[name="driverLicenseState"]').first.select_option("CA")
        except Exception:
            pass


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.locator("button", has_text="5,000").first.click()
    page.wait_for_timeout(2500)

    prev = None
    for i in range(40):
        s = snap(page)
        h = s["hash"]
        if h != prev:
            ORDER.append({"hash": h, "inputs": s["inputs"]})
            print(f"{len(ORDER):2d}. #{h} -> inputs: {s['inputs']}")
            prev = h
        if h == "finish":
            break
        fill_step(page, s)
        try:
            page.locator("button", has_text="NEXT").first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1800)

    browser.close()
