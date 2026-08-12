#!/usr/bin/env python3
"""Dump remaining TGFC choice steps from loanPurpose onward."""
import sys, json, time
from datetime import datetime, timedelta
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

def h(page):
    return (page.evaluate("() => (location.hash||'').replace(/^#/,'')") or "")
def nxt(page):
    try: page.locator("button", has_text="NEXT").first.click(timeout=2000)
    except Exception: pass
    page.wait_for_timeout(600)
def choice(page, text):
    try:
        page.locator("button", has_text=text).first.click(timeout=2000)
        page.wait_for_timeout(600)
        return True
    except Exception:
        return False
def dump(page):
    return page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      return {
        hash:(location.hash||'').replace(/^#/,''),
        title:(document.querySelector('.f-wizard-step--title')||{}).innerText,
        buttons: Array.from(document.querySelectorAll('button')).filter(vis).map(b => ((b.innerText||b.value||'')+'|'+(b.value||'')).replace(/\\s+/g,' ').trim()).filter(t=>t && t.length<60),
        inputs: Array.from(document.querySelectorAll('input,select')).filter(e=>vis(e)&&e.type!=='hidden').map(e=>({name:e.name,tag:e.tagName,ph:e.placeholder||'',type:e.type||''}))
      };
    }""")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1800)
    page.locator("button", has_text="5,000").first.click(); page.wait_for_timeout(700)
    page.locator('input[name="email"]').first.fill("a@example.com"); nxt(page)
    page.locator('input[name="firstName"]').first.fill("Alice")
    page.locator('input[name="lastName"]').first.fill("Rivera"); nxt(page)
    page.locator('input[name="phone"]').first.click()
    page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=15); nxt(page)
    choice(page,"No")
    page.locator('input[name="address"]').first.fill("742 Oak"); nxt(page)
    page.locator('input[name="zip"]').first.fill("90210")
    page.locator('input[name="city"]').first.fill("LA")
    page.locator("select").first.select_option("CA"); nxt(page)
    choice(page,"5 Years")
    if h(page)=="isHomeOwner": choice(page,"Rent")
    vis=[]
    for i in range(page.locator("select").count()):
        s=page.locator("select").nth(i)
        if s.is_visible(): vis.append(s)
    if len(vis)>=3:
        vis[0].select_option("03"); page.wait_for_timeout(150)
        try: vis[1].select_option("22")
        except Exception: pass
        vis[2].select_option("1988"); nxt(page)
    choice(page,"Employment"); choice(page,"5 Years"); choice(page,"Bi-Weekly")
    dt=datetime.now()+timedelta(days=14)
    while dt.weekday()>=5: dt+=timedelta(days=1)
    page.evaluate("""(day)=>{for (const el of document.querySelectorAll('.Calendar__day')){if((el.className||'').includes('-disabled'))continue; if((el.innerText||'').trim()===String(day)){el.click();return}}}""", dt.day)
    page.wait_for_timeout(800)
    choice(page,"$4000 - $5000")
    if h(page)=="employerName":
        page.locator('input[name="employerName"]').first.fill("Pacific Retail"); nxt(page)
    if h(page)=="driverLicense":
        page.locator('input[name="driverLicense"]').first.fill("D8829103"); nxt(page)
    if h(page)=="driverLicenseState":
        # may be nameless select
        try: page.locator("select").first.select_option("CA")
        except Exception: pass
        nxt(page)
    if h(page)=="ssn":
        page.locator('input[name="ssn"]').first.click()
        page.locator('input[name="ssn"]').first.press_sequentially("900223344", delay=20); nxt(page)

    for i in range(15):
        d=dump(page)
        print(json.dumps(d, indent=2))
        print("---")
        step=d["hash"]
        if step=="finish":
            break
        # try click first non-next choice
        clicked=False
        for b in d["buttons"]:
            label=b.split("|")[0]
            if label.upper() in ("NEXT","") or label.startswith("Up to"):
                continue
            if choice(page, label.split()[0] if label else ""):
                clicked=True
                break
            if choice(page, label[:20]):
                clicked=True
                break
        if not clicked:
            if d["inputs"]:
                name=d["inputs"][0]["name"]
                if name:
                    try:
                        page.locator(f'input[name="{name}"]').first.fill("123456789")
                    except Exception: pass
                nxt(page)
            else:
                nxt(page)
        page.wait_for_timeout(700)
    browser.close()
