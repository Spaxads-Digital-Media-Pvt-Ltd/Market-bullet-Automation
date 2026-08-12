#!/usr/bin/env python3
import re
import requests

html = requests.get("https://togetfastcash.com/", timeout=30).text
m = re.search(r"/lib/main\?[^\"]+", html)
print("script", m.group(0) if m else None)
js = requests.get("https://togetfastcash.com" + m.group(0), timeout=60).text
for key in ["Under", "None", "Debt Consolidation", "Excellent", "Checking", "Direct Deposit", "Own my home", "Rent"]:
    print(key, js.count(key))
# nearby debt UI strings
for pat in [r".{0,40}No Debt.{0,40}", r".{0,40}Under \$.{0,40}", r".{0,60}creditScore.{0,80}", r"DebtAmount.{0,120}"]:
    mm = re.search(pat, js, re.I)
    print(pat, "=>", (mm.group(0)[:150] if mm else None))
# extract quoted strings containing $
dollars = sorted(set(re.findall(r'"([^"]{0,5}\$[^"]{0,40})"', js)))
print("dollar strings", dollars[:40])
