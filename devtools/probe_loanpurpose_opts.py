#!/usr/bin/env python3
import sys, json, time
from datetime import datetime, timedelta
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

def h(page):
    return (page.evaluate("() => (location.hash||'').replace(/^#/,'')") or "")
def nxt(page):
    try: page.locator("button", has_text="NEXT").first.click(timeout=2000)
    except Exception: pass
    page.wait_for_timeout(500)
def choice(page, text):
    try:
        page.locator("button", has_text=text).first.click(timeout=2000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    page.locator("button", has_text="5,000").first.click(); page.wait_for_timeout(600)
    page.locator('input[name="email"]').first.fill("a@example.com"); nxt(page)
    page.locator('input[name="firstName"]').first.fill("Alice")
    page.locator('input[name="lastName"]').first.fill("Rivera"); nxt(page)
    page.locator('input[name="phone"]').first.click()
    page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=15); nxt(page)
    choice(page, "No")
    page.locator('input[name="address"]').first.fill("742 Oak"); nxt(page)
    page.locator('input[name="zip"]').first.fill("90210")
    page.locator('input[name="city"]').first.fill("LA")
    page.locator("select").first.select_option("CA"); nxt(page)
    choice(page, "5 Years")
    if h(page) == "isHomeOwner":
        choice(page, "Rent")
    vis = []
    for i in range(page.locator("select").count()):
        s = page.locator("select").nth(i)
        if s.is_visible():
            vis.append(s)
    if len(vis) >= 3:
        vis[0].select_option("03"); page.wait_for_timeout(100)
        try:
            vis[1].select_option("22")
        except Exception:
            pass
        vis[2].select_option("1988"); nxt(page)
    choice(page, "Employment"); choice(page, "5 Years"); choice(page, "Bi-Weekly")
    dt = datetime.now() + timedelta(days=14)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    page.evaluate(
        """(day)=>{for (const el of document.querySelectorAll('.Calendar__day')){if((el.className||'').includes('-disabled'))continue; if((el.innerText||'').trim()===String(day)){el.click();return}}}""",
        dt.day,
    )
    page.wait_for_timeout(600)
    choice(page, "$4000 - $5000")
    page.locator('input[name="employerName"]').first.fill("Pacific"); nxt(page)
    page.locator('input[name="driverLicense"]').first.fill("D8829103"); nxt(page)
    try:
        page.locator("select").first.select_option("CA")
    except Exception:
        pass
    nxt(page)
    page.locator('input[name="ssn"]').first.click()
    page.locator('input[name="ssn"]').first.press_sequentially("900223344", delay=15); nxt(page)
    print("AT", h(page))
    opts = page.evaluate(
        """() => {
      const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      return Array.from(document.querySelectorAll('select')).filter(vis).map(s => ({
        id:s.id, options: Array.from(s.options).map(o => o.value+'|'+o.textContent.trim())
      }));
    }"""
    )
    print(json.dumps(opts, indent=2))
    # select Good + Other and next
    sels = [page.locator("select").nth(i) for i in range(page.locator("select").count()) if page.locator("select").nth(i).is_visible()]
    sels = []
    for i in range(page.locator("select").count()):
        s = page.locator("select").nth(i)
        if s.is_visible():
            sels.append(s)
    if len(sels) >= 2:
        print("select0 options", sels[0].evaluate("el => Array.from(el.options).map(o=>o.value+'|'+o.text)"))
        print("select1 options", sels[1].evaluate("el => Array.from(el.options).map(o=>o.value+'|'+o.text)"))
        # try pick by index 1
        sels[0].select_option(index=1)
        sels[1].select_option(index=1)
        nxt(page)
        print("AFTER", h(page), page.evaluate("() => (document.querySelector('.f-wizard-step--title')||{}).innerText"))
    browser.close()
