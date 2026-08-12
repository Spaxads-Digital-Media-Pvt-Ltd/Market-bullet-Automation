#!/usr/bin/env python3
"""Inspect TGFC #dobY step."""
import sys, json, time
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

def hash_(page):
    return (page.evaluate("() => (location.hash||'').replace(/^#/,'')") or "")

def next_(page):
    page.locator("button", has_text="NEXT").first.click()
    page.wait_for_timeout(1200)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    page.locator("button", has_text="5,000").first.click()
    page.wait_for_timeout(1500)
    page.locator('input[name="email"]').first.fill("a@example.com"); next_(page)
    if hash_(page) == "lastName":
        page.locator('input[name="firstName"]').first.fill("Alice")
        page.locator('input[name="lastName"]').first.fill("Rivera"); next_(page)
    if hash_(page) == "homePhone":
        page.locator('input[name="phone"]').first.click()
        page.locator('input[name="phone"]').first.press_sequentially("3105550101", delay=40); next_(page)
    if hash_(page) == "isMilitary":
        page.locator("button", has_text="No").first.click(); page.wait_for_timeout(1000)
    if hash_(page) == "address":
        page.locator('input[name="address"]').first.fill("742 Oak Street"); next_(page)
    if hash_(page) == "state":
        page.locator('input[name="zip"]').first.fill("90210")
        page.locator('input[name="city"]').first.fill("Los Angeles")
        page.locator("select").first.select_option("CA"); next_(page)
    if hash_(page) == "residenceMonths":
        page.locator("button", has_text="5 years").first.click(); page.wait_for_timeout(1000)
    if hash_(page) == "isHomeOwner":
        page.locator("button", has_text="Rent").first.click(); page.wait_for_timeout(1000)
    print("NOW HASH:", hash_(page))
    detail = page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      return {
        inputs: Array.from(document.querySelectorAll('input,select')).filter(vis).map(e => ({
          tag:e.tagName, name:e.name, id:e.id, type:e.type, ph:e.placeholder,
          opts: e.tagName==='SELECT' ? Array.from(e.options).slice(0,8).map(o=>o.value+'|'+o.text) : null,
          html: e.outerHTML.slice(0,180)
        })),
        title: (document.querySelector('.f-wizard-step--title')||{}).innerText,
        body: (document.querySelector('.f-wizard-step--body')||{}).innerText?.slice(0,400)
      };
    }""")
    print(json.dumps(detail, indent=2))
    browser.close()
