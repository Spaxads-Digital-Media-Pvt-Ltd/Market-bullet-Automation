#!/usr/bin/env python3
import re
from pathlib import Path

js = Path(
    r"C:\Users\user\.cursor\projects\c-Users-user-Downloads-market-bullet-automation-main"
    r"\agent-tools\c93e2df9-a352-4150-8c3a-e1cc5bffb36f.txt"
).read_text(encoding="utf-8", errors="ignore")

# Find x= and k= and S= near BankAccountNumber component - search backwards from validation
i = js.find("Must be 4-30 digits")
chunk = js[max(0, i - 2500) : i + 100]
# find function defs
for m in re.finditer(r"(?:var|const|let|,)([kSxCvw])=function\([^)]*\)\{[^}]{0,200}\}", chunk):
    print(m.group(0)[:220])
    print("---")

# broader search for Must be 4-30 digits function x
print("\nFULL CONTEXT:\n")
print(chunk[-1500:])
