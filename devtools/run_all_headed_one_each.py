#!/usr/bin/env python3
"""Fill one Pending lead on each of the 4 offers, headed, holding the finish popup."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMOS = [
    ("To Get Fast Cash", "devtools/demo_fill_tgfc_headed.py"),
    ("Rapid Pay Day Fund", "devtools/demo_fill_rpdf_headed.py"),
    ("Easy Cash Day", "devtools/demo_fill_ecd_headed.py"),
    ("PayDayEd", "devtools/demo_fill_pde_headed.py"),
]


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_SECS"] = env.get("KEEP_BROWSER_SECS", "45")
    env.pop("FILL_ROW", None)
    env.pop("FILL_EMAIL", None)
    py = sys.executable
    results = []
    for i, (name, script) in enumerate(DEMOS, 1):
        print("\n" + "#" * 64, flush=True)
        print(f"#  {i}/4  {name}  — watch Chrome through the finish popup", flush=True)
        print("#" * 64 + "\n", flush=True)
        rc = subprocess.call([py, "-u", script], cwd=str(ROOT), env=env)
        results.append((name, "SUCCESS" if rc == 0 else f"FAILED rc={rc}"))
        print(f"\n>>> {name}: {results[-1][1]}\n", flush=True)

    print("=" * 64)
    print("ALL FOUR OFFERS")
    for name, status in results:
        print(f"  {status:12}  {name}")
    print("=" * 64)
    if any(s.startswith("FAILED") for _, s in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
