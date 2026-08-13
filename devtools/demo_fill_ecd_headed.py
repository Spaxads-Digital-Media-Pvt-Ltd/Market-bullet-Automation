#!/usr/bin/env python3
"""Fill one Easy Cash Day lead from the sheet in a visible Chrome window."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
os.environ["HEADLESS"] = "false"
os.environ["BROWSER_CHANNEL"] = "chrome"
os.environ["PYTHONUTF8"] = "1"

from utils.sheet_handler import SheetHandler
from core.form_filler_ecd import FormFiller, FormFillerError


def _rotating_proxy() -> str | None:
    cfg_path = Path("ui_config.json")
    if not cfg_path.exists():
        return None
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    proxy = (saved.get("proxy") or {}).get("rotating_url") or ""
    return proxy.strip() or None


def main() -> None:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    cfg["target"]["url"] = "https://easycashday.com/"
    cfg["browser"] = {"channel": "chrome"}
    cfg.setdefault("screenshots", {})["enabled"] = True
    cfg["screenshots"]["directory"] = "screenshots/easy_cash_day_demo"

    sheet = SheetHandler(
        cfg,
        sheet_url=os.getenv("SHEET_URL_ECD"),
        worksheet_name=os.getenv("SHEET_WS_ECD", "Easy Cash Day"),
    )
    pending = sheet.get_pending_rows()
    if not pending:
        print("No Pending rows in Easy Cash Day.")
        sys.exit(1)

    want_email = (os.getenv("FILL_EMAIL") or "").strip().lower()
    row = pending[0]
    if want_email:
        match = [r for r in pending if str(r.get("Email Address") or "").strip().lower() == want_email]
        if not match:
            print(f"No Pending row with email {want_email}")
            sys.exit(1)
        row = match[0]
    row_num = row["_row_number"]
    proxy_url = _rotating_proxy()
    print("=" * 60)
    print("  LIVE DEMO — Easy Cash Day (headed Chrome)")
    print("=" * 60)
    print(f"  Sheet row : {row_num}")
    print(f"  Name      : {row.get('First Name')} {row.get('Last Name')}")
    print(f"  Email     : {row.get('Email Address')}")
    print(f"  Phone     : {row.get('Phone Number')}")
    print(f"  DOB       : {row.get('Date of Birth (DOB)')}")
    print(f"  SSN       : {row.get('SSN Full')}")
    print(f"  Account   : {row.get('Account Number')}")
    print(f"  Target    : {cfg['target']['url']}")
    print(f"  Proxy     : {'rotating US' if proxy_url else 'direct'}")
    print("  Watch the Chrome window — each wizard step will be filled.")
    print("=" * 60)

    sheet.mark_in_progress(row_num)
    filler = FormFiller(cfg)
    fingerprint = {
        "viewport": {"width": 1100, "height": 860},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "is_mobile": False,
        "has_touch": False,
        "device_scale_factor": 1,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "color_scheme": "light",
    }

    try:
        def _write(result: dict) -> None:
            sheet.update_row(
                row_num,
                status="Success",
                notes=result.get("notes", ""),
                submission_id=result.get("submission_id", ""),
                proxy_used="rotating" if proxy_url else "direct",
            )
            print("\nSHEET UPDATED: Success\n", flush=True)

        result = filler.process_row(
            row=row,
            fingerprint=fingerprint,
            proxy_url=proxy_url,
            row_number=row_num,
            on_result=_write,
        )
        sheet.update_row(
            row_num,
            status="Success",
            notes=result.get("notes", ""),
            submission_id=result.get("submission_id", ""),
            proxy_used="rotating" if proxy_url else "direct",
        )
        print("\nSUCCESS:", result)
    except FormFillerError as e:
        sheet.update_row(
            row_num,
            status="Failed",
            notes=f"[{e.error_type}] {e}",
            proxy_used="rotating" if proxy_url else "direct",
        )
        print(f"\nFAILED [{e.error_type}]: {e}")
        sys.exit(1)
    except Exception as e:
        sheet.update_row(
            row_num,
            status="Failed",
            notes=f"[unexpected] {e}",
            proxy_used="rotating" if proxy_url else "direct",
        )
        print(f"\nUNEXPECTED: {e}")
        raise


if __name__ == "__main__":
    main()
