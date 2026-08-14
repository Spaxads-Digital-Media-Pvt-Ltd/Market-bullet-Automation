"""
core/lead_platform.py — shared layer for the lead-funnel platform.

Several loan-funnel sites share the same lead platform: identical 31-field vocabulary (confirmed from each site's
own JS), identical option semantics, and the same backend endpoints
(``/?cmd=ExtApplyV2`` progressive save, ``/?cmd=RenderResult`` on completion).

Everything that depends only on that shared data model lives here — reading a
sheet row, mapping its values onto the platform's option codes, validating
against the rules the sites enforce client-side, and the browser lifecycle.
Only the DOM interaction differs per site, so each filler subclasses
``BasePlatformFiller`` and implements the handful of abstract members below.

This split exists deliberately: the previous generation of this codebase had
five near-identical copies of one filler (8 415 lines) that had already drifted
into divergent bugs. Site-specific code belongs in a subclass; anything else
belongs here.
"""
from __future__ import annotations

import os
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from utils.proxy_manager import ProxyManager
from utils.stealth import inject_stealth

log = structlog.get_logger(__name__)


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _sheet_digits(raw: str) -> str:
    """Digit string from a sheet cell — handles scientific notation (4.45E+8)."""
    s = str(raw or "").strip().replace(",", "").replace(" ", "")
    if re.match(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$", s):
        try:
            return str(int(float(s)))
        except (ValueError, OverflowError):
            pass
    return _digits(s)


def _ssn_digits(raw: str) -> str:
    """9-digit SSN if it would pass typical site checks; else empty."""
    d = _sheet_digits(raw)
    if len(d) != 9:
        return ""
    area = int(d[:3])
    if area in (0, 666) or area >= 900:
        return ""
    if d[3:5] == "00" or d[5:] == "0000":
        return ""
    if len(set(d)) == 1:
        return ""
    return d


def _ssn_format(raw: str) -> str:
    d = _digits(raw)
    if len(d) != 9:
        return ""
    return f"{d[:3]}-{d[3:5]}-{d[5:]}"


def _ssn_invalid_reason(raw: str) -> str:
    d = _sheet_digits(raw)
    if len(d) != 9:
        return f"must be 9 digits, got {len(d)}"
    area = int(d[:3])
    if area in (0, 666) or area >= 900:
        return "area cannot be 000, 666, or 900-999"
    if d[3:5] == "00":
        return "group cannot be 00"
    if d[5:] == "0000":
        return "serial cannot be 0000"
    if len(set(d)) == 1:
        return "cannot be all the same digit"
    return ""


def _account_digits(raw: str) -> str:
    return _sheet_digits(raw)


def _account_invalid_reason(acct: str, routing: str = "") -> str:
    d = _account_digits(acct)
    if not d:
        return "empty"
    if len(d) < 6:
        return f"must be 6-17 digits, got {len(d)}"
    if len(d) > 17:
        return f"must be 6-17 digits, got {len(d)}"
    if len(set(d)) == 1:
        return "cannot be all the same digit"
    if routing and d == _digits(routing):
        return "cannot match the routing number"
    return ""


def _aba_checksum_ok(routing: str) -> bool:
    """Both sites run this exact check client-side before they will advance."""
    if len(routing) != 9 or not routing.isdigit():
        return False
    d = [int(c) for c in routing]
    total = (3 * (d[0] + d[3] + d[6])
             + 7 * (d[1] + d[4] + d[7])
             + 1 * (d[2] + d[5] + d[8]))
    return total % 10 == 0


class FormFillerError(Exception):
    """Base exception for form-filling errors."""

    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type


class BasePlatformFiller:
    """Sheet row -> platform values -> browser session. DOM work is a subclass job."""

    # ---- subclass contract -------------------------------------------------
    #   default_url        : str                     fallback target URL
    #   _prepare(page, row_number)                   consent gates, etc. (optional)
    #   _fill_form(page, fields, row_number, stop)   drive the wizard; return outcome
    # ------------------------------------------------------------------------
    default_url = ""

    _STATE_CODES = {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
        "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
        "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
        "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
        "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
        "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
        "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
        "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
        "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
        "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
        "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
    }

    # (upper bound exclusive, option value) — first bracket the income fits.
    _NETIM_BRACKETS = [
        (1500, "1500"), (2000, "2000"), (2500, "2500"), (3000, "3000"),
        (4000, "4000"), (5000, "5000"), (6000, "6000"), (7000, "7000"),
        (8000, "8000"), (9000, "9000"), (10000, "10000"),
    ]
    _NETIM_TOP = "11000"

    _DEBT_BRACKETS = [
        (1, "0"), (5000, "4999"), (10000, "9999"), (15000, "14999"),
        (20000, "19999"), (25000, "24999"), (30000, "29999"), (35000, "34999"),
        (40000, "39999"), (45000, "44999"), (50000, "49999"),
    ]
    _DEBT_TOP = "50000"

    _TENURE_STEPS = [(12, "12"), (24, "24"), (36, "36"), (48, "48")]
    _TENURE_TOP = "60"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._target = config.get("target", {})
        self._delays = config.get("delays", {})
        self._ss_dir = Path(config.get("screenshots", {}).get("directory", "screenshots"))
        self._ss_dir.mkdir(parents=True, exist_ok=True)
        self._save_shots = bool(config.get("screenshots", {}).get("enabled", False))
        self._max_steps = int(config.get("form", {}).get("max_steps", 40))
        self._crashed = False   # per-row; reset at the top of process_row


    # ---------------------------------------------------------------- public

    def process_row(
        self,
        row: dict[str, Any],
        fingerprint: dict[str, Any],
        proxy_url: str | None,
        row_number: int,
        stop_event=None,
        on_result=None,
    ) -> dict[str, Any]:
        """Fill and submit the application for one sheet row."""
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        fields = self._parse_fields(row)
        self._validate_required_fields(fields)
        self._dup_reset_done = 0

        url = (self._target.get("url") or self.default_url).strip()
        page: Page | None = None
        self._crashed = False

        with sync_playwright() as pw:
            launch_args: dict[str, Any] = {
                "headless": headless,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            # Marker flag so the UI's Stop can force-kill this exact browser if it
            # blocks mid-call (e.g. a page that never renders).
            engine_tag = self._config.get("browser", {}).get("engine_tag")
            if engine_tag:
                launch_args["args"].append(f"--lead-engine-tag={engine_tag}")
            # Playwright's *bundled* Chromium reproducibly crashes its renderer
            # on these sites part-way through loading the third-party
            # fraud-detection script — headless and headed alike.  A stock Google
            # Chrome install runs the identical page without trouble, so we
            # launch that channel by default.  BROWSER_CHANNEL=chromium forces
            # the bundled build (expect crashes).
            # Per-offer channel comes from the engine's own config dict (so
            # concurrent engines can use different browsers without racing on a
            # shared env var); fall back to BROWSER_CHANNEL, then "chrome".
            channel = (self._config.get("browser", {}).get("channel")
                       or os.getenv("BROWSER_CHANNEL", "chrome")).strip().lower()
            if channel and channel not in ("chromium", "bundled", "default"):
                launch_args["channel"] = channel
            if proxy_url:
                launch_args["proxy"] = ProxyManager.to_playwright_proxy(proxy_url)

            try:
                browser: Browser = pw.chromium.launch(**launch_args)
            except Exception as exc:
                if "channel" not in launch_args:
                    raise
                raise FormFillerError(
                    f"Could not launch browser channel '{channel}': {exc}. "
                    f"Install Google Chrome, or set BROWSER_CHANNEL=chromium to use "
                    f"Playwright's bundled build (which crashes on this target).",
                    error_type="browser_launch",
                ) from exc
            try:
                ctx_args = self._clean_fingerprint(fingerprint)
                context: BrowserContext = browser.new_context(**ctx_args)
                page = context.new_page()

                def _on_crash(_p: Page) -> None:
                    self._crashed = True
                    log.error("form.page_crashed", row=row_number)

                page.on("crash", _on_crash)
                inject_stealth(page, fingerprint)

                log.info("form.navigating", url=url, row=row_number)
                self._goto(page, url, row_number, stop_event)
                self._live(page)

                self._prepare(page, row_number)
                outcome = self._fill_form(page, fields, row_number, stop_event)
                extra = self._click_post_congrats_cta(page, fields, row_number, stop_event)
                if extra:
                    outcome = f"{outcome} → {extra}"

                self._screenshot(self._newest_page(page), row_number, "success")
                submission_id = str(uuid.uuid4())[:8].upper()
                log.info("form.success", row=row_number, submission_id=submission_id,
                         outcome=outcome)
                result = {
                    "status": "Success",
                    "notes": f"Submitted — {outcome}",
                    "submission_id": submission_id,
                }
                # Write the sheet BEFORE the headed hold so Status is not stuck on Pending.
                if callable(on_result):
                    try:
                        on_result(result)
                    except Exception as exc:
                        log.warning("form.on_result_fail", error=str(exc)[:120])
                try:
                    hold = float(os.getenv("KEEP_BROWSER_SECS", "0") or 0)
                except ValueError:
                    hold = 0
                if hold > 0 and not headless:
                    print(f"\n*** Holding browser {hold:.0f}s so you can see the last page ***\n", flush=True)
                    time.sleep(hold)
                context.close()
                return result

            except FormFillerError:
                if page:
                    try:
                        self._screenshot(page, row_number, "error")
                    except Exception:
                        pass
                raise
            except Exception as exc:
                error_type = self._classify_error(exc)
                log.exception("form.unexpected", row=row_number, error_type=error_type)
                if page:
                    try:
                        self._screenshot(page, row_number, error_type)
                    except Exception:
                        pass
                raise FormFillerError(str(exc), error_type=error_type) from exc
            finally:
                self._close_browser(browser)

    # --------------------------------------------------------------- navigation

    def _goto(self, page: Page, url: str, row_number: int, stop_event) -> None:
        """Load the landing page, retrying so a bad rotating-proxy exit IP or a
        renderer crash costs one reload rather than the whole lead."""
        last_err: Exception | None = None
        for attempt in range(1, 4):
            self._check_stop(stop_event)
            last_err = None
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                last_err = e
            landed = ""
            try:
                landed = page.url or ""
            except Exception as e:
                last_err = e
            if not last_err and not landed.startswith("chrome-error://"):
                return
            log.warning("form.nav_retry", attempt=attempt, row=row_number,
                        url=landed[:60], error=str(last_err)[:90] if last_err else "chrome-error")
            if attempt < 3:
                time.sleep(3)
        raise FormFillerError(
            f"Navigation failed: {last_err}" if last_err
            else "Page failed to load — proxy unreachable or blocked",
            error_type="proxy_error",
        )


    # ---------------------------------------------------------------- hooks

    def _prepare(self, page: Page, row_number: int) -> None:
        """Clear anything standing between the load and the first step
        (consent gates, splash screens). Default: nothing to do."""

    def _fill_form(self, page: Page, fields: dict, row_number: int, stop_event) -> str:
        raise NotImplementedError

    def _ssn_last4(self, f: dict) -> str:
        return _digits(f.get("last_ssn") or f.get("ssn") or "")[-4:]

    def _ssn_first5(self, f: dict) -> str:
        d = _digits(f.get("ssn") or "")
        return d[:5] if len(d) >= 5 else d

    def _is_duplicate_identity_screen(self, page: Page) -> bool:
        """True when the site recognized email / SSN / phone and asks to verify."""
        try:
            return bool(page.evaluate(
                """() => {
                    const t = ((document.body && document.body.innerText) || '')
                        .replace(/\\s+/g, ' ');
                    return /last 4 digits of your social|last four digits of your social|not \\w+\\?\\s*start a new form|start a new form|welcome back|we (found|located) your (file|application)|hi \\w+\\.\\s*please enter|please enter the last 4/i.test(t);
                }"""
            ))
        except Exception:
            return False

    def _is_nav_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            s in msg
            for s in (
                "execution context",
                "frame was detached",
                "target closed",
                "target page",
                "navigation",
                "connection closed",
                "page crashed",
            )
        )

    def _click_start_new_form(self, page: Page) -> bool:
        """Click 'Not NAME? Start a new form' so a duplicate is filled like a new lead."""
        for pat in (r"start a new form", r"not \w+\s*\?", r"not you"):
            try:
                loc = page.get_by_text(re.compile(pat, re.I)).first
                if loc.count() == 0:
                    continue
                loc.click(timeout=4000, force=True)
                log.info("form.duplicate_new_form", action=pat, via="playwright")
                print("[DUP] clicked Start a new form — filling like a unique lead", flush=True)
                time.sleep(1.2)
                return True
            except Exception:
                continue
        try:
            clicked = page.evaluate(
                """() => {
                    const vis = e => e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    const re = /start a new form|not \\w+\\s*\\?|not you/i;
                    const nodes = Array.from(document.querySelectorAll(
                        'a,button,[role=button],span,div,p,label'
                    ));
                    for (const el of nodes) {
                        if (!vis(el)) continue;
                        const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        if (!t || t.length > 90) continue;
                        if (!re.test(t)) continue;
                        const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
                        if (propsKey && el[propsKey] && typeof el[propsKey].onClick === 'function') {
                            el[propsKey].onClick({
                                preventDefault() {}, stopPropagation() {},
                                target: el, currentTarget: el, type: 'click',
                            });
                        } else {
                            el.click();
                        }
                        return t.slice(0, 60);
                    }
                    return '';
                }"""
            )
        except Exception:
            clicked = ""
        if clicked:
            log.info("form.duplicate_new_form", action=clicked, via="dom")
            print("[DUP] clicked Start a new form — filling like a unique lead", flush=True)
            time.sleep(1.2)
            return True
        return False

    def _fill_duplicate_verify_fields(self, page: Page, f: dict) -> bool:
        """Fill last-4 SSN (or last-4 phone) on a returning-user verify step."""
        last4 = self._ssn_last4(f)
        phone4 = _digits(f.get("phone") or "")[-4:]
        full = _digits(f.get("ssn") or "")
        first5 = self._ssn_first5(f)
        try:
            inputs = page.evaluate(
                """() => {
                    const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    return Array.from(document.querySelectorAll('input,textarea'))
                        .filter(e => vis(e) && e.type !== 'hidden'
                                 && e.type !== 'checkbox' && e.type !== 'radio')
                        .map(e => ({
                            name: e.name || e.id || '',
                            max: parseInt(e.maxLength, 10) || 0,
                            ph: (e.placeholder || '').toLowerCase(),
                            label: (
                                (e.getAttribute('aria-label') || '') + ' ' +
                                ((e.labels && e.labels[0] && e.labels[0].innerText) || '') + ' ' +
                                ((e.previousElementSibling && e.previousElementSibling.innerText) || '')
                            ).toLowerCase(),
                        }));
                }"""
            ) or []
        except Exception:
            inputs = []

        def _put(name: str, val: str) -> bool:
            if not name or not val:
                return False
            fn = getattr(self, "_text_wizard", None)
            if callable(fn):
                return bool(fn(page, name, val))
            return False

        filled = False
        for inp in inputs:
            name = str(inp.get("name") or "")
            mx = int(inp.get("max") or 0)
            blob = f"{name} {inp.get('ph', '')} {inp.get('label', '')}".lower()
            if any(k in blob for k in ("ssn", "social", "ssnfc", "ssnec", "ssnv")):
                if mx >= 9:
                    val = full or last4
                elif mx in (5, 6) and "last" not in blob:
                    val = first5 or last4
                else:
                    val = last4
                if _put(name, val):
                    filled = True
            elif any(k in blob for k in ("phone", "mobile", "tel")) and phone4:
                val = phone4 if mx in (0, 4) else _digits(f.get("phone") or "")
                if _put(name, val):
                    filled = True

        if not filled and last4:
            for n in ("ssnEC", "ssnFC", "ssnV1", "ssn"):
                if _put(n, last4 if n != "ssn" else (full or last4)):
                    filled = True
                    break
        # Last resort: any visible short text box on the verify screen.
        if not filled and last4:
            try:
                typed = page.evaluate(
                    """(v) => {
                        const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                        const el = Array.from(document.querySelectorAll('input,textarea'))
                          .find(e => vis(e) && e.type !== 'hidden' && e.type !== 'checkbox'
                                 && e.type !== 'radio' && (e.maxLength === 4 || e.maxLength <= 0
                                 || /ssn|social|digit/i.test((e.name||'')+(e.placeholder||'')+(e.id||''))));
                        if (!el) return false;
                        const last = el.value;
                        el.focus();
                        el.value = '';
                        if (el._valueTracker) el._valueTracker.setValue(last === '' ? ' ' : last);
                        const proto = HTMLInputElement.prototype;
                        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) desc.set.call(el, v); else el.value = v;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
                        if (propsKey && el[propsKey] && el[propsKey].onChange) {
                          el[propsKey].onChange({ target: el, currentTarget: el, preventDefault(){}, stopPropagation(){} });
                        }
                        return true;
                    }""",
                    last4,
                )
                if typed:
                    filled = True
            except Exception:
                pass
        return filled

    def _handle_duplicate_identity(self, page: Page, f: dict, row_number: int, step: str = "") -> str:
        """Existing email/SSN/phone — verify last-4 and KEEP filling to the end.

        Never treat a duplicate as done/skipped. Prefer the returning-user
        last-4 SSN path so the funnel continues to finish + post-CTA pages.
        Only click "Start a new form" when last-4 cannot be filled.

        Returns ``verified``, ``new_form``, or ``""``.
        """
        try:
            step_l = (step or "").lower()
            # ssnEC is a normal wizard step for new leads — only treat it as a
            # duplicate when the welcome-back / last-4 copy is on screen.
            on_verify_step = step_l in ("ssnfc", "welcomeback", "ssnv1", "verify", "returning")
            on_dup_copy = self._is_duplicate_identity_screen(page)
            if step_l == "ssnec" and on_dup_copy:
                on_verify_step = True
            if not (on_verify_step or on_dup_copy):
                return ""
            log.info("form.duplicate_identity", step=step, row=row_number)
            print(f"[DUP] existing lead on step={step!r} — filling last-4 and continuing to end", flush=True)

            # 1) Prefer verify last-4 and continue the rest of the form.
            if self._fill_duplicate_verify_fields(page, f):
                log.info("form.duplicate_verified", row=row_number)
                print("[DUP] last-4 SSN filled — continuing wizard / CTAs like a normal lead", flush=True)
                return "verified"

            # 2) Fallback: start a fresh form, then the main loop fills every step.
            if getattr(self, "_dup_reset_done", 0) < 2 and self._click_start_new_form(page):
                self._dup_reset_done = getattr(self, "_dup_reset_done", 0) + 1
                deadline = time.time() + 8
                while time.time() < deadline:
                    if not self._is_duplicate_identity_screen(page):
                        break
                    time.sleep(0.4)
                print("[DUP] started new form — will fill every step to the last CTA", flush=True)
                return "new_form"
            return ""
        except Exception as exc:
            if self._is_nav_error(exc):
                log.info("form.duplicate_navigated", error=str(exc)[:100], row=row_number)
                return "verified"
            log.warning("form.duplicate_error", error=str(exc)[:120], row=row_number)
            return ""

    def _fill_email_maybe_dup(self, page: Page, f: dict) -> bool:
        """Fill email. If a returning-user screen appears, verify last-4 and continue."""
        fn = getattr(self, "_fill_step_fields", None)
        ok = bool(fn(page, "email", f)) if callable(fn) else False
        time.sleep(0.9)
        try:
            if self._is_duplicate_identity_screen(page):
                print("[DUP] after email — verifying last-4 SSN (will not skip)", flush=True)
                if self._fill_duplicate_verify_fields(page, f):
                    return True
        except Exception as exc:
            if not self._is_nav_error(exc):
                log.warning("form.email_dup_check", error=str(exc)[:100])
        return bool(ok)

    def _key_delay(self) -> float:
        import random
        lo = float(self._delays.get("min_typing_delay", 0.04))
        hi = float(self._delays.get("max_typing_delay", 0.12))
        return random.uniform(lo, hi) * 1000

    def _action_pause(self) -> None:
        import random
        lo = float(self._delays.get("min_action_delay", 0.5))
        hi = float(self._delays.get("max_action_delay", 2.0))
        time.sleep(random.uniform(lo, hi))

    def _pause_range(self, key: str, lo: float, hi: float) -> None:
        """Sleep a random time in a [lo, hi] window read from config, so the
        rhythm is tunable without code changes."""
        import random
        rng = self._delays.get(key)
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo, hi = float(rng[0]), float(rng[1])
        time.sleep(random.uniform(lo, hi))

    def _read_pause(self) -> None:
        """Human beat after a fresh step renders — as if reading the question
        before answering.  Keeps multi-step forms from feeling machine-paced."""
        self._pause_range("read_pause", 0.5, 1.2)

    def _field_pause(self) -> None:
        """Human beat between fields within one step (name -> surname -> DOB),
        which is what otherwise reads as a bot filling everything at once."""
        self._pause_range("field_pause", 0.35, 0.8)

    def _check_stop(self, stop_event) -> None:
        if stop_event is not None and stop_event.is_set():
            raise FormFillerError("Stopped by user", error_type="stopped")

    def _live(self, page: Page) -> None:
        """Refresh the UI's live-preview frame."""
        try:
            page.screenshot(path=str(self._ss_dir / "live_view.png"))
        except Exception:
            pass

    # ---------------------------------------------------------------- parsing

    def _parse_fields(self, row: dict) -> dict:
        # Case/space-insensitive header map — sheet tabs are sometimes re-cased
        # ('Zip Code' vs 'ZIP Code', 'Date Of Birth (Dob)', 'Ssn Full'), which
        # would otherwise make exact-key lookups miss and report missing data.
        _norm = {}
        for _k, _v in row.items():
            _nk = re.sub(r"\s+", " ", str(_k)).strip().lower()
            if _nk not in _norm or str(_v or "").strip():
                _norm[_nk] = _v

        def g(*keys: str) -> str:
            for k in keys:
                nk = re.sub(r"\s+", " ", str(k)).strip().lower()
                v = str(_norm.get(nk) or "").strip()
                if v:
                    return v
            return ""

        phone = _digits(g("Phone Number", "Phone"))
        employer_phone = _digits(g("Employer Work Phone", "Work Phone")) or phone

        full_ssn_raw = g("SSN Full", "SSN")
        full_ssn = _ssn_digits(full_ssn_raw) or _sheet_digits(full_ssn_raw)
        last4 = _sheet_digits(g("SSN Last 4"))
        if len(full_ssn) == 9:
            last_ssn = full_ssn[-4:]
        else:
            last_ssn = last4[-4:] if last4 else ""
            if len(full_ssn) != 9:
                full_ssn = last4

        zip_raw = _digits(g("ZIP Code", "Zip", "Zip_Code"))
        # ABA routing numbers are 9 digits; a spreadsheet that stored the value
        # as a number drops the leading zero (067014822 -> 67014822), which then
        # fails the checksum. Restore it before validating.
        routing = _digits(g("ABA Routing Number", "routingNumber", "Routing Number"))
        if 0 < len(routing) < 9:
            routing = routing.zfill(9)

        loan_raw = re.sub(r"[,$\s]", "", g("Requested Loan Amount ($)", "Loan_Amount"))
        try:
            loan_amount = int(float(loan_raw))
        except (ValueError, TypeError):
            loan_amount = 5000
        loan_amount = max(100, min(35000, loan_amount))

        income_raw = re.sub(r"[,$\s]", "", g("Monthly Net Income ($)", "Monthly_Income"))
        try:
            income = int(float(income_raw))
        except (ValueError, TypeError):
            income = 3000
        monthly_income = max(1500, min(20000, income if income > 0 else 3000))

        return {
            "first_name":     g("First Name", "First_Name"),
            "last_name":      g("Last Name", "Last_Name"),
            "email":          g("Email Address", "Email"),
            "phone":          self._fmt_phone(phone),
            "employer_phone": self._fmt_phone(employer_phone),
            "dob":            self._normalize_dob(g("Date of Birth (DOB)", "DOB", "dob")),
            "ssn":            full_ssn,
            "last_ssn":       last_ssn,
            "zip":            zip_raw.zfill(5) if zip_raw else "",
            "street_address": g("Street Address", "Address"),
            "city":           g("City"),
            "state":          self._normalize_state(g("State")),
            "loan_amount":    loan_amount,
            "monthly_income": monthly_income,
            "income_bracket": self._bracket(income, self._NETIM_BRACKETS, self._NETIM_TOP),
            "debt_bracket":   self._debt_bracket(g("Credit Card Debt", "Debt Amount")),
            "address_months": self._tenure(g("Years at Address", "Months at Address")),
            "employer_months": self._tenure(g("Years at Employer", "Months at Employer")),
            "bank_months":    self._tenure(g("Years at Bank", "Months at Bank")),
            "is_homeowner":   self._yes_no(g("Homeowner", "Is Homeowner"), default="0"),
            "is_military":    self._yes_no(g("Military", "Active Military"), default="0"),
            "is_direct_deposit": self._yes_no(g("Direct Deposit"), default="1"),
            "income_source":  self._income_source(g("Income Source", "Primary Income Source")),
            "pay_freq":       self._pay_freq(g("Pay Frequency", "Pay_Frequency")),
            "employer_name":  g("Employer Name", "Employer_Name") or "Employer",
            "dl_number":      g("Driver License / ID Number", "driversLicenseNumber"),
            "dl_state":       self._normalize_state(
                                  g("Driver License State") or g("State")),
            "account_type":   "2" if g("Account Type", "bankAccountType").lower().startswith("sav") else "1",
            "credit_score":   self._credit_score(g("Credit Score Rating", "Credit_Score")),
            "loan_reason":    self._loan_reason(g("Loan Purpose", "Loan_Purpose")),
            "routing_number": routing,
            "account_number": _account_digits(g("Account Number", "accountNumber")),
            "bank_name":      g("Bank Name", "bankName"),
            "ssn_raw":        full_ssn_raw,
        }

    def _validate_required_fields(self, f: dict) -> None:
        required = [
            "first_name", "last_name", "email", "phone", "dob",
            "zip", "street_address", "city", "state",
            "ssn", "routing_number", "account_number",
        ]
        missing = [k for k in required if not f.get(k)]

        # Fail fast on rules the form enforces client-side — otherwise the lead
        # burns a full browser session only to stall on a step it can never pass.
        if f["routing_number"] and not _aba_checksum_ok(f["routing_number"]):
            missing.append("routing_number(failed ABA checksum)")
        ssn_err = _ssn_invalid_reason(f.get("ssn") or f.get("ssn_raw") or "")
        if f.get("ssn") and ssn_err:
            missing.append(f"ssn({ssn_err})")
        acct = f["account_number"]
        acct_err = _account_invalid_reason(acct, f.get("routing_number", ""))
        if acct and acct_err:
            missing.append(f"account_number({acct_err})")
        if f["dob"] and not re.match(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}$", f["dob"]):
            missing.append("dob(must be MM/DD/YYYY)")
        elif f["dob"]:
            age = self._age(f["dob"])
            if age is not None and not (18 <= age <= 120):
                missing.append(f"dob(age {age} outside 18-120)")
        if f["phone"] and not re.match(r"^\([2-9]\d{2}\) \d{3}-\d{4}$", f["phone"]):
            missing.append("phone(invalid US number)")
        if f["zip"] and len(f["zip"]) != 5:
            missing.append("zip(must be 5 digits)")

        if missing:
            raise FormFillerError(
                f"Missing or invalid fields: {missing}", error_type="missing_data"
            )

    # ------------------------------------------------------------- normalising

    def _fmt_phone(self, digits: str) -> str:
        """Render as (XXX) XXX-XXXX — the pattern the form's regex accepts."""
        d = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        if len(d) != 10 or d[0] not in "23456789":
            return ""
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"

    def _normalize_dob(self, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%m/%d/%Y")
            except ValueError:
                pass
        return raw

    def _age(self, dob: str) -> int | None:
        try:
            d = datetime.strptime(dob, "%m/%d/%Y")
        except ValueError:
            return None
        today = datetime.now()
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))

    def _normalize_state(self, raw: str) -> str:
        raw = (raw or "").strip()
        if len(raw) == 2:
            return raw.upper()
        return self._STATE_CODES.get(raw.lower(), raw.upper()[:2])

    def _bracket(self, value: int, brackets: list[tuple[int, str]], top: str) -> str:
        for upper, option in brackets:
            if value < upper:
                return option
        return top

    def _debt_bracket(self, raw: str) -> str:
        digits = re.sub(r"[,$\s]", "", raw or "")
        try:
            amount = int(float(digits))
        except (ValueError, TypeError):
            return "0"
        return self._bracket(amount, self._DEBT_BRACKETS, self._DEBT_TOP)

    def _tenure(self, raw: str) -> str:
        """Sheet may hold years ("3") or months ("36"); both map to the radios."""
        raw = (raw or "").strip().lower()
        if not raw:
            return self._TENURE_TOP
        nums = re.findall(r"\d+", raw)
        if not nums:
            return self._TENURE_TOP
        n = int(nums[0])
        months = n if ("month" in raw or n > 12) else n * 12
        for upper, option in self._TENURE_STEPS:
            if months <= upper:
                return option
        return self._TENURE_TOP

    def _yes_no(self, raw: str, default: str = "0") -> str:
        raw = (raw or "").strip().lower()
        if not raw:
            return default
        return "1" if raw in {"yes", "y", "true", "1", "own", "owner"} else "0"

    def _income_source(self, raw: str) -> str:
        raw = (raw or "").strip().lower()
        if any(k in raw for k in ("benefit", "unemploy", "disab", "social", "pension", "retire")):
            return "2"
        return "1"

    def _pay_freq(self, raw: str) -> str:
        raw = (raw or "").strip().lower()
        if "week" in raw and ("bi" in raw or "every 2" in raw or "every two" in raw):
            return "2"
        if "semi" in raw or "twice" in raw:
            return "4"
        if "week" in raw:
            return "1"
        if "month" in raw:
            return "3"
        return "2"

    def _credit_score(self, raw: str) -> str:
        raw = (raw or "").strip().lower()
        if not raw:
            return "1"
        words = {"excellent": "2", "great": "2", "good": "3", "fair": "4", "poor": "5"}
        for word, value in words.items():
            if raw.startswith(word):
                return value
        try:
            score = int(re.sub(r"\D", "", raw)[:3])
        except (ValueError, TypeError):
            return "1"
        if score >= 700:
            return "2"
        if score >= 600:
            return "3"
        if score >= 500:
            return "4"
        return "5"

    def _loan_reason(self, raw: str) -> str:
        raw = (raw or "").strip().lower()
        if "card" in raw or "credit card" in raw:
            return "14"
        if "debt" in raw or "consol" in raw:
            return "1"
        return "13"

    # ---------------------------------------------------------------- utilities

    def _close_browser(self, browser: Browser) -> None:
        """Shut the browser down without ever blocking the engine thread.

        A Chromium renderer that has crashed never acknowledges close(), so the
        call would hang forever and the Stop button could not reach the thread.
        Playwright's sync API is greenlet-based and thread-affine, so closing on
        a watchdog thread is not an option either — it corrupts the event loop.
        Instead: skip close() entirely on a crashed target and let the
        sync_playwright() context exit reap the driver and its children.
        """
        if self._crashed:
            log.warning("form.skip_close", msg="renderer crashed; leaving teardown to the driver")
            return
        try:
            browser.close()
        except Exception:
            pass

    # Funnel domains — after Submit we must leave these before clicking offer CTAs.
    _SOURCE_HOSTS = (
        "togetfastcash.com",
        "rapidpaydayfund.com",
        "easycashday.com",
        "paydayed.com",
        "mylendingwallet.com",
    )

    def _newest_page(self, page: Page) -> Page:
        try:
            pages = [p for p in page.context.pages if not p.is_closed()]
            if pages:
                return pages[-1]
        except Exception:
            pass
        return page

    _LEGAL_URL = re.compile(
        r"personal-loan-notice|privacy|terms-of|terms_of|unsubscribe|"
        r"advertiser|disclosure|/legal|/notice",
        re.I,
    )

    def _is_legal_page(self, page: Page) -> bool:
        try:
            url = (page.url or "").lower()
        except Exception:
            return False
        if self._LEGAL_URL.search(url):
            return True
        try:
            blob = page.evaluate(
                """() => ((document.querySelector('h1,h2,title')||{}).innerText
                  || document.title || '').toLowerCase()"""
            ) or ""
        except Exception:
            blob = ""
        return bool(re.search(r"personal loan notice|not a lender|terms of service", blob, re.I))

    def _form_page(self, page: Page) -> Page:
        """Stay on a page that can be filled — never a legal/notice tab."""
        try:
            pages = [p for p in page.context.pages if not p.is_closed()]
        except Exception:
            return page
        usable: list[Page] = []
        for p in pages:
            if self._is_source_site(p):
                continue
            if self._is_legal_page(p):
                try:
                    if len(pages) > 1:
                        p.close()
                except Exception:
                    pass
                continue
            usable.append(p)
        if not usable:
            return page
        # Finish SSN / VIEW OFFERS before switching to another tab.
        for p in usable:
            if self._page_needs_view_offers(p):
                return p
        best, best_n = usable[-1], -1
        for p in usable:
            try:
                n = p.evaluate(
                    """() => document.querySelectorAll(
                      'input:not([type=hidden]),select,textarea,[role=radio],[role=option]'
                    ).length"""
                ) or 0
            except Exception:
                n = 0
            if n >= best_n:
                best, best_n = p, n
        return best

    def _page_is_done(self, page: Page) -> bool:
        """Terminal page of an extra form. Only meaningful once the extra form
        has been worked on — the main funnel also shows a congratulations page
        while it redirects, and that one must be followed, not treated as done."""
        try:
            url = (page.url or "").lower()
        except Exception:
            url = ""
        if re.search(r"/congrats|/thank", url):
            return True
        try:
            return bool(page.evaluate(self._JS_SECONDARY_DONE))
        except Exception:
            return False

    def _wait_for_congrats(self, page: Page, secs: float) -> Page | None:
        """Wait for the extra form's congratulations page after VIEW OFFERS."""
        until = time.time() + secs
        while time.time() < until:
            try:
                pages = [p for p in page.context.pages if not p.is_closed()]
            except Exception:
                pages = [page]
            for p in pages:
                if self._page_is_done(p):
                    return p
            try:
                page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            time.sleep(0.5)
        return None

    def _page_needs_view_offers(self, page: Page) -> bool:
        try:
            url = (page.url or "").lower()
        except Exception:
            url = ""
        if re.search(r"/ssn\b", url):
            return True
        try:
            return bool(page.evaluate(
                """() => {
                  const h = ((document.body && document.body.innerText) || '')
                    .toLowerCase().slice(0, 1600);
                  if (!/social security number|what is your ssn/.test(h)) return false;
                  return Array.from(document.querySelectorAll(
                    'button,input,[role=button],a,[class*="btn"]'
                  )).some(e => /view\\s*(my\\s*)?offers/i.test(
                    ((e.innerText || e.value || e.getAttribute('aria-label') || '') + '')
                  ));
                }"""
            ))
        except Exception:
            return False

    def _page_host(self, page: Page) -> str:
        try:
            url = (page.url or "").lower()
        except Exception:
            return ""
        m = re.search(r"https?://([^/]+)", url)
        return (m.group(1) if m else "").removeprefix("www.")

    def _is_source_site(self, page: Page) -> bool:
        host = self._page_host(page)
        if not host:
            return True
        for src in self._SOURCE_HOSTS:
            if host == src or host.endswith("." + src):
                return True
        try:
            target = (self._target.get("url") or self.default_url or "").lower()
        except Exception:
            target = (self.default_url or "").lower()
        tm = re.search(r"https?://([^/]+)", target)
        th = (tm.group(1) if tm else "").removeprefix("www.")
        return bool(th and (host == th or host.endswith("." + th)))

    # Click the first congratulations / offer-list card (my411 OPTION 01, etc.).
    _JS_CLICK_OFFER_CTA = r"""(dryRun) => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 100 && r.height >= 40
            && st.visibility !== 'hidden' && st.display !== 'none'
            && st.pointerEvents !== 'none'
            && r.bottom > 0 && r.top < (innerHeight + 400);
        };
        const text = e => ((e.innerText || e.value || '') + '').replace(/\s+/g, ' ').trim();
        const skip = /(privacy|terms &|terms of|disclosure|log ?in|sign ?in|cookie|advertiser|unsubscribe)/i;

        const scoreAnchor = (a) => {
          const t = text(a);
          const href = ((a.href || a.getAttribute('href') || '') + '').toLowerCase();
          if (!t || skip.test(t)) return 0;
          let s = 0;
          if (/option\s*0?\d/i.test(t)) s += 60;
          if (/personal loan|cash loan|installment/i.test(t)) s += 35;
          if (/secure site/i.test(t)) s += 10;
          if (/borrow up to|request \$\d|urgent needs|fit any need/i.test(t)) s += 15;
          if (/click\.php|out\.php|go\.php|\/rd\/|clk|track|redirect/i.test(href)) s += 30;
          const r = a.getBoundingClientRect();
          if (r.height >= 80 && r.width >= 180) s += 15;
          if (t.length > 420) s -= 25;
          if (/select an option|complete the form|accept the terms/i.test(t) && t.length < 80) s = 0;
          return s;
        };

        const anchors = Array.from(document.querySelectorAll('a[href]')).filter(vis);
        let best = null, bestScore = 0;
        for (const a of anchors) {
          const sc = scoreAnchor(a);
          if (sc > bestScore) { best = a; bestScore = sc; }
        }
        if (best && bestScore >= 25) {
          const label = text(best).slice(0, 80) || best.href.slice(0, 80);
          if (!dryRun) { best.scrollIntoView({block:'center', inline:'nearest'}); best.click(); }
          return label;
        }

        const boxes = Array.from(document.querySelectorAll(
          'div,section,article,li,[role=link],[role=button],[onclick],[data-href],[data-url]'
        )).filter(vis);
        const box = boxes.find(el => {
          const t = text(el);
          if (t.length < 10 || t.length > 320) return false;
          return /option\s*0?\d/i.test(t) && /loan|cash/i.test(t);
        });
        if (box) {
          const target = box.closest('a[href]') || box.querySelector('a[href]') || box;
          const label = text(box).slice(0, 80);
          if (!dryRun) { target.scrollIntoView({block:'center', inline:'nearest'}); target.click(); }
          return label;
        }

        const go = /^(continue|next|apply now|get started|see offer|view offer|get cash|get my|select|start here|claim offer)/i;
        const no = /(back|cancel|decline|privacy|terms|submit loan|loan request|^next$)/i;
        const btn = Array.from(document.querySelectorAll(
          'button,input[type=submit],input[type=button],[role=button],a.btn,a.button'
        )).filter(vis).find(e => {
          const s = text(e);
          return s && s.length < 40 && go.test(s) && !no.test(s);
        });
        if (btn) {
          const label = text(btn).slice(0, 40);
          if (!dryRun) btn.click();
          return label;
        }
        return '';
    }"""

    _JS_MODAL_CTA = r"""() => {
        const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
        const text = e => ((e.innerText || e.value || '')+'').replace(/\s+/g,' ').trim();
        const go = /see (my )?(offers?|results|options)|view (my )?(offers?|results)|continue|next|get (started|offers?|results)|show (me )?(offers?|results)|compare|find (my )?offers?/i;
        const no = /back|cancel|close|x$|privacy|terms|disclosure/i;
        const roots = [
          document.querySelector('.final-processing-modal, .f-modal, .shared-modal-content, .f-modal-dialog, [class*=congrat]'),
          document.body
        ].filter(Boolean);
        for (const root of roots) {
          const btns = Array.from(root.querySelectorAll('button,a,[role=button],input[type=button],input[type=submit]')).filter(vis);
          const b = btns.find(e => {
            const s = text(e);
            return s && s.length < 40 && go.test(s) && !no.test(s);
          });
          if (b) { b.click(); return text(b).slice(0, 40); }
        }
        return '';
    }"""

    def _offsite_page(self, page: Page) -> Page | None:
        try:
            for p in page.context.pages:
                if p.is_closed():
                    continue
                if not self._is_source_site(p):
                    return p
        except Exception:
            pass
        return None

    def _click_post_congrats_cta(self, page: Page, fields: dict, row_number: int, stop_event) -> str:
        """After congratulations / processing, click a CTA on the redirected options page,
        then keep filling / clicking through any follow-on form until the last CTA."""
        deadline = time.time() + 90
        cur = page
        while time.time() < deadline:
            self._check_stop(stop_event)
            off = self._offsite_page(page)
            if off is not None:
                cur = off
                break
            try:
                hit = page.evaluate(self._JS_MODAL_CTA) or ""
                if hit:
                    log.info("form.modal_cta", row=row_number, cta=hit)
                    print(f"\n*** Congrats modal CTA — {hit} ***\n", flush=True)
            except Exception:
                pass
            time.sleep(1.2)
        else:
            cur = self._offsite_page(page) or self._newest_page(page)

        if self._is_source_site(cur):
            log.info("form.redirect_cta", row=row_number, state="still-on-source",
                     url=(cur.url or "")[:80])
            return ""

        try:
            cur.bring_to_front()
        except Exception:
            pass
        for state in ("domcontentloaded", "load"):
            try:
                cur.wait_for_load_state(state, timeout=15000)
            except Exception:
                pass
        time.sleep(1.8)
        self._screenshot(cur, row_number, "offer_list")
        log.info("form.redirect_cta", row=row_number, state="landed",
                 url=(cur.url or "")[:90])

        label = ""
        frame = None
        for fr in list(cur.frames):
            try:
                if fr.is_detached():
                    continue
                found = fr.evaluate(self._JS_CLICK_OFFER_CTA, True) or ""
            except Exception:
                found = ""
            if found:
                label, frame = found, fr
                break

        if not frame or not label:
            log.info("form.redirect_cta", row=row_number, state="no-list-cta",
                     url=(cur.url or "")[:80])
            trail = self._drive_secondary_funnel(cur, fields, row_number, stop_event)
            return trail or f"offer page no CTA ({(cur.url or '')[:60]})"

        log.info("form.redirect_cta", row=row_number, state="click", cta=label[:80])
        print(f"\n*** Offer page CTA — clicking: {label[:80]} ***\n", flush=True)
        dest = cur
        clicked = False
        try:
            with cur.context.expect_page(timeout=8000) as pinfo:
                frame.evaluate(self._JS_CLICK_OFFER_CTA, False)
                clicked = True
            dest = pinfo.value
        except Exception:
            if not clicked:
                try:
                    frame.evaluate(self._JS_CLICK_OFFER_CTA, False)
                except Exception:
                    pass
            dest = self._newest_page(page)

        try:
            dest.bring_to_front()
        except Exception:
            pass
        for state in ("domcontentloaded", "load"):
            try:
                dest.wait_for_load_state(state, timeout=20000)
            except Exception:
                pass
        time.sleep(2.0)
        self._screenshot(dest, row_number, "offer_cta_clicked")
        log.info("form.redirect_cta", row=row_number, state="after-click",
                 url=(dest.url or "")[:90])
        trail = self._drive_secondary_funnel(dest, fields, row_number, stop_event)
        note = f"clicked offer CTA ({(dest.url or '')[:70]})"
        return f"{note} → {trail}" if trail else note

    def _valid_mmddyyyy(self, raw: str) -> str | None:
        """Return MM/DD/YYYY if raw is a real adult DOB, else None."""
        s = (raw or "").strip()
        if not s:
            return None
        parsed = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%y"):
            try:
                parsed = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            dig = re.sub(r"\D", "", s)
            if len(dig) == 8:
                try:
                    parsed = datetime.strptime(dig, "%m%d%Y")
                except ValueError:
                    parsed = None
        if parsed is None:
            return None
        age = datetime.now().year - parsed.year - (
            (datetime.now().month, datetime.now().day) < (parsed.month, parsed.day)
        )
        if age < 18 or age > 90 or not (1 <= parsed.month <= 12):
            return None
        return parsed.strftime("%m/%d/%Y")

    def _secondary_vals(self, f: dict) -> dict:
        """Sheet value when present and valid; otherwise a valid dummy.

        Extra funnels (AmOne, MarketLoans, LendingForBadCredit, …) must never
        get garbage like 31/24/9722 — that was a phone dumped into a DOB mask.
        """
        n = random.randint(2000, 8999)
        d_first = random.choice(["James", "Ryan", "Emily", "Laura", "Kevin", "Megan", "Brian", "Olivia"])
        d_last = random.choice(["Parker", "Brooks", "Hayes", "Cole", "Reed", "Walsh", "Bennett", "Foster"])
        area = random.choice(["602", "214", "404", "503", "216", "615"])
        exch = str(random.randint(200, 989))
        line = f"{random.randint(1000, 9999)}"
        d_phone = f"{area}{exch}{line}"
        d_year, d_month, d_day = random.randint(1978, 1996), random.randint(1, 12), random.randint(1, 28)
        zips = {
            "90210": ("Beverly Hills", "CA"),
            "85001": ("Phoenix", "AZ"),
            "75201": ("Dallas", "TX"),
            "30301": ("Atlanta", "GA"),
            "60601": ("Chicago", "IL"),
            "97201": ("Portland", "OR"),
        }
        d_zip = random.choice(list(zips))
        d_city, d_state = zips[d_zip]

        def _sheet(*keys: str, dummy: str = "") -> str:
            for k in keys:
                v = f.get(k)
                if v not in (None, ""):
                    s = str(v).strip()
                    if s:
                        return s
            return dummy

        phone_digits = re.sub(r"\D", "", _sheet("phone"))[-10:]
        phone = phone_digits if len(phone_digits) == 10 else d_phone
        dob = self._valid_mmddyyyy(_sheet("dob")) or f"{d_month:02d}/{d_day:02d}/{d_year}"
        parts = dob.split("/")
        income_raw = re.sub(r"\D", "", _sheet("monthly_income", dummy="4500")) or "4500"
        try:
            income_n = max(1500, min(20000, int(income_raw)))
        except ValueError:
            income_n = 4500
        ssn_digits = re.sub(r"\D", "", _sheet("ssn"))
        ssn = ssn_digits if len(ssn_digits) == 9 else f"{random.randint(400, 650)}{random.randint(10, 80):02d}{random.randint(1000, 8999)}"
        routing = re.sub(r"\D", "", _sheet("routing_number", dummy="021000021")).zfill(9)[:9]
        account = re.sub(r"\D", "", _sheet("account_number")) or str(random.randint(1000000000, 8999999999))
        loan = _sheet("loan_amount", dummy="5000")
        try:
            loan_n = max(500, min(35000, int(re.sub(r"\D", "", str(loan)) or "5000")))
        except ValueError:
            loan_n = 5000
        reason = str(f.get("loan_reason") or "")
        if reason == "14":
            purpose = ["pay off credit cards", "credit card", "debt consolidation"]
        elif reason == "1":
            purpose = ["debt consolidation", "debt", "emergency"]
        elif reason == "13":
            purpose = ["emergency", "personal", "other"]
        else:
            purpose = ["debt consolidation", "credit card consolidation", "home improvement"]
        pf = str(f.get("pay_freq") or "2")
        if pf == "1":
            purpose = ["weekly"] + purpose
        elif pf == "3":
            purpose = ["monthly"] + purpose
        elif pf == "4":
            purpose = ["twice a month", "semi-monthly", "semi monthly"] + purpose
        else:
            purpose = ["every other week", "bi-weekly", "biweekly", "twice a month"] + purpose
        credit = str(f.get("credit_score") or "3")
        if credit == "2":
            purpose = ["excellent"] + purpose
        elif credit == "4":
            purpose = ["fair"] + purpose
        elif credit == "5":
            purpose = ["poor"] + purpose
        else:
            purpose = ["good"] + purpose
        dd = "no" if str(f.get("is_direct_deposit") or "1") == "0" else "yes"
        purpose = [dd] + purpose
        return {
            "loan_amount": str(loan_n),
            "first_name": _sheet("first_name", dummy=d_first),
            "last_name": _sheet("last_name", dummy=d_last),
            "email": _sheet("email", dummy=f"{d_first.lower()}.{d_last.lower()}{n}@gmail.com"),
            "phone": phone,
            "phone_fmt": _sheet("phone", dummy=f"({area}) {exch}-{line}"),
            "zip": _sheet("zip", dummy=d_zip)[:5].zfill(5) if _sheet("zip", dummy=d_zip) else d_zip,
            "city": _sheet("city", dummy=d_city),
            "state": _sheet("state", dummy=d_state),
            "address": _sheet("street_address", dummy=f"{random.randint(100, 999)} Oak Street"),
            "dob": dob,
            "dob_m": parts[0].lstrip("0") if parts else str(d_month),
            "dob_d": parts[1].lstrip("0") if len(parts) > 1 else str(d_day),
            "dob_y": parts[2] if len(parts) > 2 else str(d_year),
            "ssn": ssn,
            "income": str(income_n),
            "annual_income": str(max(18000, min(180000, income_n * 12))),
            "direct_deposit": "no" if str(f.get("is_direct_deposit") or "1") == "0" else "yes",
            "apt": "",
            "employer": _sheet("employer_name", dummy=random.choice(
                ["Summit Retail LLC", "Northwind Goods", "Harbor Supply Co"])),
            "routing": routing,
            "account": account,
            "bank_name": _sheet("bank_name", dummy="Chase"),
            "purpose": purpose,
        }

    _JS_FILL_SECONDARY = r"""(V) => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width > 8 && r.height > 8
            && st.visibility !== 'hidden' && st.display !== 'none';
        };
        const setV = (el, val) => {
          if (val === undefined || val === null) return false;
          val = String(val);
          const proto = el.tagName === 'TEXTAREA'
            ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const d = Object.getOwnPropertyDescriptor(proto, 'value');
          if (d && d.set) d.set.call(el, val);
          else el.value = val;
          ['input','change','keyup','blur'].forEach(ev =>
            el.dispatchEvent(new Event(ev, {bubbles:true})));
          return true;
        };
        const key = e => {
          let s = (e.name||'')+' '+(e.id||'')+' '+(e.placeholder||'')+' '
            +(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('autocomplete')||'');
          if (e.id) {
            const lf = document.querySelector('label[for="'+CSS.escape(e.id)+'"]');
            if (lf) s += ' '+(lf.innerText||'');
          }
          const wrap = e.closest('label');
          if (wrap) s += ' '+(wrap.innerText||'');
          const prev = e.previousElementSibling;
          if (prev && prev.tagName === 'LABEL') s += ' '+(prev.innerText||'');
          const parent = e.parentElement;
          if (parent) {
            const pl = parent.querySelector(':scope > label');
            if (pl) s += ' '+(pl.innerText||'');
          }
          return s.toLowerCase();
        };
        const heading = ((document.querySelector('h1,h2,h3,.title,.headline,legend')||{}).innerText||'')
          + ' ' + (location.href||'') + ' ' + (location.pathname||'');
        const pageIsDob = /\/dob\b|date of birth|birth.?date|what is your date of birth|birthday/i.test(heading);
        const pageIsAnnual = /annual (pre-?tax )?income|pre-?tax income|yearly income|what.?s your annual/i.test(heading);
        const pageIsIncome = /monthly[-_\/ ]?income|\/income\b|salary|gross (monthly|income)|net (monthly|income)|how much do you (make|earn)|what is your (monthly )?income/i.test(heading)
          && !pageIsDob && !pageIsAnnual;
        const pageIsAmount = /how much.*(borrow|need)|loan[-_\/ ]?amount|requested amount|\/loan-amount/i.test(heading)
          && !pageIsIncome && !pageIsDob && !pageIsAnnual;
        const incomeBad = (raw) => {
          const d = String(raw||'').replace(/\D/g,'');
          if (!d) return true;
          const n = parseInt(d, 10);
          return d.length >= 8 || n > 20000 || n < 500;
        };
        const annualBad = (raw) => {
          const d = String(raw||'').replace(/\D/g,'');
          if (!d) return true;
          const n = parseInt(d, 10);
          return d.length >= 8 || n < 12000 || n > 250000;
        };
        const dobBad = (raw) => {
          const d = String(raw||'').replace(/\D/g,'');
          if (d.length !== 8) return true;
          const mm = parseInt(d.slice(0,2),10), dd = parseInt(d.slice(2,4),10), yy = parseInt(d.slice(4),10);
          return mm < 1 || mm > 12 || dd < 1 || dd > 31 || yy < 1940 || yy > 2008;
        };
        let n = 0;
        document.querySelectorAll('input,select,textarea').forEach(e => {
          if (!vis(e) || e.disabled || e.readOnly) return;
          const typ = (e.type||'').toLowerCase();
          if (typ === 'hidden' || typ === 'radio' || typ === 'checkbox' || typ === 'submit' || typ === 'button') return;
          const k = key(e);
          const fieldIsDob = /dob|birth|birthday/.test(k) || pageIsDob || typ === 'date';
          const fieldIsAnnual = (/annual|pre-?tax|yearly/.test(k) || pageIsAnnual) && !fieldIsDob;
          const fieldIsIncome = (/income|salary|gross|net.?pay|monthly.?pay/.test(k) || pageIsIncome)
            && !fieldIsDob && !fieldIsAnnual;
          if (e.tagName === 'SELECT') {
            const want = /state/.test(k) ? V.state
              : /month|dob.*m|birth.*m/.test(k) ? V.dob_m
              : /day|dob.*d|birth.*d/.test(k) ? V.dob_d
              : /year|dob.*y|birth.*y/.test(k) ? V.dob_y
              : '';
            if (!want) return;
            const o = Array.from(e.options).find(o =>
              o.value === want || o.text.trim() === want
              || o.value === want.padStart(2,'0') || o.text.trim() === want.padStart(2,'0')
              || new RegExp('^'+want+'$','i').test(o.text.trim())
              || new RegExp('\\b'+want+'\\b','i').test(o.text));
            if (o && e.value !== o.value) {
              e.value = o.value;
              e.dispatchEvent(new Event('change', {bubbles:true}));
              n++;
            }
            return;
          }
          const cur = (e.value||'').replace(/[$,\s]/g,'');
          const isEmpty = !cur || cur === '0' || cur === '00' || cur === '100';
          if (fieldIsDob) {
            if (dobBad(cur) && setV(e, V.dob)) n++;
            return;
          }
          if (/apt|suite|unit|apartment|addr2|address.?2|address.?line.?2|line.?2|addl|additional.?addr/.test(k)) {
            if ((e.value || '').trim() && setV(e, V.apt || '')) n++;
            return;
          }
          if (fieldIsAnnual) {
            if (annualBad(cur) && setV(e, V.annual_income || String((parseInt(V.income||'4500',10)||4500)*12))) n++;
            return;
          }
          if (fieldIsIncome) {
            if (incomeBad(cur) && setV(e, V.income)) n++;
            return;
          }
          if (typ === 'range' && /amount|loan|borrow/.test(k + ' ' + heading) && !pageIsIncome && !pageIsDob) {
            if (setV(e, V.loan_amount)) n++;
            return;
          }
          if (!pageIsIncome && (/amount|borrow|loan.?amt|requested/.test(k) || (pageIsAmount && /number|tel|text/.test(typ)))) {
            if (setV(e, V.loan_amount)) n++;
          } else if (/first|fname|given/.test(k) && !/last/.test(k)) {
            if (isEmpty && setV(e, V.first_name)) n++;
          } else if (/last|lname|surname|family/.test(k)) {
            if (isEmpty && setV(e, V.last_name)) n++;
          } else if (/e-?mail/.test(k)) {
            if (isEmpty && setV(e, V.email)) n++;
          } else if ((/phone|mobile|cell/.test(k) || typ === 'tel') && !fieldIsIncome && !fieldIsDob && !pageIsAmount && !pageIsDob) {
            if (isEmpty && setV(e, V.phone || V.phone_fmt)) n++;
          } else if (/zip|postal/.test(k)) {
            if (isEmpty && setV(e, V.zip)) n++;
          } else if (/city/.test(k)) {
            if (isEmpty && setV(e, V.city)) n++;
          } else if (/street|address/.test(k) && !/email/.test(k)) {
            if (isEmpty && setV(e, V.address)) n++;
          } else if (/ssn|social/.test(k)) {
            const ssnDigits = cur.replace(/\D/g,'');
            if (ssnDigits.length !== 9 && setV(e, V.ssn)) n++;
          } else if (/employer|company/.test(k)) {
            if (isEmpty && setV(e, V.employer)) n++;
          } else if (/routing|\baba\b/.test(k)) {
            if (isEmpty && setV(e, V.routing)) n++;
          } else if (/account/.test(k) && !/type/.test(k)) {
            if (isEmpty && setV(e, V.account)) n++;
          } else if (pageIsAmount && isEmpty && /number|tel|text/.test(typ)) {
            if (setV(e, V.loan_amount)) n++;
          }
        });
        // Anything still empty — fill with a sensible value so we never stall.
        document.querySelectorAll('input,select,textarea').forEach(e => {
          if (!vis(e) || e.disabled || e.readOnly) return;
          const typ = (e.type||'').toLowerCase();
          if (['hidden','radio','checkbox','submit','button','file','image'].includes(typ)) return;
          if (e.tagName === 'SELECT') {
            if (e.selectedIndex > 0) return;
            for (let i = 1; i < e.options.length; i++) {
              if (!/select|choose|please|--/.test(e.options[i].text)) {
                e.selectedIndex = i;
                e.dispatchEvent(new Event('change', {bubbles:true}));
                n++;
                return;
              }
            }
            return;
          }
          const cur = (e.value||'').replace(/[$,\s]/g,'');
          const k = key(e);
          const fieldIsDob = /dob|birth|birthday/.test(k) || pageIsDob || typ === 'date';
          const fieldIsAnnual = (/annual|pre-?tax|yearly/.test(k) || pageIsAnnual) && !fieldIsDob;
          const fieldIsIncome = (/income|salary|gross|net.?pay|monthly.?pay/.test(k) || pageIsIncome)
            && !fieldIsDob && !fieldIsAnnual;
          if (/apt|suite|unit|apartment|addr2|address.?2|address.?line.?2|line.?2|addl|additional.?addr/.test(k)) {
            if ((e.value || '').trim()) setV(e, V.apt || '');
            return;
          }
          if (fieldIsDob && dobBad(cur)) {
            if (setV(e, V.dob)) n++;
            return;
          }
          if (fieldIsAnnual && annualBad(cur)) {
            if (setV(e, V.annual_income || String((parseInt(V.income||'4500',10)||4500)*12))) n++;
            return;
          }
          if (fieldIsIncome && incomeBad(cur)) {
            if (setV(e, V.income)) n++;
            return;
          }
          if (cur && cur !== '0' && cur !== '00') return;
          let val = '';
          if (typ === 'email' || /email/.test(k)) val = V.email;
          else if (fieldIsDob) val = V.dob;
          else if (fieldIsAnnual) val = V.annual_income;
          else if (fieldIsIncome) val = V.income;
          else if ((typ === 'tel' || /phone|mobile|cell/.test(k)) && !pageIsIncome && !pageIsAmount && !pageIsDob && !pageIsAnnual)
            val = V.phone || V.phone_fmt;
          else if (typ === 'number' || /amount|borrow|income|salary/.test(k) || pageIsIncome || pageIsAnnual)
            val = (pageIsAnnual || /annual|pre-?tax/.test(k)) ? (V.annual_income || V.income)
              : (pageIsIncome || /income|salary/.test(k)) ? V.income : V.loan_amount;
          else if (/zip|postal/.test(k)) val = V.zip;
          else if (/city/.test(k)) val = V.city;
          else if (/state/.test(k)) val = V.state;
          else if (/address|street/.test(k) && !/apt|suite|unit/.test(k)) val = V.address;
          else if (/first|fname/.test(k)) val = V.first_name;
          else if (/last|lname|surname/.test(k)) val = V.last_name;
          else if (/ssn|social/.test(k)) val = V.ssn;
          else if (typ === 'date') val = (V.dob_y||'1988')+'-'+String(V.dob_m||'6').padStart(2,'0')+'-'+String(V.dob_d||'15').padStart(2,'0');
          else if (pageIsDob) val = V.dob;
          else if (pageIsAnnual) val = V.annual_income;
          if (val && setV(e, val)) n++;
        });
        if (/direct deposit|paid via direct/i.test(heading + ' ' + ((document.body && document.body.innerText) || '').slice(0, 1800))) {
          const wantYes = String(V.direct_deposit || 'yes').toLowerCase() !== 'no';
          document.querySelectorAll('input[type=radio]').forEach(r => {
            const lab = (((r.labels && r.labels[0] && r.labels[0].innerText) || r.value || '') + '').toLowerCase().trim();
            if (wantYes && /^yes\b/.test(lab) && !r.checked) { r.click(); n++; }
            if (!wantYes && /^no\b/.test(lab) && !r.checked) { r.click(); n++; }
          });
        }
        document.querySelectorAll('input[type=checkbox]').forEach(c => {
          if (!vis(c) || c.checked) return;
          const k = ((c.name||'')+' '+(c.id||'')+' '+((c.labels&&c.labels[0]&&c.labels[0].innerText)||'')).toLowerCase();
          if (/agree|terms|consent|authorize|privacy|opt.?in|confirm/.test(k)) { c.click(); n++; }
        });
        return n;
    }"""

    _JS_CLICK_CHOICE = r"""(V) => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 20 && r.height >= 16
            && st.visibility !== 'hidden' && st.display !== 'none'
            && st.pointerEvents !== 'none';
        };
        const text = e => ((e.innerText || e.getAttribute('aria-label') || e.value || '')+'').replace(/\s+/g,' ').trim();
        const skip = /(see all options|more options|advertiser|disclosure|privacy|terms|log ?in|cookie|back|cancel|notice|legal|policy|learn more|read more|article|blog)/i;
        const purposes = [
          'debt consolidation','credit card consolidation','pay off credit cards',
          'home improvement','business','auto','emergency','personal','other','credit cards',
          'excellent','good','fair','poor','employed','self employed','full-time','full time',
          'monthly','bi-weekly','biweekly','weekly','checking','savings',
          'twice a month','every other week','semi-monthly','semi monthly'
        ];
        const short = new Set(['personal','emergency','auto','business','other','good','fair','poor','excellent','employed','monthly','weekly']);
        const preferred = (V.purpose || []).map(s => (s||'').toLowerCase());
        const matchPurpose = (raw) => {
          const low = (raw || '').toLowerCase().replace(/\s+/g, ' ').trim();
          if (!low || skip.test(low) || low.length > 40) return '';
          const hits = purposes.filter(p =>
            low === p || low === p + ' loan' || low.startsWith(p + ' ')
            || (!short.has(p) && low.includes(p) && low.length <= p.length + 18)
          );
          // Parent wrappers contain every option — ignore those.
          if (hits.length !== 1) return '';
          return hits[0];
        };
        const rank = (hit) => {
          const i = preferred.findIndex(p => hit.includes(p) || p.includes(hit));
          return i === -1 ? 99 : i;
        };

        const radioRows = [];
        document.querySelectorAll('input[type=radio], input[type=checkbox]').forEach(inp => {
          if (!vis(inp) && !(inp.labels && inp.labels[0] && vis(inp.labels[0]))) return;
          let lab = '';
          if (inp.labels && inp.labels[0]) lab = text(inp.labels[0]);
          if (!lab && inp.id) {
            const l = document.querySelector('label[for="'+inp.id+'"]');
            if (l) lab = text(l);
          }
          if (!lab) {
            const wrap = inp.closest('label,li,[role=radio],[role=option]');
            if (wrap) lab = text(wrap);
          }
          if (lab && lab.length > 48) lab = '';
          const hit = matchPurpose(lab);
          if (hit) radioRows.push({el: inp, t: lab, hit, checked: !!inp.checked});
        });
        if (radioRows.length) {
          radioRows.sort((a,b) => rank(a.hit) - rank(b.hit));
          const pick = radioRows.find(x => !x.checked) || radioRows[0];
          if (pick.checked) return '';
          const labEl = (pick.el.labels && pick.el.labels[0])
            || (pick.el.id && document.querySelector('label[for="'+pick.el.id+'"]'))
            || pick.el;
          labEl.scrollIntoView({block:'center', inline:'nearest'});
          labEl.click();
          if (!pick.el.checked) pick.el.click();
          return (pick.t || pick.hit).slice(0, 60);
        }

        const nodes = Array.from(document.querySelectorAll(
          'button,[role=button],[role=radio],[role=option],a,label,li,div,span'
        )).filter(vis);
        const tiles = [];
        for (const el of nodes) {
          const t = text(el);
          const hit = matchPurpose(t);
          if (!hit) continue;
          if ((hit === 'personal' || hit === 'emergency' || hit === 'auto' || hit === 'business')
              && t.split(/\s+/).length > 3) continue;
          tiles.push({el, t, hit});
        }
        if (tiles.length) {
          tiles.sort((a,b) => rank(a.hit) - rank(b.hit));
          const pick = tiles[0];
          const target = pick.el.closest('a,button,[role=button],label') || pick.el;
          target.scrollIntoView({block:'center', inline:'nearest'});
          target.click();
          return pick.t.slice(0, 60);
        }

        // Any radio group with nothing selected — pick the first real option.
        const groups = {};
        document.querySelectorAll('input[type=radio]').forEach(r => {
          const name = r.name || '_anon';
          (groups[name] = groups[name] || []).push(r);
        });
        for (const list of Object.values(groups)) {
          if (list.some(r => r.checked)) continue;
          const r = list[0];
          const lab = (r.labels && r.labels[0]) || r;
          lab.scrollIntoView({block:'center', inline:'nearest'});
          lab.click();
          if (!r.checked) r.click();
          return (text(lab) || 'radio').slice(0, 60);
        }

        // Generic answer tiles — never sliders, footers, or dollar-range chrome.
        const skipHard = /privacy|terms|login|cookie|advertiser|notice|disclosure|see all|more options|back|cancel|close|session replay|trustpilot|rating|policy/i;
        const cards = Array.from(document.querySelectorAll(
          'button,a,[role=button],[role=option],[role=radio],label'
        )).filter(vis);
        for (const el of cards) {
          if (el.closest('footer,nav,input[type=range],[role=slider]')) continue;
          const t = text(el);
          if (!t || t.length < 2 || t.length > 42 || skipHard.test(t)) continue;
          if (/^\$[\d,.\s$kK–—-]+$/i.test(t)) continue;
          if (/^(next|continue|submit|back)$/i.test(t)) continue;
          const r = el.getBoundingClientRect();
          if (r.width < 48 || r.height < 28 || r.width > 720) continue;
          el.scrollIntoView({block:'center', inline:'nearest'});
          el.click();
          return t.slice(0, 60);
        }
        return '';
    }"""

    _JS_CLICK_EXACT_OPTION = r"""(label) => {
        const want = String(label || '').toLowerCase().replace(/\s+/g, ' ').trim();
        if (!want) return '';
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 20 && r.height >= 16
            && st.visibility !== 'hidden' && st.display !== 'none'
            && st.pointerEvents !== 'none';
        };
        const text = e => ((e.innerText || e.getAttribute('aria-label') || '') + '')
          .replace(/\s+/g, ' ').trim();
        const skip = /more options|see all|next|continue|privacy|terms|advertiser|learn more|read more|notice|unsubscribe|disclosure|legal|policy/i;
        const nodes = Array.from(document.querySelectorAll(
          'input[type=radio],label,button,li,[role=button],[role=radio],[role=option],[role=listitem],div,span'
        )).filter(vis);
        const hits = [];
        for (const el of nodes) {
          if (el.closest('nav,header,footer')) continue;
          const href = ((el.closest('a') || el).getAttribute('href') || '');
          if (/^https?:/i.test(href) && !/#/.test(href)) continue;
          const t = text(el);
          if (!t || skip.test(t) || t.length > 48) continue;
          const low = t.toLowerCase();
          if (!(low === want || low === want + ' loan' || low === want + '.'
                || (low.startsWith(want) && low.length <= want.length + 12))) continue;
          const multi = (low.match(/debt consolidation|credit card consolidation|home improvement/g) || []).length;
          if (multi > 1) continue;
          const r = el.getBoundingClientRect();
          hits.push({el, t, w: r.width * r.height});
        }
        if (!hits.length) return '';
        hits.sort((a,b) => a.w - b.w);
        const pick = hits[0];
        const target = pick.el.closest('label,button,[role=button],[role=radio],[role=option],li') || pick.el;
        target.scrollIntoView({block:'center', inline:'nearest'});
        target.click();
        if (pick.el.type === 'radio' && !pick.el.checked) pick.el.click();
        return (text(target) || pick.t).slice(0, 60);
    }"""

    _JS_CLICK_STACK = r"""(V) => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 40 && r.height >= 22
            && st.visibility !== 'hidden' && st.display !== 'none'
            && st.pointerEvents !== 'none';
        };
        const text = e => ((e.innerText || e.getAttribute('aria-label') || '')+'').replace(/\s+/g,' ').trim();
        const skip = /(next|continue|submit|back|cancel|notice|privacy|terms|advertiser|unsubscribe|more options|see all|log ?in)/i;
        const preferred = (V.purpose || []).concat([
          String(V.direct_deposit || 'yes').toLowerCase() === 'no' ? 'no' : 'yes'
        ]).map(s => (s||'').toLowerCase());
        const cards = Array.from(document.querySelectorAll(
          'button,a,[role=button],[role=radio],[role=option],label,li'
        )).filter(vis).map(el => ({el, t: text(el)})).filter(x =>
          x.t && x.t.length >= 2 && x.t.length <= 36
          && !skip.test(x.t) && x.t.split(/\s+/).length <= 5
          && !x.el.closest('nav,header,footer')
        );
        if (cards.length < 2) return '';
        const score = (t) => {
          const low = t.toLowerCase();
          const i = preferred.findIndex(p => low === p || low.includes(p) || p.includes(low));
          return i === -1 ? 99 : i;
        };
        cards.sort((a,b) => score(a.t) - score(b.t));
        const pick = cards[0];
        const target = pick.el.closest('button,a,label,[role=button],[role=radio]') || pick.el;
        target.scrollIntoView({block:'center', inline:'nearest'});
        target.click();
        return pick.t.slice(0, 60);
    }"""

    _JS_CLICK_NEXT = r"""() => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 24 && r.height >= 18
            && st.visibility !== 'hidden' && st.display !== 'none'
            && st.pointerEvents !== 'none'
            && !e.disabled;
        };
        const text = e => ((e.innerText || e.value || e.getAttribute('aria-label') || '')+'').replace(/\s+/g,' ').trim();
        const cookie = /(accept all|accept cookies|^accept$|i agree|allow all|got it|agree and close)/i;
        const cookieBtn = Array.from(document.querySelectorAll(
          'button,a,[role=button],input[type=button],input[type=submit]'
        )).filter(vis).find(e => {
          const s = text(e);
          return s && s.length < 40 && cookie.test(s);
        });
        if (cookieBtn) {
          cookieBtn.click();
          return text(cookieBtn).slice(0, 40);
        }
        const landing = /(get started|start now|start here|apply now|find\s*(my\s*)?offers?|check\s*(my\s*)?(rates?|offers?)|see\s*(my\s*)?(rates?|offers?)|view\s*(my\s*)?offers?|show\s*(me\s*)?(results|offers)|get\s*(my\s*)?(rates?|offers?)|get pre-?qualified|unlock|compare rates|see if i qualify|personalized)/i;
        const stepGo = /(^next$|^continue$|^proceed$|^submit$)/i;
        const go = new RegExp(landing.source + '|' + stepGo.source, 'i');
        const no = /(back|cancel|decline|previous|see all options|more options|disclosure|privacy|terms|log ?in|sign ?in|advertiser|notice|legal|policy)/i;
        const radios = Array.from(document.querySelectorAll('input[type=radio]')).filter(r => {
          if (vis(r)) return true;
          const lab = (r.labels && r.labels[0]) || (r.id && document.querySelector('label[for="'+r.id+'"]'));
          return !!(lab && vis(lab));
        });
        const unanswered = radios.length && !radios.some(r => r.checked);
        const btns = Array.from(document.querySelectorAll(
          'button,input[type=submit],input[type=button],[role=button],a.btn,a.button,a'
        )).filter(vis);
        const b = btns.find(e => {
          const s = text(e);
          if (!s || s.length > 60 || !go.test(s) || no.test(s)) return false;
          if (unanswered && stepGo.test(s) && !landing.test(s)) return false;
          return true;
        });
        if (!b) return '';
        b.scrollIntoView({block:'center', inline:'nearest'});
        b.click();
        return text(b).slice(0, 40);
    }"""

    _JS_CLICK_VIEW_OFFERS = r"""() => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 40 && r.height >= 18
            && st.visibility !== 'hidden' && st.display !== 'none';
        };
        const text = e => ((e.innerText || e.value || e.getAttribute('aria-label') || '')+'')
          .replace(/\s+/g,' ').trim();
        const go = /^(view\s*(my\s*)?offers?|see\s*(my\s*)?offers?)$/i;
        const els = Array.from(document.querySelectorAll(
          'button,input[type=submit],input[type=button],[role=button],a.btn,a.button,[class*="btn"],[class*="Button"]'
        ));
        const b = els.find(e => vis(e) && go.test(text(e)) && text(e).length < 40);
        if (!b) return '';
        try { b.disabled = false; } catch (err) {}
        b.scrollIntoView({block:'center', inline:'nearest'});
        b.click();
        return text(b).slice(0, 40);
    }"""

    # "Congratulations / you have been selected / being redirected" is NOT here:
    # the main funnel shows that while it hands off to the extra form, and that
    # page has to be followed into the extra form.
    _JS_SECONDARY_DONE = r"""() => {
        const body = ((document.body && document.body.innerText) || '').toLowerCase().slice(0, 2500);
        return /(thank you for (your )?(app|request|submi)|application (has been )?(received|submitted|complete)|we('?| ha)ve received|no (more )?offers? available|unable to (find|match)|sorry,? we (couldn|cannot))/i.test(body);
    }"""

    _JS_SECONDARY_STOP = r"""() => {
        const body = ((document.body && document.body.innerText) || '').toLowerCase().slice(0, 2500);
        const h = [...document.querySelectorAll('h1,h2,h3,.title,.headline,legend,label')]
          .map(e => (e.innerText||'').toLowerCase()).join(' ');
        const blob = h + ' ' + body;
        if (/(create (an? )?account|create (a )?password|set (your )?password|confirm password|new password|choose a password)/i.test(blob))
          return 'password';
        if (/(card number|debit card|credit card number|\bcvv\b|\bcvc\b|expir(y|ation) date|payment method|add (a )?(credit )?card|billing zip|pay now|checkout)/i.test(blob)
            && !/credit card (debt|consolidation|balance)/i.test(blob))
          return 'payment';
        return '';
    }"""

    _JS_UNANSWERED_CHOICE = r"""() => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 16 && r.height >= 12
            && st.visibility !== 'hidden' && st.display !== 'none';
        };
        const radios = Array.from(document.querySelectorAll('input[type=radio]')).filter(r => {
          if (vis(r)) return true;
          const lab = (r.labels && r.labels[0]) || (r.id && document.querySelector('label[for="'+r.id+'"]'));
          return !!(lab && vis(lab));
        });
        // Every group must be answered — one answered group is not enough when
        // the page asks several questions at once.
        const groups = {};
        for (const r of radios) {
          const k = r.name || ('__' + (r.id || Math.random()));
          (groups[k] = groups[k] || []).push(r);
        }
        for (const k in groups) {
          if (!groups[k].some(r => r.checked)) return true;
        }
        const selects = Array.from(document.querySelectorAll('select')).filter(vis);
        for (const s of selects) {
          const t = (s.options[s.selectedIndex] || {}).text || '';
          if (!s.value || /^\s*(please )?(select|choose|--)/i.test(t)) return true;
        }
        const h = [...document.querySelectorAll('h1,h2,h3,.title,.headline,legend,p,label')]
          .map(e => (e.innerText||'')).join(' ').toLowerCase().slice(0, 1200);
        if (/what.?s this loan for|choose the closest|credit score|employment status|how are you paid|loan for|how is your credit/.test(h)) {
          const tiles = Array.from(document.querySelectorAll(
            '[role=radio],label,button,[class*="option"],[class*="Option"],[class*="choice"]'
          )).filter(vis);
          const selected = tiles.some(el =>
            el.getAttribute('aria-checked') === 'true'
            || /selected|active|checked/i.test(String(el.className||'')));
          if (tiles.length >= 2 && !selected && !radios.some(r => r.checked)) return true;
        }
        return false;
    }"""

    _PRIMARY_CTA = (
        r"accept all",
        r"accept cookies",
        r"^i agree$",
        r"allow all",
        r"find my offers",
        r"get started",
        r"start now",
        r"start here",
        r"see if i qualify",
        r"^next$",
        r"^continue$",
        r"apply now",
        r"view (my )?offers",
        r"see (my )?offers",
        r"see (my )?rates",
        r"check (my )?(rates|offers)",
        r"get (my )?(rates?|offers?)",
        r"get pre-?qualified",
        r"show (me )?(results|offers)",
        r"compare rates",
        r"^submit$",
    )

    def _secondary_page_kind(self, page: Page) -> str:
        try:
            data = page.evaluate(
                """() => {
                  const heads = [...document.querySelectorAll('h1,h2,h3,.title,.headline,legend')]
                    .map(e => e.innerText||'').join(' ');
                  const body = ((document.body && document.body.innerText) || '').slice(0, 900);
                  return {
                    heads: ((location.pathname||'')+' '+(location.href||'')+' '+heads).toLowerCase(),
                    body: body.toLowerCase()
                  };
                }"""
            ) or {}
            heads = str(data.get("heads") or "")
            blob = heads + " " + str(data.get("body") or "")
        except Exception:
            heads = (page.url or "").lower()
            blob = heads
        if re.search(r"/ssn\b|unable to verify|social security number|confirmation\.html", blob, re.I):
            return "ssn"
        if re.search(r"annual (pre-?tax )?income|pre-?tax income|yearly income|what.?s your annual", blob, re.I):
            return "annual_income"
        if re.search(r"/dob\b|date of birth|birth.?date|what is your date of birth|\bbirthday\b", blob, re.I):
            return "dob"
        if re.search(
            r"monthly[-_/ ]?income|/income\b|salary|gross.?pay|net.?pay|"
            r"how much do you (make|earn)|what is your (monthly )?income",
            blob,
            re.I,
        ):
            return "income"
        if re.search(r"loan[-_/ ]?amount|how much.*(borrow|need)|requested amount", blob, re.I):
            return "amount"
        if re.search(
            r"/credit-score|/loan-purpose|/account-type|/employment|/pay-frequency|"
            r"/income-source|/pay-type|/direct-deposit|"
            r"what.?s this loan for|choose the closest|employment status|"
            r"how are you paid|how often are you paid|how is your credit|"
            r"what is your credit score|account type|checking or saving|"
            r"direct deposit|do you have direct",
            blob, re.I,
        ):
            return "choice"
        return ""

    def _type_secondary_dob(self, page: Page, dob: str) -> bool:
        """Type a valid MM/DD/YYYY into masked tel/text DOB fields."""
        want = self._valid_mmddyyyy(dob) or "06/15/1988"
        want_digits = re.sub(r"\D", "", want)
        try:
            boxes = page.locator(
                "input[type='tel']:visible, input[type='text']:visible, "
                "input[type='date']:visible, input[inputmode='numeric']:visible"
            )
            count = boxes.count()
            if count == 0:
                return False
            box = boxes.first
            for i in range(min(count, 6)):
                el = boxes.nth(i)
                meta = " ".join([
                    el.get_attribute("name") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("placeholder") or "",
                    el.get_attribute("aria-label") or "",
                    el.get_attribute("type") or "",
                ])
                if re.search(r"dob|birth|date", meta, re.I):
                    box = el
                    break
            cur_digits = re.sub(r"\D", "", box.input_value() or "")
            if cur_digits == want_digits and self._valid_mmddyyyy(box.input_value() or want):
                return False
            box.click(timeout=4000)
            box.press("Control+A")
            box.press("Backspace")
            try:
                box.fill("")
            except Exception:
                pass
            typ = (box.get_attribute("type") or "").lower()
            if typ == "date":
                y, m, d = want.split("/")[2], want.split("/")[0], want.split("/")[1]
                box.fill(f"{y}-{m}-{d}")
            else:
                box.type(want_digits, delay=50)
            box.press("Tab")
            time.sleep(0.35)
            got = re.sub(r"\D", "", box.input_value() or "")
            return got == want_digits or bool(self._valid_mmddyyyy(box.input_value() or ""))
        except Exception:
            return False

    def _type_secondary_ssn(self, page: Page, ssn: str) -> bool:
        want = re.sub(r"\D", "", str(ssn or ""))
        if len(want) != 9:
            return False
        try:
            boxes = page.locator(
                "input[type='tel']:visible, input[type='text']:visible, "
                "input[type='password']:visible, input[inputmode='numeric']:visible"
            )
            count = boxes.count()
            if count == 0:
                return False
            box = boxes.first
            for i in range(min(count, 8)):
                el = boxes.nth(i)
                meta = " ".join([
                    el.get_attribute("name") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("placeholder") or "",
                    el.get_attribute("aria-label") or "",
                ])
                if re.search(r"ssn|social", meta, re.I):
                    box = el
                    break
            cur = re.sub(r"\D", "", box.input_value() or "")
            if cur == want:
                return False
            box.click(timeout=4000)
            box.press("Control+A")
            box.press("Backspace")
            try:
                box.fill("")
            except Exception:
                pass
            box.type(want, delay=40)
            box.press("Tab")
            time.sleep(0.35)
            got = re.sub(r"\D", "", box.input_value() or "")
            return got == want or len(got) >= 9
        except Exception:
            return False

    def _click_direct_deposit(self, page: Page, yes: bool = True) -> str:
        try:
            blob = page.evaluate(
                "() => ((document.body && document.body.innerText) || '').slice(0, 2000).toLowerCase()"
            ) or ""
        except Exception:
            blob = ""
        if not re.search(r"direct deposit", blob, re.I):
            return ""
        label = "Yes" if yes else "No"
        locators = [
            page.get_by_role("radio", name=re.compile(rf"^{label}$", re.I)),
            page.get_by_label(re.compile(rf"^{label}$", re.I)),
            page.locator("label,button,[role=button],[role=radio],span").filter(
                has_text=re.compile(rf"^{label}$", re.I)
            ),
            page.get_by_text(re.compile(rf"^{label}$", re.I)),
        ]
        for loc in locators:
            try:
                if loc.count() == 0:
                    continue
                el = loc.first
                if el.is_visible():
                    el.click(timeout=3000)
                    return label
            except Exception:
                continue
        return ""

    def _type_secondary_income(self, page: Page, income: str, *, annual: bool = False) -> bool:
        """Type monthly or annual income into masked currency/tel fields."""
        want = re.sub(r"\D", "", str(income or "")) or ("36000" if annual else "4500")
        lo, hi = (18000, 200000) if annual else (1500, 20000)
        try:
            n = int(want)
            if n < lo or n > hi:
                want = "36000" if annual else "4500"
        except ValueError:
            want = "36000" if annual else "4500"
        try:
            boxes = page.locator(
                "input[type='tel']:visible, input[type='text']:visible, "
                "input[type='number']:visible, input[inputmode='numeric']:visible, "
                "input[inputmode='decimal']:visible"
            )
            count = boxes.count()
            if count == 0:
                return False
            box = boxes.first
            for i in range(min(count, 6)):
                el = boxes.nth(i)
                meta = " ".join([
                    el.get_attribute("name") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("placeholder") or "",
                    el.get_attribute("aria-label") or "",
                ])
                if re.search(r"income|salary|gross|amount|pay", meta, re.I):
                    box = el
                    break
            cur = re.sub(r"\D", "", box.input_value() or "")
            try:
                cur_n = int(cur) if cur else 0
            except ValueError:
                cur_n = 0
            if cur == want or (lo <= cur_n <= hi and (annual or len(cur) <= 5)):
                return False
            box.click(timeout=4000)
            box.press("Control+A")
            box.press("Backspace")
            try:
                box.fill("")
            except Exception:
                pass
            box.type(want, delay=45)
            box.press("Tab")
            time.sleep(0.35)
            got = re.sub(r"\D", "", box.input_value() or "")
            try:
                got_n = int(got) if got else 0
            except ValueError:
                got_n = 0
            return got == want or lo <= got_n <= hi
        except Exception:
            return False

    _SECONDARY_CHOICE_LABELS = (
        "Debt Consolidation",
        "Credit Card Consolidation",
        "Home Improvement",
        "Emergency",
        "Moving",
        "Medical",
        "Auto",
        "Business",
        "Personal",
        "Other",
        "Excellent (720+)",
        "Excellent",
        "Good (680-719)",
        "Good",
        "Fair",
        "Poor",
        "Employed",
        "Self Employed",
        "Self-Employed",
        "Full-Time",
        "Full Time",
        "Monthly",
        "Bi-Weekly",
        "Biweekly",
        "Weekly",
        "Every Other Week",
        "Twice A Month",
        "Twice a Month",
        "Semi-Monthly",
        "Semi Monthly",
        "Yes",
        "No",
        "Checking",
        "Savings",
        "Checking Account",
        "Savings Account",
    )

    def _unanswered_choice_page(self, page: Page) -> bool:
        if self._visible_choice_tiles(page):
            return True
        try:
            return bool(page.evaluate(self._JS_UNANSWERED_CHOICE))
        except Exception:
            return False

    _JS_EMPTY_REQUIRED = r"""() => {
        const vis = e => {
          if (!e) return false;
          const r = e.getBoundingClientRect();
          const st = getComputedStyle(e);
          return r.width >= 30 && r.height >= 12
            && st.visibility !== 'hidden' && st.display !== 'none';
        };
        const out = [];
        const els = Array.from(document.querySelectorAll(
          'input[required],select[required],textarea[required],' +
          '[aria-required=true],[aria-invalid=true],.error input,.invalid input'
        ));
        for (const e of els) {
          const t = (e.type || '').toLowerCase();
          if (t === 'hidden' || t === 'submit' || t === 'button') continue;
          if (t === 'checkbox' || t === 'radio') continue;
          if (!vis(e)) continue;
          if (String(e.value || '').trim()) continue;
          out.push((e.name || e.id || e.placeholder || t || 'field').slice(0, 24));
        }
        return out.slice(0, 8).join(',');
    }"""

    def _empty_required(self, page: Page) -> str:
        """Names of visible required fields still blank — fill before Next."""
        try:
            return str(page.evaluate(self._JS_EMPTY_REQUIRED) or "")
        except Exception:
            return ""

    def _visible_choice_tiles(self, page: Page) -> list[str]:
        """True option tiles only (AmOne purpose / credit / job) — not landing copy."""
        found: list[str] = []
        markers = (
            "Debt Consolidation", "Credit Card Consolidation", "Home Improvement",
            "Excellent (720+)", "Good (680-719)", "Good", "Fair", "Employed",
            "Full-Time", "Full Time", "Checking", "Savings",
            "Monthly", "Weekly", "Twice A Month", "Every Other Week",
            "Yes", "No",
        )
        for lab in markers:
            try:
                loc = page.locator("button,[role=button],[role=radio],[role=option],label,li").filter(
                    has_text=re.compile(rf"^{re.escape(lab)}$", re.I)
                )
                if loc.count() and loc.first.is_visible():
                    found.append(lab)
            except Exception:
                continue
        return found

    def _choice_labels(self, vals: dict) -> list[str]:
        """Sheet purpose/credit first, then other valid AmOne-style options."""
        ordered: list[str] = []
        for pref in vals.get("purpose") or []:
            p = str(pref or "").strip().lower()
            if not p:
                continue
            for lab in self._SECONDARY_CHOICE_LABELS:
                if p in lab.lower() or lab.lower() in p:
                    if lab not in ordered:
                        ordered.append(lab)
        for lab in self._SECONDARY_CHOICE_LABELS:
            if lab not in ordered:
                ordered.append(lab)
        return ordered

    def _click_label_exact(self, page: Page, label: str) -> str:
        for fr in list(page.frames):
            try:
                if fr.is_detached():
                    continue
                hit = fr.evaluate(self._JS_CLICK_EXACT_OPTION, label) or ""
            except Exception:
                hit = ""
            if hit:
                return str(hit)[:60]
        rx = re.compile(re.escape(label), re.I)
        locators = [
            page.locator("button").filter(has_text=rx),
            page.locator("[role=button],[role=radio],[role=option],label,li").filter(has_text=rx),
            page.get_by_text(label, exact=False),
        ]
        for loc in locators:
            try:
                n = loc.count()
            except Exception:
                continue
            for i in range(min(n, 8)):
                try:
                    el = loc.nth(i)
                    if not el.is_visible():
                        continue
                    txt = re.sub(r"\s+", " ", el.inner_text() or "").strip()
                    if re.search(
                        r"more options|see all|^next$|^continue$|notice|privacy|terms|"
                        r"unsubscribe|disclosure|advertiser",
                        txt, re.I,
                    ):
                        continue
                    if len(txt.split()) > max(4, len(label.split()) + 1):
                        continue
                    if len(re.findall(
                        r"debt consolidation|credit card consolidation|home improvement",
                        txt, re.I,
                    )) > 1:
                        continue
                    if len(txt) > 64:
                        continue
                    if label.lower() not in txt.lower():
                        continue
                    el.scroll_into_view_if_needed(timeout=3000)
                    try:
                        el.click(timeout=4000, force=True)
                    except Exception:
                        el.click(timeout=4000)
                    return (txt or label)[:60]
                except Exception:
                    continue
        return ""

    def _click_secondary_choice(self, page: Page, vals: dict) -> str:
        """Pick a visible answer tile (AmOne loan purpose, credit, employment, …)."""
        for label in self._choice_labels(vals):
            hit = self._click_label_exact(page, label)
            if hit:
                return hit
        for fr in list(page.frames):
            try:
                if fr.is_detached():
                    continue
                hit = fr.evaluate(self._JS_CLICK_CHOICE, vals) or ""
            except Exception:
                hit = ""
            if hit and not re.search(r"more options|see all|^next$|notice", str(hit), re.I):
                return str(hit)[:60]
        for fr in list(page.frames):
            try:
                if fr.is_detached():
                    continue
                hit = fr.evaluate(self._JS_CLICK_STACK, vals) or ""
            except Exception:
                hit = ""
            if hit:
                return str(hit)[:60]
        return ""

    def _click_view_offers(self, page: Page) -> str:
        """Click VIEW OFFERS on the SSN step — never the legal-copy mention of it."""
        for fr in list(page.frames):
            try:
                if fr.is_detached():
                    continue
                hit = fr.evaluate(self._JS_CLICK_VIEW_OFFERS) or ""
            except Exception:
                hit = ""
            if hit:
                return str(hit)[:40]
        rx = re.compile(r"view (my )?offers", re.I)
        locators = [
            page.get_by_role("button", name=rx),
            page.get_by_role("link", name=rx),
            page.locator("button,input[type=submit],input[type=button],[role=button]").filter(has_text=rx),
        ]
        for loc in locators:
            try:
                if loc.count() == 0:
                    continue
                btn = loc.first
                if not btn.is_visible():
                    continue
                raw = re.sub(r"\s+", " ", (btn.inner_text() or btn.get_attribute("value") or "")).strip()
                if len(raw) > 48:
                    continue
                btn.scroll_into_view_if_needed(timeout=3000)
                try:
                    btn.click(timeout=4000)
                except Exception:
                    btn.click(timeout=4000, force=True)
                return raw[:40] or "VIEW OFFERS"
            except Exception:
                continue
        return ""

    def _click_primary_cta(self, page: Page, *, force: bool = False, allow_next: bool = True) -> str:
        """Click the real step button (Find My Offers / Next / Continue), not sliders."""
        unanswered = False if force else self._unanswered_choice_page(page)
        if not unanswered:
            view = self._click_view_offers(page)
            if view:
                return view
        for pat in self._PRIMARY_CTA:
            if (unanswered or not allow_next) and re.search(r"next|continue|submit", pat, re.I):
                continue
            rx = re.compile(pat, re.I)
            locators = []
            for role in ("button", "link"):
                try:
                    locators.append(page.get_by_role(role, name=rx))
                except Exception:
                    pass
            try:
                locators.append(page.locator(
                    "button,input[type=submit],input[type=button],[role=button]"
                ).filter(has_text=rx))
            except Exception:
                pass
            for loc in locators:
                try:
                    if loc.count() == 0:
                        continue
                    btn = loc.first
                    if not btn.is_visible():
                        continue
                    raw = re.sub(r"\s+", " ", (btn.inner_text() or btn.get_attribute("value") or pat)).strip()
                    if len(raw) > 48:
                        continue
                    label = raw[:40]
                    if re.search(r"privacy|terms|policy|replay|advertiser|notice|unsubscribe", label, re.I):
                        continue
                    if (unanswered or not allow_next) and re.search(r"^(next|continue|submit)$", label, re.I):
                        continue
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click(timeout=4000)
                    return label or pat
                except Exception:
                    continue
        return ""

    def _drive_secondary_funnel(self, page: Page, fields: dict, row_number: int, stop_event) -> str:
        """Fill every field and click every real CTA on any post-offer site until the end."""
        vals = self._secondary_vals(fields)
        cur = page
        deadline = time.time() + 360
        steps: list[str] = []
        choice_hits: dict[str, int] = {}
        req_hits: dict[str, int] = {}
        last_action = ""
        idle = 0
        max_steps = 40

        while time.time() < deadline and len(steps) < max_steps:
            self._check_stop(stop_event)
            cur = self._form_page(cur)
            try:
                cur.bring_to_front()
            except Exception:
                pass
            try:
                self._live(cur)
            except Exception:
                pass

            # Only a terminal page of the extra form itself ends the run. Before
            # any extra-form step, a congrats/handoff page is just a redirect.
            if steps and self._page_is_done(cur):
                log.info("form.secondary_done", row=row_number, url=(cur.url or "")[:80])
                steps.append("final page")
                break

            stop_why = ""
            try:
                stop_why = str(cur.evaluate(self._JS_SECONDARY_STOP) or "")
            except Exception:
                stop_why = ""
            if stop_why:
                log.info("form.secondary_stop", reason=stop_why, row=row_number,
                         url=(cur.url or "")[:80])
                steps.append(f"stop:{stop_why}")
                break

            kind = self._secondary_page_kind(cur)
            tiles = self._visible_choice_tiles(cur)
            unanswered = False if kind == "ssn" else (bool(tiles) or kind == "choice")

            # Fill first (sheet if present, else a valid dummy). Then click CTA.
            filled = 0
            for fr in list(cur.frames):
                try:
                    if fr.is_detached():
                        continue
                    filled += int(fr.evaluate(self._JS_FILL_SECONDARY, vals) or 0)
                except Exception:
                    pass
            if kind == "dob":
                if self._type_secondary_dob(cur, vals.get("dob") or "06/15/1988"):
                    filled += 1
                    log.info("form.secondary_dob_typed",
                             value=vals.get("dob"), row=row_number,
                             url=(cur.url or "")[:80])
            if kind == "income":
                if self._type_secondary_income(cur, vals.get("income") or "4500"):
                    filled += 1
                    log.info("form.secondary_income_typed",
                             value=vals.get("income"), row=row_number,
                             url=(cur.url or "")[:80])
            if kind == "annual_income":
                annual = vals.get("annual_income") or str(int(vals.get("income") or 4500) * 12)
                if self._type_secondary_income(cur, annual, annual=True):
                    filled += 1
                    log.info("form.secondary_annual_typed",
                             value=annual, row=row_number, url=(cur.url or "")[:80])
                dd = self._click_direct_deposit(cur, yes=str(vals.get("direct_deposit") or "yes") != "no")
                if dd:
                    filled += 1
                    log.info("form.secondary_direct_deposit", cta=dd, row=row_number)
            if kind == "ssn":
                if self._type_secondary_ssn(cur, vals.get("ssn") or ""):
                    filled += 1
                    log.info("form.secondary_ssn_typed", row=row_number,
                             url=(cur.url or "")[:80])
            if filled:
                idle = 0
                log.info("form.secondary_fill", count=filled, row=row_number,
                         url=(cur.url or "")[:80])
                time.sleep(0.9)

            action = ""
            if kind != "ssn":
                try:
                    action = self._click_secondary_choice(cur, vals)
                except Exception:
                    action = ""
                if not action:
                    try:
                        action = self._click_direct_deposit(
                            cur, yes=str(vals.get("direct_deposit") or "yes") != "no"
                        )
                    except Exception:
                        action = ""
                if not action:
                    try:
                        action = cur.evaluate(self._JS_CLICK_STACK, vals) or ""
                    except Exception:
                        action = ""
            if action:
                log.info("form.secondary_choice", cta=action, row=row_number)
                idle = 0
                time.sleep(0.8)
                # Another question may still be open on the same page — answer
                # them all before moving to the next step.
                choice_hits[action] = choice_hits.get(action, 0) + 1
                unanswered = self._unanswered_choice_page(cur)
                if unanswered and choice_hits[action] < 3:
                    steps.append(action)
                    last_action = ""
                    continue
                unanswered = False
            elif unanswered:
                idle += 1
                if idle >= 10:
                    log.info("form.secondary_idle", row=row_number, url=(cur.url or "")[:80])
                    break
                time.sleep(0.7)
                continue

            nxt = ""
            hold = False
            if kind == "ssn":
                try:
                    nxt = self._click_view_offers(cur) or self._click_primary_cta(cur, force=True) or ""
                except Exception:
                    nxt = ""
            else:
                # A blank required field means the details are not done yet, so
                # hold off on Next and let the fill pass run again first.
                missing = self._empty_required(cur)
                if missing:
                    req_hits[missing] = req_hits.get(missing, 0) + 1
                    log.info("form.secondary_missing", fields=missing, row=row_number,
                             tries=req_hits[missing])
                hold = bool(missing) and req_hits.get(missing, 0) <= 3
                try:
                    nxt = self._click_primary_cta(
                        cur,
                        force=kind in ("dob", "income", "annual_income", "amount"),
                        allow_next=not unanswered and not hold,
                    )
                except Exception:
                    nxt = ""
            if nxt:
                log.info("form.secondary_primary", cta=nxt, row=row_number)
                action = f"{action} → {nxt}" if action else nxt

            if not action and kind == "dob":
                if self._type_secondary_dob(cur, vals.get("dob") or "06/15/1988"):
                    time.sleep(0.7)
                try:
                    nxt = self._click_primary_cta(cur, force=True) or ""
                except Exception:
                    nxt = ""
                if nxt:
                    log.info("form.secondary_primary", cta=nxt, row=row_number)
                    action = nxt

            if not action and kind == "income":
                if self._type_secondary_income(cur, vals.get("income") or "4500"):
                    time.sleep(0.7)
                try:
                    nxt = self._click_primary_cta(cur, force=True) or ""
                except Exception:
                    nxt = ""
                if nxt:
                    log.info("form.secondary_primary", cta=nxt, row=row_number)
                    action = nxt

            if not action and kind == "annual_income":
                annual = vals.get("annual_income") or str(int(vals.get("income") or 4500) * 12)
                self._type_secondary_income(cur, annual, annual=True)
                self._click_direct_deposit(cur, yes=str(vals.get("direct_deposit") or "yes") != "no")
                time.sleep(0.7)
                try:
                    nxt = self._click_primary_cta(cur, force=True) or ""
                except Exception:
                    nxt = ""
                if nxt:
                    log.info("form.secondary_primary", cta=nxt, row=row_number)
                    action = nxt

            if not action and kind == "ssn":
                self._type_secondary_ssn(cur, vals.get("ssn") or "")
                time.sleep(0.7)
                try:
                    nxt = self._click_view_offers(cur) or self._click_primary_cta(cur, force=True) or ""
                except Exception:
                    nxt = ""
                if nxt:
                    log.info("form.secondary_primary", cta=nxt, row=row_number)
                    action = nxt

            if not action and not unanswered and not hold:
                for fr in list(cur.frames):
                    try:
                        if fr.is_detached():
                            continue
                        action = fr.evaluate(self._JS_CLICK_NEXT) or ""
                    except Exception:
                        action = ""
                    if action:
                        break

            if not action:
                idle += 1
                if (unanswered or hold) and idle < 14:
                    time.sleep(1.0)
                    continue
                if idle >= 8:
                    log.info("form.secondary_idle", row=row_number, url=(cur.url or "")[:80])
                    break
                time.sleep(1.4)
                continue

            try:
                sig = cur.evaluate(
                    "() => (location.pathname||'') + '|' + document.querySelectorAll('input,select,button,a').length"
                )
            except Exception:
                sig = (cur.url or "").split("?")[0]
            key = f"{sig}|{action}"
            if key == last_action:
                idle += 1
                if idle >= 3:
                    if kind == "dob" and self._type_secondary_dob(
                            cur, vals.get("dob") or "06/15/1988"):
                        idle = 0
                        last_action = ""
                        time.sleep(0.8)
                        continue
                    if kind == "income" and self._type_secondary_income(
                            cur, vals.get("income") or "4500"):
                        idle = 0
                        last_action = ""
                        time.sleep(0.8)
                        continue
                    if kind == "annual_income":
                        annual = vals.get("annual_income") or str(int(vals.get("income") or 4500) * 12)
                        self._type_secondary_income(cur, annual, annual=True)
                        self._click_direct_deposit(cur, yes=str(vals.get("direct_deposit") or "yes") != "no")
                        idle = 0
                        last_action = ""
                        time.sleep(0.8)
                        continue
                    if kind == "ssn" and self._type_secondary_ssn(cur, vals.get("ssn") or ""):
                        idle = 0
                        last_action = ""
                        time.sleep(0.8)
                        continue
                    retry = self._click_secondary_choice(cur, vals)
                    if retry:
                        idle = 0
                        last_action = ""
                        time.sleep(0.8)
                        continue
                    log.info("form.secondary_last_cta", cta=action, row=row_number)
                    steps.append(f"last CTA:{action}")
                    break
                time.sleep(1.5)
                continue
            last_action = key
            idle = 0
            steps.append(action)
            print(f"\n*** Secondary CTA — {action} ***\n", flush=True)
            log.info("form.secondary_cta", cta=action, row=row_number,
                     url=(cur.url or "")[:80])
            time.sleep(1.0)
            # SSN → VIEW OFFERS → Congratulations ends the extra form. Whatever
            # the lender opens after that (Wisdom Lending etc.) is left alone.
            if kind == "ssn" and re.search(r"view\s*(my\s*)?offers", action, re.I):
                end = self._wait_for_congrats(cur, 16)
                cur = end or cur
                log.info("form.secondary_done", row=row_number,
                         url=(cur.url or "")[:80], via="view offers")
                steps.append("congratulations")
                break
            cur = self._form_page(cur)
            try:
                cur.bring_to_front()
            except Exception:
                pass
            for state in ("domcontentloaded", "load"):
                try:
                    cur.wait_for_load_state(state, timeout=15000)
                except Exception:
                    pass
            time.sleep(0.8)

        self._screenshot(cur, row_number, "secondary_final")
        log.info("form.secondary_trail", steps=steps, row=row_number,
                 url=(cur.url or "")[:80])
        return " → ".join(steps) if steps else ""

    def _screenshot(self, page: Page, row: int, label: str) -> None:
        if not self._save_shots:
            return
        try:
            path = self._ss_dir / f"row_{row:04d}_{label}.png"
            page.screenshot(path=str(path), full_page=False)
        except Exception as e:
            log.warning("screenshot.failed", error=str(e)[:80])

    # ---------------------------------------------------------- post-offer flow
    # Shared post-offer lender-match back-end on several funnel sites.

    # Still working ("Thank you for your request / Connecting with our network of
    # trusted lenders") — wait, don't act.
    _JS_POST_STATE = r"""() => {
        const vis = e => e.offsetParent !== null && e.getClientRects().length > 0;
        const t = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
        const body = (document.body ? document.body.innerText : '').toLowerCase();
        const processing = /(connecting with|trusted lenders|should only take|do not refresh|do not leave|please wait|one moment|processing your|matching you|finding you|searching for|finalis|finaliz)/.test(body);
        const fields = Array.from(document.querySelectorAll('input,select,textarea'))
            .filter(e => vis(e) && e.type !== 'hidden' && !e.disabled && !e.readOnly)
            .map(e => (e.name || e.id || ''));
        const buttons = Array.from(document.querySelectorAll(
                'button,input[type=submit],input[type=button],[role=button],a.btn,a.button'))
            .filter(e => vis(e) && !e.disabled).map(t).filter(x => x && x.length < 40);
        return { processing, fields, buttons, sig: fields.join(',') + '|' + buttons.join(',') };
    }"""

    # Fill any bank / routing / account fields the offer asks for, from the lead.
    # Skips fields that already carry a value; matches by name/id/placeholder/label.
    _JS_FILL_BANK = r"""(V) => {
        const vis = e => e.offsetParent !== null && e.getClientRects().length > 0;
        const setV = (el, val) => { const p = Object.getPrototypeOf(el);
            const d = Object.getOwnPropertyDescriptor(p, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
            d.set.call(el, val); ['input','change','blur'].forEach(ev => el.dispatchEvent(new Event(ev, {bubbles:true}))); };
        const key = e => {
            let s = (e.name||'') + ' ' + (e.id||'') + ' ' + (e.placeholder||'') + ' ' + (e.getAttribute('aria-label')||'');
            const lf = e.id ? document.querySelector('label[for="' + e.id + '"]') : null;
            if (lf) s += ' ' + (lf.innerText || '');
            const wrap = e.closest('label');            // radios/checkboxes often wrap their label
            if (wrap) s += ' ' + (wrap.innerText || '');
            return s.toLowerCase();
        };
        let n = 0;
        document.querySelectorAll('input,select').forEach(e => {
            if (!vis(e) || e.disabled || e.readOnly || e.type === 'hidden' || e.type === 'radio' || e.type === 'checkbox') return;
            const k = key(e);
            if (e.tagName === 'SELECT') {
                if (/account type|acct type|type of account/.test(k)) {
                    const o = Array.from(e.options).find(o => new RegExp(V.account_type, 'i').test(o.text));
                    if (o) { e.value = o.value; e.dispatchEvent(new Event('change', {bubbles:true})); n++; }
                }
                return;
            }
            if (e.value && e.value.trim()) return;             // don't overwrite prefilled
            if (/routing|\baba\b|\brtn\b/.test(k))                  { setV(e, V.routing_number); n++; }
            else if (/account\s*(number|no|#)|acct\s*(number|no|#)/.test(k)
                     || (/account/.test(k) && !/type/.test(k)))    { setV(e, V.account_number); n++; }
            else if (/bank\s*name/.test(k) || (/bank/.test(k) && !/account/.test(k))) { setV(e, V.bank_name); n++; }
        });
        // account-type radios (checking / savings)
        const at = (V.account_type || '').toLowerCase();
        document.querySelectorAll('input[type=radio]').forEach(e => {
            if (!vis(e)) return; const k = key(e);
            if (/account type|acct|checking|savings/.test(k)) {
                if ((at.includes('sav') && /sav/.test(k)) || (at.includes('check') && /check/.test(k))) {
                    if (!e.checked) { e.click(); n++; }
                }
            }
        });
        return n;
    }"""

    # Find a Continue / Accept-style button (never Back / Decline / Cancel).
    # dryRun=true returns its text without clicking, so the caller can arm a
    # popup listener before the real click.
    _JS_CLICK_CONTINUE = r"""(dryRun) => {
        const vis = e => e.offsetParent !== null && e.getClientRects().length > 0;
        const t = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
        const go = /^(continue|next|accept|agree|submit|proceed|confirm|finish|get started|start here|start now|start|see my|see offers?|see if|view|view my|view offer|view details|get my|get offer|get started now|claim|redeem|show me|complete|i agree|apply now|apply|yes\b.*|accept.*offer|get.*offer|see.*offer)/i;
        const no = /(back|cancel|decline|no thanks|edit|previous|return to|log ?in|sign ?in|sign ?up|español|terms|disclosure|privacy|conditions)/i;
        const b = Array.from(document.querySelectorAll(
                'button,input[type=submit],input[type=button],[role=button],a.btn,a.button,a'))
            .filter(vis).filter(e => !e.disabled)
            .find(e => { const s = t(e); return s && s.length < 40 && go.test(s) && !no.test(s); });
        if (b) { if (!dryRun) b.click(); return t(b).slice(0, 40); }
        return '';
    }"""

    def _handle_post_offer(self, page: Page, f: dict, row_number: int, stop_event) -> None:
        """After the application is routed to the lender-match flow ("Thank you
        for your request / Connecting with our network of trusted lenders"), the
        site may ask for bank/routing details to finalise an offer, then present
        one or more Continue buttons.  Work through it: wait out the processing,
        fill the bank fields, click Continue, and repeat until it settles."""
        log.info("form.post_offer_start", row=row_number)
        self._screenshot(page, row_number, "post_offer_arrived")
        # account_type is parsed as a code ("1" checking / "2" savings) — map it
        # to a word so it can match the offer page's Checking/Savings controls.
        at_raw = str(f.get("account_type", "") or "").strip().lower()
        account_type_word = "savings" if at_raw in ("2", "savings", "sav", "s") else "checking"
        # Accept both key conventions: some sites use routing_number/account_number,
        # CashUSA (which borrows this handler) uses routing/account.
        bank_vals = {
            "routing_number": f.get("routing_number") or f.get("routing", ""),
            "account_number": f.get("account_number") or f.get("account", ""),
            "bank_name":      f.get("bank_name", "") or "",
            "account_type":   account_type_word,
        }
        ctx = page.context
        cur = page                          # current surface — may switch to an offer tab
        # Let the arriving offers page begin loading before we poll it.
        for state in ("domcontentloaded", "load"):
            try:
                cur.wait_for_load_state(state, timeout=15000)
            except Exception:
                pass

        def _find_cta():
            """First frame carrying a Continue/View/Start-Here CTA, and its text.
            Offer cards are frequently rendered inside ad iframes."""
            for fr in cur.frames:
                try:
                    if fr.is_detached():
                        continue
                    txt = fr.evaluate(self._JS_CLICK_CONTINUE, True) or ""
                except Exception:
                    txt = ""
                if txt:
                    return fr, txt
            return None, ""

        deadline = time.time() + 240        # a few minutes, per the on-screen note
        clicks = 0
        max_clicks = 6                      # safety cap for in-place Continue chains
        proc_logged = 0.0
        last_progress = time.time()
        last_click = None                   # (url, cta) — detects a no-op re-click
        while time.time() < deadline:
            self._check_stop(stop_event)
            try:
                self._live(cur)
            except Exception:
                pass
            try:
                st = cur.evaluate(self._JS_POST_STATE)
            except Exception:
                time.sleep(2)
                continue

            # 1) Fill any bank/routing fields the offer is asking for.
            filled = 0
            try:
                filled = cur.evaluate(self._JS_FILL_BANK, bank_vals) or 0
            except Exception:
                filled = 0
            if filled:
                log.info("form.post_offer_bank_filled", count=filled, row=row_number)
                self._screenshot(cur, row_number, "post_offer_bank")
                last_progress = time.time()
                time.sleep(1)

            # 2) A Continue / View / "Start Here!" CTA (searched across frames).
            cta_fr, cta = (_find_cta() if clicks < max_clicks else (None, ""))
            if cta_fr is not None:
                here = ((cur.url or ""), cta)
                if here == last_click:
                    # Same button on the same page as last time — the previous
                    # click didn't advance, so stop rather than spam it.
                    log.info("form.post_offer_no_progress", button=cta, row=row_number)
                    break
                last_click = here
                clicks += 1
                last_progress = time.time()
                log.info("form.post_offer_continue", button=cta, row=row_number)
                new_tab = None
                try:
                    with ctx.expect_page(timeout=8000) as pinfo:
                        cta_fr.evaluate(self._JS_CLICK_CONTINUE, False)   # actually click
                    new_tab = pinfo.value
                except Exception:
                    new_tab = None           # no popup — navigated in place
                if new_tab is not None:
                    # The offer opened in its own window ("results will open in a
                    # new window") — that's the destination.  Follow it, give it
                    # time to load (it's often an interstitial that then redirects
                    # to the lender), and STOP; do not drill into the advertiser's
                    # own application funnel.
                    cur = new_tab
                    log.info("form.post_offer_tab", url=(cur.url or "")[:80], row=row_number)
                    settle = float(self._delays.get("offer_load_wait", 6))
                    for state in ("domcontentloaded", "load", "networkidle"):
                        try:
                            cur.wait_for_load_state(state, timeout=20000)
                        except Exception:
                            pass
                    try:
                        cur.bring_to_front()
                    except Exception:
                        pass
                    time.sleep(settle)
                    # In case it redirected to the lender during the settle, wait
                    # for that page to load too before finishing.
                    for state in ("domcontentloaded", "networkidle"):
                        try:
                            cur.wait_for_load_state(state, timeout=15000)
                        except Exception:
                            pass
                    log.info("form.post_offer_loaded", url=(cur.url or "")[:80], row=row_number)
                    break
                # In-place navigation (a Continue/Submit on the aggregator) —
                # wait for it and keep going through the flow.
                for state in ("domcontentloaded", "load"):
                    try:
                        cur.wait_for_load_state(state, timeout=15000)
                    except Exception:
                        pass
                time.sleep(2)
                continue

            # 3) No CTA yet.  If the offers page is still searching / connecting
            #    ("Searching for the best offers…"), keep waiting for the cards.
            if st.get("processing"):
                if time.time() - proc_logged > 15:
                    log.info("form.post_offer_processing", row=row_number)
                    proc_logged = time.time()
                time.sleep(3)
                continue

            # 4) Not processing and nothing to click — give ad-loaded cards time
            #    to render, then finish if still nothing after a while.
            if not filled and time.time() - last_progress > 45:
                break
            time.sleep(2)

        self._screenshot(cur, row_number, "post_offer_final")
        log.info("form.post_offer_done", clicks=clicks, row=row_number)

    def _classify_error(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "crash" in msg:
            return "browser_crashed"
        if "proxy" in msg or "net::err" in msg or "tunnel" in msg:
            return "proxy_error"
        if "closed" in msg or "target page" in msg:
            return "browser_closed"
        if "timeout" in msg:
            return "timeout"
        if self._is_nav_error(exc):
            return "navigated"
        return "unknown"

    def _clean_fingerprint(self, fp: dict) -> dict:
        allowed = {
            "user_agent", "viewport", "locale", "timezone_id",
            "geolocation", "color_scheme", "device_scale_factor",
            "is_mobile", "has_touch", "java_script_enabled",
            "extra_http_headers",
        }
        return {k: v for k, v in fp.items() if k in allowed and v is not None}
