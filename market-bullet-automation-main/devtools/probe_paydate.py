#!/usr/bin/env python3
"""Figure out how TGFC next-pay calendar works."""
import sys, json, time
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta

def h(page):
    return (page.evaluate("() => (location.hash||'').replace(/^#/,'')") or "")

def nxt(page):
    try: page.locator("button", has_text="NEXT").first.click(timeout=2000)
    except Exception: pass
    page.wait_for_timeout(900)

def choice(page, text):
    try:
        page.locator("button", has_text=text).first.click(timeout=2000)
        page.wait_for_timeout(800)
        return True
    except Exception:
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    page.locator("button", has_text="5,000").first.click(); page.wait_for_timeout(1000)
    page.locator('input[name="email"]').first.fill("a@example.com"); nxt(page)
    page.locator('input[name="firstName"]').first.fill("Alice")
    page.locator('input[name="lastName"]').first.fill("Rivera"); nxt(page)
    page.locator('input[name="phone"]').first.click()
    page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=25); nxt(page)
    choice(page, "No")
    page.locator('input[name="address"]').first.fill("742 Oak"); nxt(page)
    page.locator('input[name="zip"]').first.fill("90210")
    page.locator('input[name="city"]').first.fill("LA")
    page.locator("select").first.select_option("CA"); nxt(page)
    choice(page, "5 Years")
    if h(page)=="isHomeOwner": choice(page, "Rent")
    # dob
    vis=[]
    for i in range(page.locator("select").count()):
        s=page.locator("select").nth(i)
        if s.is_visible(): vis.append(s)
    if len(vis)>=3:
        vis[0].select_option("03"); page.wait_for_timeout(300)
        try: vis[1].select_option("22")
        except Exception: vis[1].select_option(label="22")
        vis[2].select_option("1988"); nxt(page)
    choice(page, "Employment")
    choice(page, "5 Years")
    choice(page, "Bi-Weekly")
    print("AT", h(page))
    # dump calendar html
    html = page.evaluate("""() => {
      const step = document.querySelector('.f-wizard-step');
      return {
        title: (document.querySelector('.f-wizard-step--title')||{}).innerText,
        html: step ? step.innerHTML.slice(0,4000) : '',
        buttons: Array.from(document.querySelectorAll('.f-wizard-step button, .f-wizard-step [role=button], .f-wizard-step td, .f-wizard-step div')).slice(0,80).map(e => ({
          tag:e.tagName, cls:(e.className||'').toString().slice(0,40), text:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30)
        })).filter(x => x.text)
      };
    }""")
    print(json.dumps(html, indent=2)[:6000])

    # try picking a future date carefully
    target = datetime.now() + timedelta(days=14)
    # click month tab if present (August / September quick picks)
    page.evaluate("""(month) => {
      const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      const btns = Array.from(document.querySelectorAll('button')).filter(vis);
      // Prefer short month pills at top - often first two
      const pill = btns.find(b => (b.innerText||'').trim() === month);
      if (pill) pill.click();
    }""", target.strftime("%B"))
    page.wait_for_timeout(500)
    print("after month", h(page))
    # click day number in calendar grid only
    clicked = page.evaluate("""(day) => {
      const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
      // look for day cells
      const cands = Array.from(document.querySelectorAll('button,td,div,span')).filter(vis);
      for (const el of cands) {
        const t = (el.innerText||'').trim();
        if (t === String(day) && (el.className||'').toString().toLowerCase().includes('day')) { el.click(); return 'day-class'; }
      }
      for (const el of cands) {
        const t = (el.innerText||'').trim();
        if (t === String(day) && el.tagName==='BUTTON' && t.length <= 2) { el.click(); return 'day-btn'; }
      }
      return null;
    }""", target.day)
    print("day click", clicked, "hash", h(page))
    page.wait_for_timeout(1500)
    print("final", h(page), page.evaluate("""() => (document.querySelector('.f-wizard-step--title')||{}).innerText"""))
    page.wait_for_timeout(5000)
    browser.close()
