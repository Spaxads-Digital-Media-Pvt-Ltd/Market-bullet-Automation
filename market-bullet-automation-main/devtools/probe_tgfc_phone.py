#!/usr/bin/env python3
"""Probe TGFC live form through homePhone step."""
from playwright.sync_api import sync_playwright
import json
import time


def dump(page, label):
    info = page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const hash = (location.hash || '').replace(/^#/, '');
      const inputs = Array.from(document.querySelectorAll('input,select,textarea')).filter(e => vis(e)).map(e => ({
        tag: e.tagName, type: e.type||'', name: e.name||'', id: e.id||'', ph: e.placeholder||''
      }));
      return {hash, inputs};
    }""")
    print(f"\n=== {label} hash={info['hash']} ===")
    print(json.dumps(info['inputs'], indent=2))


def click_next(page):
    page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const btns = Array.from(document.querySelectorAll('button')).filter(vis);
      const next = btns.find(b => /next/i.test((b.innerText||'')));
      if (next) next.click();
    }""")


def fill_named(page, name, value):
    page.evaluate("""([name, value]) => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const el = document.querySelector('input[name="' + name + '"]');
      if (!el || !vis(el)) return false;
      el.focus();
      const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      proto.set.call(el, value);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return el.value;
    }""", [name, value])


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.goto("https://togetfastcash.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    page.evaluate("""() => {
      const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText||'').includes('5,000'));
      if (b) b.click();
    }""")
    page.wait_for_timeout(3000)
    dump(page, "email")
    fill_named(page, "email", "test@example.com")
    click_next(page)
    page.wait_for_timeout(2500)
    dump(page, "after email")
    fill_named(page, "firstName", "John")
    fill_named(page, "lastName", "Tester")
    click_next(page)
    page.wait_for_timeout(2500)
    dump(page, "homePhone step")
    # try all visible inputs
    detail = page.evaluate("""() => {
      const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      return Array.from(document.querySelectorAll('input')).filter(e => vis(e)).map(e => ({
        name: e.name, id: e.id, type: e.type, ph: e.placeholder, max: e.maxLength, val: e.value
      }));
    }""")
    print("ALL INPUTS:", json.dumps(detail, indent=2))
    browser.close()
