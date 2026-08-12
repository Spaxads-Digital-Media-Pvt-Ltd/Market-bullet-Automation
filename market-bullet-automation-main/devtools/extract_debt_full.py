#!/usr/bin/env python3
import re
import requests

html = requests.get("https://togetfastcash.com/", timeout=30).text
m = re.search(r"/lib/main\?[^\"]+", html)
js = requests.get("https://togetfastcash.com" + m.group(0), timeout=60).text
# all No Debt contexts
for mm in re.finditer(r".{0,30}No Debt.{0,200}", js):
    print(mm.group(0))
    print("---")
# payType buttons
for mm in re.finditer(r".{0,40}directDeposit.{0,120}", js, re.I):
    print("DDCTX", mm.group(0)[:160])
