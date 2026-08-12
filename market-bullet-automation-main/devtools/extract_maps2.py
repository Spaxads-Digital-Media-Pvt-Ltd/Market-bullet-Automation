#!/usr/bin/env python3
import re
import requests

html = requests.get("https://togetfastcash.com/", timeout=30).text
m = re.search(r"/lib/main\?[^\"]+", html)
js = requests.get("https://togetfastcash.com" + m.group(0), timeout=60).text
mm = re.search(r'\{0:"No Debt"[^}]+\}', js)
print("DEBT MAP:", mm.group(0) if mm else None)
mm2 = re.search(r'excellent:"Excellent"[^}]+\}', js, re.I)
print("CREDIT:", mm2.group(0) if mm2 else None)
mm3 = re.search(r'Debt Consolidation.{0,200}', js)
print("PURPOSE:", mm3.group(0)[:200] if mm3 else None)
mm4 = re.search(r'Direct Deposit.{0,200}', js)
print("DD:", mm4.group(0)[:200] if mm4 else None)
