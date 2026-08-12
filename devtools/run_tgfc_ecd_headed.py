#!/usr/bin/env python3
"""Headed TGFC then ECD — verify AmONE form fill, ECD redirect CTA, sheet writeback."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = [
    ("To Get Fast Cash", "devtools/demo_fill_tgfc_headed.py"),
    ("Easy Cash Day", "devtools/demo_fill_ecd_headed.py"),
]


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    env["HEADLESS"] = "false"
    env["KEEP_BROWSER_SECS"] = env.get("KEEP_BROWSER_SECS", "40")
    py = sys.executable
    results = []
    for i, (name, script) in enumerate(RUNS, 1):
        print("\n" + "#" * 64, flush=True)
        print(f"#  {i}/2  {name}", flush=True)
        print("#" * 64 + "\n", flush=True)
        rc = subprocess.call([py, "-u", script], cwd=str(ROOT), env=env)
        results.append((name, "SUCCESS" if rc == 0 else f"FAILED rc={rc}"))
        print(f"\n>>> {name}: {results[-1][1]}\n", flush=True)
    print("=" * 64)
    for name, status in results:
        print(f"  {status:12}  {name}")
    print("=" * 64)
    if any(s.startswith("FAILED") for _, s in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
