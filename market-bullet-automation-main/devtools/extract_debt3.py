#!/usr/bin/env python3
import re
import requests

html = requests.get("https://togetfastcash.com/", timeout=30).text
m = re.search(r"/lib/main\?[^\"]+", html)
js = requests.get("https://togetfastcash.com" + m.group(0), timeout=60).text
print([s for s in re.findall(r'"([^"]*\$[^"]*)"', js) if "Debt" in s or "7,500" in s or "1,000" in s or "5,000" in s][:40])
# look for 1:" or 5001
mm = re.search(r'No Debt.{0,300}', js)
print(mm.group(0) if mm else None)
# maybe another map
for pat in [r'1:"[^"]{0,40}"', r'5001:"[^"]+"', r'2501:"[^"]+"', r'1001:"[^"]+"']:
    print(pat, re.findall(pat, js)[:10])
