#!/usr/bin/env python3
"""Inspect several TGFC choice steps after DOB."""
import sys, json, time
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

def h(page):
    return (page.evaluate("() => (location.hash||'').replace(/^#/,'')") or "")

def nxt(page):
    try:
        page.locator("button", has_text="NEXT").first.click(timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(1000)

def choice(page, text):
    try:
        page.locator("button", has_text=text).first.click(timeout=2000)
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    page.locator("button", has_text="5,000").first.click(); page.wait_for_timeout(1200)
    page.locator('input[name="email"]').first.fill("a@example.com"); nxt(page)
    if h(page)=="lastName":
        page.locator('input[name="firstName"]').first.fill("Alice")
        page.locator('input[name="lastName"]').first.fill("Rivera"); nxt(page)
    if h(page)=="homePhone":
        page.locator('input[name="phone"]').first.click()
        page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=30); nxt(page)
    if h(page)=="isMilitary": choice(page, "No")
    if h(page)=="address":
        page.locator('input[name="address"]').first.fill("742 Oak Street"); nxt(page)
    if h(page)=="state":
        page.locator('input[name="zip"]').first.fill("90210")
        page.locator('input[name="city"]').first.fill("Los Angeles")
        page.locator("select").first.select_option("CA"); nxt(page)
    if h(page)=="residenceMonths": choice(page, "5 years") or choice(page, "5")
    if h(page)=="isHomeOwner": choice(page, "Rent") or choice(page, "Own")
    if h(page)=="dobY":
        sels = [page.locator("select").nth(i) for i in range(page.locator("select").count()) if page.locator("select").nth(i).is_visible()]
        # get visible
        vis=[]
        for i in range(page.locator("select").count()):
            s=page.locator("select").nth(i)
            if s.is_visible(): vis.append(s)
        vis[0].select_option("03"); page.wait_for_timeout(400)
        vis[1].select_option("22"); page.wait_for_timeout(200)
        vis[2].select_option("1988"); nxt(page)

    for _ in range(12):
        step = h(page)
        detail = page.evaluate("""() => {
          const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
          return {
            hash: (location.hash||'').replace(/^#/,''),
            title: (document.querySelector('.f-wizard-step--title')||{}).innerText,
            buttons: Array.from(document.querySelectorAll('button')).filter(vis).map(b => (b.innerText||'').replace(/\\s+/g,' ').trim()).filter(Boolean),
            inputs: Array.from(document.querySelectorAll('input,select')).filter(e => vis(e) && e.type!=='hidden').map(e => ({name:e.name, tag:e.tagName, ph:e.placeholder||'', opts: e.tagName==='SELECT'?Array.from(e.options).slice(0,8).map(o=>o.value+'|'+o.text):null}))
          };
        }""")
        print(json.dumps(detail, indent=2))
        print("---")
        if step in ("finish",):
            break
        # try common advances
        if not any(choice(page, t) for t in ["Employed","Employment","Benefits","No","Yes","Weekly","Bi-Weekly","Biweekly","Semi-Monthly","Monthly","Checking","Savings","Other","None","Credit","5 years","Own","Rent"]):
            # fill first text input
            try:
                inp = page.locator("input:visible").first
                if inp.count():
                    inp.fill("3500")
                nxt(page)
            except Exception:
                nxt(page)
        page.wait_for_timeout(800)
    browser.close()
