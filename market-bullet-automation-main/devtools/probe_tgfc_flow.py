#!/usr/bin/env python3
"""Walk TGFC live form and log every hash + inputs."""
from playwright.sync_api import sync_playwright
import json
import time

STEPS_LOG = []


def snapshot(page):
    return page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const hash = (location.hash || '').replace(/^#/, '');
      const inputs = Array.from(document.querySelectorAll('input,select,textarea'))
        .filter(e => vis(e) && e.type !== 'hidden')
        .map(e => ({name: e.name||'', id: e.id||'', type: e.type||'', ph: e.placeholder||''}));
      const btns = Array.from(document.querySelectorAll('button')).filter(vis)
        .map(b => (b.innerText||'').replace(/\\s+/g,' ').trim()).filter(t => t && t.length < 30);
      return {hash, inputs, btns};
    }""")


def set_val(page, name, value):
    return page.evaluate("""([name, value]) => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      let el = document.querySelector('input[name="' + name + '"], select[name="' + name + '"], textarea[name="' + name + '"]');
      if (!el) {
        el = Array.from(document.querySelectorAll('input,select,textarea')).find(e => vis(e) && (e.placeholder||'').toLowerCase().includes(name.toLowerCase()));
      }
      if (!el || !vis(el)) return null;
      if (el.tagName === 'SELECT') {
        el.value = value;
        el.dispatchEvent(new Event('change', {bubbles:true}));
        return el.value;
      }
      el.focus();
      el.click();
      const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      proto.set.call(el, value);
      el.dispatchEvent(new Event('input', {bubbles:true}));
      el.dispatchEvent(new Event('change', {bubbles:true}));
      el.dispatchEvent(new Event('blur', {bubbles:true}));
      return el.value;
    }""", [name, value])


def click_choice(page, text):
    return page.evaluate("""(text) => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const want = text.toLowerCase();
      for (const b of Array.from(document.querySelectorAll('button,label,[role=button]'))) {
        if (!vis(b)) continue;
        const t = (b.innerText||b.textContent||'').replace(/\\s+/g,' ').trim();
        if (t.toLowerCase().includes(want)) { b.click(); return t; }
      }
      return null;
    }""", text)


def click_next(page):
    return page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      for (const b of Array.from(document.querySelectorAll('button'))) {
        if (!vis(b)) continue;
        const t = (b.innerText||'').replace(/\\s+/g,' ').trim();
        if (/^next$/i.test(t)) { b.click(); return t; }
      }
      return null;
    }""")


FILL = {
    "email": "test@example.com",
    "ssnEC": "1234",
    "firstName": "John",
    "lastName": "Tester",
    "homePhone": "(310)555-0100",
    "address": "123 Main St",
    "ssn": "900112233",
    "employerName": "Acme Inc",
    "incomeNetMonthly": "3500",
    "incomeNextDate": "08/25/2026",
    "driverLicense": "D1234567",
    "bankRoutingNumber": "021000021",
    "bankAccountNumber": "123456789",
    "dobM": "01", "dobD": "15", "dobY": "1990",
}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    click_choice(page, "5,000")
    page.wait_for_timeout(2000)

    seen = set()
    for i in range(35):
        snap = snapshot(page)
        h = snap["hash"]
        key = (h, str(snap["inputs"]))
        if key not in seen:
            seen.add(key)
            print(f"\n--- iter {i} hash={h} ---")
            print("inputs:", json.dumps(snap["inputs"], indent=2))
            print("btns:", snap["btns"][:6])
            STEPS_LOG.append(h)

        if h == "finish":
            break
        if h in FILL:
            v = set_val(page, h, FILL[h])
            print(f"  filled {h} -> {v}")
        elif h == "lastName":
            set_val(page, "firstName", FILL["firstName"])
            set_val(page, "lastName", FILL["lastName"])
        elif h == "dobY":
            set_val(page, "dobM", FILL["dobM"])
            set_val(page, "dobD", FILL["dobD"])
            set_val(page, "dobY", FILL["dobY"])
        elif h in ("isMilitary", "isHomeOwner", "incomeSource", "incomeFrequency", "payType", "bankAccountType", "loanPurpose", "debt"):
            click_choice(page, "No" if "Military" in h else "Employed" if h == "incomeSource" else "Bi-Weekly" if h == "incomeFrequency" else "Yes" if h == "payType" else "Checking" if h == "bankAccountType" else "Other" if h == "loanPurpose" else "None")
        elif h in ("residenceMonths", "employedMonths", "bankMonths"):
            click_choice(page, "5 years")
        elif h == "state" or h == "driverLicenseState":
            sel = page.locator('select[name="state"], select[name="driverLicenseState"]').first
            if sel.count():
                sel.select_option(value="CA")
        elif h == "loanAmount":
            click_choice(page, "5,000")

        old = h
        click_next(page)
        page.wait_for_timeout(2000)
        if snapshot(page)["hash"] == old and i > 0:
            # try choice on stuck step
            for label in ["NEXT", "Continue", "No", "Yes", "Own", "Rent"]:
                pass

    print("\nSTEP ORDER:", STEPS_LOG)
    browser.close()
