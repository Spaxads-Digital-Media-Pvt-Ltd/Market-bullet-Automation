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
    page.wait_for_timeout(700)
def choice(page, text):
    try:
        page.locator("button", has_text=text).first.click(timeout=2000)
        page.wait_for_timeout(700)
        return True
    except Exception:
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    page.locator("button", has_text="5,000").first.click(); page.wait_for_timeout(800)
    page.locator('input[name="email"]').first.fill("a@example.com"); nxt(page)
    page.locator('input[name="firstName"]').first.fill("Alice")
    page.locator('input[name="lastName"]').first.fill("Rivera"); nxt(page)
    page.locator('input[name="phone"]').first.click()
    page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=20); nxt(page)
    choice(page,"No")
    page.locator('input[name="address"]').first.fill("742 Oak"); nxt(page)
    page.locator('input[name="zip"]').first.fill("90210")
    page.locator('input[name="city"]').first.fill("LA")
    page.locator("select").first.select_option("CA"); nxt(page)
    choice(page,"5 Years")
    if h(page)=="isHomeOwner": choice(page,"Rent")
    vis=[page.locator("select").nth(i) for i in range(page.locator("select").count()) if page.locator("select").nth(i).is_visible()]
    # rebuild visible list properly
    vis=[]
    for i in range(page.locator("select").count()):
        s=page.locator("select").nth(i)
        if s.is_visible(): vis.append(s)
    if len(vis)>=3:
        vis[0].select_option("03"); page.wait_for_timeout(200)
        try: vis[1].select_option("22")
        except Exception: pass
        vis[2].select_option("1988"); nxt(page)
    choice(page,"Employment"); choice(page,"5 Years"); choice(page,"Bi-Weekly")
    # pick calendar day
    dt = datetime.now()+timedelta(days=14)
    while dt.weekday()>=5: dt+=timedelta(days=1)
    page.evaluate("""(day) => {
      const cells = Array.from(document.querySelectorAll('.Calendar__day')).filter(e => e.offsetParent);
      for (const el of cells) {
        if ((el.className||'').includes('-disabled')) continue;
        if ((el.innerText||'').trim()===String(day)) { el.click(); return true; }
      }
    }""", dt.day)
    page.wait_for_timeout(1200)
    print("HASH", h(page))
    detail = page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      return {
        title: (document.querySelector('.f-wizard-step--title')||{}).innerText,
        inputs: Array.from(document.querySelectorAll('input,select,button')).filter(vis).map(e => ({
          tag:e.tagName, name:e.name||'', type:e.type||'', ph:e.placeholder||'', text:(e.innerText||'').trim().slice(0,40),
          html:e.outerHTML.slice(0,160)
        }))
      };
    }""")
    print(json.dumps(detail, indent=2)[:4000])
    browser.close()
