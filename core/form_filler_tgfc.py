"""
core/form_filler_tgfc.py — togetfastcash.com React hash-wizard automation.

Unlike Bootstrap wizard sites, TGFC runs a React funnel whose
step is driven by ``location.hash`` (#loanAmount, #email, …, #finish).  Each
step shows either a text input, a set of choice buttons, or both.

Completion lands on ``#finish`` where invisible reCAPTCHA v3 fires before POST.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import structlog
from playwright.sync_api import Page

from core.lead_platform import BasePlatformFiller, FormFillerError, _digits, _ssn_format

log = structlog.get_logger(__name__)

_WIZARD = "#f-wizard-form"
_NEXT_RE = re.compile(r"next|continue|submit|agree|request|get cash|finish", re.I)

__all__ = ["FormFiller", "FormFillerError"]

# Loan-amount buttons on the landing page (values in dollars).
_LOAN_BUCKETS = [(500, "500"), (1000, "1,000"), (2500, "2,500"), (5000, "5,000"), (35000, "35,000")]

# Hash step -> actual input name(s) on the live React wizard (hash != name).
_STEP_FIELDS: dict[str, list[str]] = {
    "email": ["email"],
    "ssnFC": ["ssnFC", "ssnEC", "ssn"],
    "ssnEC": ["ssnEC", "ssnFC"],
    "lastName": ["firstName", "lastName"],
    "homePhone": ["phone", "homePhone", "telephone"],
    "address": ["address"],
    "state": ["zip", "city", "state"],
    "residenceMonths": [],
    "dobY": ["dobM", "dobD", "dobY"],
    "incomeNextDate": ["incomeNextDate"],
    "incomeNetMonthly": ["incomeNetMonthly"],
    "employerName": ["employerName"],
    "driverLicense": ["driverLicense"],
    "driverLicenseState": ["driverLicenseState"],
    "ssn": ["ssn"],
    "bankRoutingNumber": ["bankRoutingNumber"],
    "bankAccountNumber": ["bankAccountNumber"],
}

# Fields that use input masks — type digit-by-digit instead of bulk fill.
# NOTE: bankAccountNumber is a React controlled text/number field — use React
# onChange (not key-mask typing) or NEXT validation keeps an empty closed-over value.
_MASKED_FIELDS = frozenset({
    "phone", "homePhone", "telephone", "ssn", "ssnEC", "ssnFC", "ssnV1", "zip",
    "dobM", "dobD", "dobY", "incomeNextDate", "bankRoutingNumber",
})

_TGFC_TENURE = {"12": "12", "24": "24", "36": "36", "48": "48", "60": "60"}


class FormFiller(BasePlatformFiller):
    """togetfastcash.com — React hash-wizard."""

    default_url = "https://togetfastcash.com/"

    def _parse_fields(self, row: dict) -> dict:
        f = super()._parse_fields(row)
        # TGFC phone: (XXX)XXX-XXXX — no space after closing paren.
        phone = _digits(f.get("phone", "").replace("(", "").replace(")", "").replace(" ", "").replace("-", ""))
        if len(phone) == 10:
            f["tgfc_phone"] = f"({phone[:3]}){phone[3:6]}-{phone[6:]}"
        else:
            f["tgfc_phone"] = ""

        dob = f.get("dob", "")
        if dob and re.match(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}$", dob):
            parts = dob.split("/")
            # Dropdown options are 1..12 / 1..31 — never send "08".
            f["dob_m"] = str(int(parts[0]))
            f["dob_d"] = str(int(parts[1]))
            f["dob_y"] = parts[2]
        else:
            f["dob_m"] = f["dob_d"] = f["dob_y"] = ""

        # Next pay date — TGFC-only column; default ~2 weeks out.
        _norm = {re.sub(r"\s+", " ", str(k)).strip().lower(): str(v or "").strip()
                 for k, v in row.items()}
        next_pay = ""
        for key in ("next pay date", "income next date", "pay date"):
            next_pay = _norm.get(key, "")
            if next_pay:
                break
        if not next_pay:
            next_pay = (datetime.now() + timedelta(days=14)).strftime("%m/%d/%Y")
        else:
            next_pay = self._normalize_dob(next_pay) or next_pay
        f["next_pay_date"] = self._future_pay_date(next_pay)

        f["tgfc_loan_amount"] = str(f.get("loan_amount", 5000))
        f["tgfc_residence_months"] = _TGFC_TENURE.get(f.get("address_months", "60"), "60")
        f["tgfc_employed_months"] = _TGFC_TENURE.get(f.get("employer_months", "60"), "60")
        f["tgfc_bank_months"] = _TGFC_TENURE.get(f.get("bank_months", "60"), "60")
        f["tgfc_income"] = str(f.get("loan_amount", 3000))  # overwritten below
        income_raw = re.sub(r"[,$\s]", "", str(row.get("Monthly Net Income ($)", "") or row.get("Monthly Net Income", "") or "3000"))
        try:
            f["tgfc_income"] = str(int(float(income_raw or "3000")))
        except (ValueError, TypeError):
            f["tgfc_income"] = "3000"

        f["tgfc_debt"] = self._debt_bracket(str(row.get("Credit Card Debt", "") or row.get("Credit Card Debt ($)", "") or "0"))
        # Keep raw dollars for TGFC debt buttons (No Debt / $7,500+ ranges).
        debt_raw = re.sub(r"[,$\s]", "", str(row.get("Credit Card Debt", "") or "0"))
        try:
            f["tgfc_debt_amount"] = int(float(debt_raw or 0))
        except (ValueError, TypeError):
            f["tgfc_debt_amount"] = 0 if str(f["tgfc_debt"]) == "0" else 8000
        f["tgfc_credit"] = self._tgfc_credit(f.get("credit_score", "1"))
        f["tgfc_loan_purpose"] = self._tgfc_loan_purpose(f.get("loan_reason", "13"))
        f["tgfc_income_source"] = "Employment" if f.get("income_source") == "1" else "Benefits"
        f["tgfc_pay_freq"] = self._tgfc_pay_freq(f.get("pay_freq", "2"))
        f["tgfc_homeowner"] = "Own" if f.get("is_homeowner") == "1" else "Rent"
        f["tgfc_military"] = "Yes" if f.get("is_military") == "1" else "No"
        f["tgfc_account_type"] = "Checking" if f.get("account_type") == "1" else "Savings"
        f["tgfc_direct_deposit"] = "Yes" if f.get("is_direct_deposit") == "1" else "No"
        return f

    def _validate_required_fields(self, f: dict) -> None:
        super()._validate_required_fields(f)
        if f.get("tgfc_phone") and not re.match(
            r"^\([2-9]\d{2}\)\d{3}-\d{4}$", f["tgfc_phone"]
        ):
            raise FormFillerError(
                "phone(invalid TGFC format — need (XXX)XXX-XXXX)",
                error_type="missing_data",
            )

    # ---------------------------------------------------------------- fill loop

    def _fill_form(self, page: Page, f: dict, row_number: int, stop_event) -> str:
        self._wait_wizard(page, row_number)
        seen: dict[str, int] = {}
        self._bank_advanced = False
        self._finish_popup = None
        self._finish_clicked = False
        # Prior runs leave localStorage._fd — clear so completion detect is fresh.
        try:
            page.evaluate(
                """() => {
                  try { localStorage.removeItem('_fd'); } catch (e) {}
                  window.__tgfc_submitted = false;
                  const form = document.applyForm || document.querySelector('form[name=applyForm], form#applyForm');
                  if (form && !form.__tgfcHooked) {
                    form.__tgfcHooked = true;
                    form.addEventListener('submit', () => { window.__tgfc_submitted = true; });
                  }
                }"""
            )
        except Exception:
            pass

        progressed = False
        for step_num in range(self._max_steps):
            self._check_stop(stop_event)
            self._live(page)

            # Visual only after we have filled a step — never treat marketing
            # copy or localStorage._fd as done before the CTA popup.
            try:
                if progressed or self._current_step(page) == "finish":
                    outcome = self._completion_state(page, require_visual=True)
                    if outcome:
                        return outcome
            except Exception as exc:
                if not self._is_nav_error(exc):
                    raise
                time.sleep(1.0)
                continue

            step = self._current_step(page)
            if not step:
                time.sleep(1.0)
                continue

            dup = self._handle_duplicate_identity(page, f, row_number, step)
            if dup == "verified":
                progressed = True
                try:
                    self._click_next(page)
                    self._await_step_change(page, step, timeout=6)
                except Exception as exc:
                    if not self._is_nav_error(exc):
                        raise
                continue
            if dup == "new_form":
                progressed = True
                continue

            seen[step] = seen.get(step, 0) + 1
            limit = 6 if step in ("bankAccountNumber", "bankRoutingNumber", "ssn", "ssnFC", "ssnEC", "incomeNextDate") else 4
            if seen[step] > limit:
                self._screenshot(page, row_number, f"stuck_{step}")
                raise FormFillerError(
                    f"Form stopped advancing at step '{step}'",
                    error_type="stuck",
                )

            log.info("form.step", step=step_num, hash=step, row=row_number)
            self._read_pause()
            try:
                handled = self._handle_step(page, step, f)
            except Exception as exc:
                if self._is_nav_error(exc):
                    progressed = True
                    continue
                raise
            progressed = True
            if not handled:
                if step.lower() in ("ssnfc", "ssnec", "welcomeback") or self._is_duplicate_identity_screen(page):
                    log.warning("form.dup_continue", step=step, row=row_number)
                    self._click_start_new_form(page)
                    time.sleep(1.0)
                    continue
                self._screenshot(page, row_number, f"unhandled_{step}")
                raise FormFillerError(
                    f"Could not fill step '{step}' — field rejected or not found",
                    error_type="field_rejected",
                )

            self._action_pause()
            if step == "finish":
                self._submit_finish(page, row_number)
                outcome = self._wait_completion(page, row_number, stop_event)
                return outcome or "submitted (finish)"

            # Choice / loan-amount steps often auto-advance on click.
            if step in ("loanAmount", "isMilitary", "isHomeOwner", "incomeSource",
                        "incomeFrequency", "payType", "bankAccountType", "loanPurpose",
                        "debt", "residenceMonths", "employedMonths", "bankMonths",
                        "incomeNextDate", "incomeNetMonthly"):
                if self._await_step_change(page, step, timeout=4):
                    self._live(page)
                    continue

            # Bank is the last data step: live site often auto-submits to finish
            # (goToNextStep → _submitForm) WITHOUT changing hash to #finish.
            if step == "bankAccountNumber":
                outcome = self._await_bank_exit(page, row_number, stop_event)
                if outcome:
                    return outcome
                # Landed on #finish consent CTA instead of silent submit.
                if self._current_step(page) == "finish":
                    continue
                # Fall through to a normal NEXT if still on bank.
                if getattr(self, "_bank_advanced", False):
                    self._bank_advanced = False

            self._click_next(page)
            if step == "bankAccountNumber":
                outcome = self._await_bank_exit(page, row_number, stop_event)
                if outcome:
                    return outcome
            else:
                self._await_step_change(page, step)
            self._live(page)

        raise FormFillerError(
            f"Form did not complete within {self._max_steps} steps",
            error_type="timeout",
        )

    # ------------------------------------------------------------- step handlers

    def _handle_step(self, page: Page, step: str, f: dict) -> bool:
        handlers: dict[str, Callable[[], bool]] = {
            "loanAmount":     lambda: self._pick_loan_amount(page, f),
            "email":          lambda: self._fill_email_maybe_dup(page, f),
            "ssnFC":          lambda: self._handle_duplicate_identity(page, f, 0, step)
                                      or self._fill_step_fields(page, step, f),
            "ssnEC":          lambda: self._fill_step_fields(page, step, f),
            "lastName":       lambda: self._fill_step_fields(page, step, f),
            "homePhone":      lambda: self._fill_step_fields(page, step, f),
            "isMilitary":     lambda: self._pick_choice(page, f["tgfc_military"]),
            "address":        lambda: self._fill_step_fields(page, step, f),
            "state":          lambda: self._fill_location_step(page, f),
            "residenceMonths": lambda: self._pick_tenure(page, f["tgfc_residence_months"]),
            "isHomeOwner":    lambda: self._pick_choice(page, f["tgfc_homeowner"]),
            "dobY":           lambda: self._fill_dob_selects(page, f),
            "incomeSource":   lambda: self._pick_choice(page, f["tgfc_income_source"]),
            "employedMonths": lambda: self._pick_tenure(page, f["tgfc_employed_months"]),
            "incomeFrequency": lambda: self._pick_choice(page, f["tgfc_pay_freq"]),
            "incomeNextDate": lambda: self._pick_next_pay_date(page, f),
            "incomeNetMonthly": lambda: self._pick_income_bracket(page, f),
            "employerName":   lambda: self._fill_step_fields(page, step, f),
            "driverLicense":  lambda: self._fill_step_fields(page, step, f),
            "driverLicenseState": lambda: self._fill_state_select(page, f["dl_state"]),
            "ssn":            lambda: self._fill_ssn(page, f),
            "loanPurpose":    lambda: self._fill_credit_and_purpose(page, f),
            "debt":           lambda: self._pick_debt(page, f),
            "payType":        lambda: self._pick_choice(page, f["tgfc_direct_deposit"]),
            "bankMonths":     lambda: self._pick_tenure(page, f["tgfc_bank_months"]),
            "bankAccountType": lambda: self._pick_choice(page, f["tgfc_account_type"]),
            "bankRoutingNumber": lambda: self._fill_bank_step(page, f),
            "bankAccountNumber": lambda: self._fill_bank_step(page, f),
            "welcomeBack":    lambda: self._click_next(page) or True,
            "finish":         lambda: True,
        }
        fn = handlers.get(step)
        if fn is None:
            return self._fill_visible_inputs(page, step, f)
        return fn()

    # ----------------------------------------------------------- TGFC value maps

    @staticmethod
    def _tgfc_credit(aef_code: str) -> str:
        return {"2": "Excellent", "3": "Good", "4": "Fair", "5": "Poor"}.get(aef_code, "Not Sure")

    @staticmethod
    def _tgfc_loan_purpose(aef_code: str) -> str:
        return {
            "14": "Debt Consolidation",
            "1": "Debt Consolidation",
        }.get(aef_code, "Emergency Situation")

    @staticmethod
    def _tgfc_pay_freq(aef_code: str) -> str:
        return {"1": "Weekly", "2": "Bi-Weekly", "4": "Semi-Monthly", "3": "Monthly"}.get(aef_code, "Bi-Weekly")

    # ----------------------------------------------------------- interactions

    def _wait_wizard(self, page: Page, row_number: int) -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            if page.locator(_WIZARD).count() or page.locator("input[name='email']").count():
                return
            # Still on loan-amount landing — click through if hash is #loanAmount.
            if self._current_step(page) == "loanAmount":
                return
            time.sleep(0.5)
        self._screenshot(page, row_number, "no_wizard")
        raise FormFillerError("Wizard form never rendered", error_type="stuck")

    def _current_step(self, page: Page) -> str:
        try:
            h = page.evaluate("() => (location.hash || '').replace(/^#/, '')") or ""
            return h.strip()
        except Exception:
            return ""

    def _visible_inputs(self, page: Page) -> list[dict[str, str]]:
        try:
            return page.evaluate(
                """() => {
                    const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    return Array.from(document.querySelectorAll('input,select,textarea'))
                        .filter(e => vis(e) && e.type !== 'hidden')
                        .map(e => ({ name: e.name || e.id || '', type: e.type || '', tag: e.tagName }));
                }"""
            ) or []
        except Exception:
            return []

    def _field_value_for(self, field_name: str, f: dict) -> str:
        """Map a DOM input name to the value from the parsed lead dict."""
        mapping = {
            "email": f.get("email", ""),
            "ssnEC": f.get("last_ssn", "") or (f.get("ssn", "")[-4:]),
            "ssnFC": f.get("last_ssn", "") or (f.get("ssn", "")[-4:]),
            "ssnV1": f.get("last_ssn", "") or (f.get("ssn", "")[-4:]),
            "firstName": f.get("first_name", ""),
            "lastName": f.get("last_name", ""),
            "phone": _digits(f.get("tgfc_phone", "") or f.get("phone", "")),
            "homePhone": _digits(f.get("tgfc_phone", "") or f.get("phone", "")),
            "telephone": _digits(f.get("tgfc_phone", "") or f.get("phone", "")),
            "address": f.get("street_address", ""),
            "zip": f.get("zip", ""),
            "city": f.get("city", ""),
            "state": f.get("state", ""),
            "dobM": f.get("dob_m", ""),
            "dobD": f.get("dob_d", ""),
            "dobY": f.get("dob_y", ""),
            "incomeNextDate": f.get("next_pay_date", ""),
            "incomeNetMonthly": f.get("tgfc_income", ""),
            "employerName": f.get("employer_name", ""),
            "driverLicense": f.get("dl_number", ""),
            "driverLicenseState": f.get("dl_state", ""),
            "ssn": f.get("ssn", ""),
            "bankRoutingNumber": f.get("routing_number", ""),
            "bankAccountNumber": f.get("account_number", ""),
            "bankName": f.get("bank_name", "") or "Chase",
        }
        return str(mapping.get(field_name, ""))

    def _fill_ssn(self, page: Page, f: dict) -> bool:
        """SSN mask is ___-__-____ — push digits into React state, not just the DOM."""
        ssn = _digits(f.get("ssn", ""))
        if len(ssn) != 9:
            return False
        area = int(ssn[:3])
        if area in (0, 666) or area >= 900:
            log.warning("form.ssn_invalid_area", prefix=ssn[:3], row_hint="site may reject 000/666/900-999")
        formatted = _ssn_format(ssn)

        loc = page.locator('input[name="ssn"]').first
        try:
            loc.wait_for(state="visible", timeout=6000)
            loc.click()
            loc.fill("")
            loc.press_sequentially(ssn, delay=max(70, int(self._key_delay())))
        except Exception:
            pass

        self._react_set_input(page, "ssn", formatted)
        got = ""
        try:
            got = loc.input_value(timeout=2000) if loc.count() else ""
        except Exception:
            got = ""
        if len(_digits(got)) < 9:
            self._text_wizard(page, "ssn", ssn)
            try:
                got = loc.input_value(timeout=2000) if loc.count() else ""
            except Exception:
                got = ""
            self._react_set_input(page, "ssn", formatted if "-" not in (got or "") else got)

        log.info("form.ssn_filled", value=got, digits=len(_digits(got)))
        print(f"[TGFC SSN] value={got!r} digits={len(_digits(got))}", flush=True)
        return len(_digits(got)) >= 9

    def _fill_bank_step(self, page: Page, f: dict) -> bool:
        """Routing / account — never overwrite ABA-resolved bankName."""
        step = self._current_step(page)
        filled = False

        if step == "bankRoutingNumber":
            routing = f.get("routing_number", "")
            if routing and self._text_wizard(page, "bankRoutingNumber", str(routing)):
                filled = True
                self._field_pause()
            # Wait for ABA → bankName autofill before leaving this step.
            try:
                page.wait_for_function(
                    """() => {
                      const el = document.querySelector('input[name="bankName"]');
                      return el && (el.value || '').trim().length > 2;
                    }""",
                    timeout=10000,
                )
            except Exception:
                pass
            try:
                bn = page.locator('input[name="bankName"]').first
                if bn.count() and bn.is_visible():
                    cur = (bn.input_value(timeout=1000) or "").strip()
                    if not cur:
                        name = f.get("bank_name", "") or "Chase"
                        if self._text_wizard(page, "bankName", name):
                            filled = True
            except Exception:
                pass

        elif step == "bankAccountNumber":
            # Do NOT overwrite ABA-resolved bankName (e.g. "JPMORGAN CHASE BANK").
            #
            # Live site quirk: bank NEXT when next-hash is "finish" calls _submitForm
            # (native applyForm) and SKIPS the Finish UI — so the processing popup never
            # shows. For a real popup we must: merge bank into React form → #finish →
            # click "Submit Loan Request" (onSubmit → processingModal.show()).
            acct = _digits(f.get("account_number", ""))
            bank = ""
            try:
                bn = page.locator('input[name="bankName"]').first
                if bn.count() and bn.is_visible():
                    bank = (bn.input_value(timeout=1500) or "").strip()
            except Exception:
                pass
            if not bank:
                bank = (f.get("bank_name") or "").strip() or "JPMORGAN CHASE BANK"
                self._react_set_input(page, "bankName", bank)

            if not acct or len(acct) < 6:
                return False

            loc = page.locator('input[name="bankAccountNumber"]').first
            try:
                loc.wait_for(state="visible", timeout=6000)
                loc.click()
                loc.fill("")
                loc.press_sequentially(acct, delay=max(50, int(self._key_delay())))
            except Exception:
                pass
            self._react_set_input(page, "bankAccountNumber", acct)
            try:
                if loc.count():
                    got = _digits(loc.input_value(timeout=1500) or "")
                    if got != acct:
                        loc.fill(acct)
                        self._react_set_input(page, "bankAccountNumber", acct)
            except Exception:
                pass

            time.sleep(0.4)
            opened = self._open_finish_for_popup(page, bank, acct)
            self._bank_advanced = bool(opened)
            return True
        else:
            # Generic fallback for unexpected bank hashes.
            for name, val in (
                ("bankRoutingNumber", f.get("routing_number", "")),
                ("bankAccountNumber", f.get("account_number", "")),
            ):
                if val and page.locator(f'input[name="{name}"]').count():
                    if self._text_wizard(page, name, str(val)):
                        filled = True

        time.sleep(0.5)
        try:
            page.wait_for_function(
                """() => {
                  const vis = e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
                  const btn = Array.from(document.querySelectorAll('button')).find(b =>
                    vis(b) && /next|continue/i.test((b.innerText||'').trim())
                  );
                  return btn && !btn.disabled;
                }""",
                timeout=5000,
            )
        except Exception:
            pass
        return filled

    def _fill_step_fields(self, page: Page, step: str, f: dict) -> bool:
        """Fill all inputs for a hash step using the live DOM field names."""
        names = _STEP_FIELDS.get(step, [step])
        filled = False
        for i, name in enumerate(names):
            val = self._field_value_for(name, f)
            if not val:
                continue
            if i > 0:
                self._field_pause()
            if self._text_wizard(page, name, val):
                filled = True
        return filled

    def _text_wizard(self, page: Page, name: str, value: str) -> bool:
        value = str(value or "")
        if not value:
            return False
        masked = name in _MASKED_FIELDS
        selectors = [
            f'{_WIZARD} input[name="{name}"]',
            f'{_WIZARD} textarea[name="{name}"]',
            f'{_WIZARD} select[name="{name}"]',
            f'input[name="{name}"]',
            f'textarea[name="{name}"]',
            f'select[name="{name}"]',
            f'#{name}',
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() == 0:
                    continue
                loc.wait_for(state="visible", timeout=6000)
                tag = loc.evaluate("el => el.tagName")
                if tag == "SELECT":
                    loc.select_option(value=value, timeout=5000)
                    return True
                loc.click()
                loc.fill("")
                if masked:
                    # Masked React inputs need keystrokes, not bulk fill.
                    digits = _digits(value) if name in ("phone", "homePhone", "telephone", "ssn", "ssnEC", "ssnFC", "ssnV1", "bankRoutingNumber", "bankAccountNumber") else value
                    loc.press_sequentially(digits, delay=max(60, int(self._key_delay())))
                else:
                    loc.press_sequentially(value, delay=self._key_delay())
                got = loc.input_value(timeout=2000)
                if _digits(got) == _digits(value) or got.strip() == value.strip():
                    return True
                page.evaluate(
                    """([sel, v]) => {
                        const el = document.querySelector(sel);
                        if (!el) return;
                        const proto = el instanceof HTMLTextAreaElement
                            ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }""",
                    [sel, value],
                )
                got = loc.input_value(timeout=2000)
                if _digits(got) == _digits(value) or got.strip() == value.strip():
                    return True
            except Exception:
                continue
        return False

    def _fill_name_step(self, page: Page, f: dict) -> bool:
        return self._fill_step_fields(page, "lastName", f)

    def _select_matching(self, page: Page, index: int, wanted: str) -> str | None:
        """Set visible select ``index`` to a padded or unpadded option; return the value used."""
        candidates = []
        raw = str(wanted or "").strip()
        if raw:
            # Live wizard options are 1..31 / 1..12 — "08" is not a valid value.
            if raw.isdigit():
                candidates.append(str(int(raw)))
                candidates.append(raw.zfill(2))
            candidates.append(raw)
        result = page.evaluate(
            """([idx, cands]) => {
                const sels = Array.from(document.querySelectorAll('select'))
                  .filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length));
                const el = sels[idx];
                if (!el) return null;
                const opts = Array.from(el.options);
                let opt = null;
                for (const c of cands) {
                  opt = opts.find(o => o.value === c || (o.text || '').trim() === c);
                  if (opt) break;
                }
                if (!opt) {
                  const n = parseInt(cands[0], 10);
                  if (!Number.isNaN(n)) {
                    opt = opts.find(o => parseInt(o.value, 10) === n || parseInt((o.text||'').trim(), 10) === n);
                  }
                }
                if (!opt) return null;
                const last = el.value;
                el.selectedIndex = opt.index;
                opt.selected = true;
                el.value = opt.value;
                if (el._valueTracker) el._valueTracker.setValue(last === opt.value ? last + ' ' : last);
                const evt = {
                  target: el, currentTarget: el, preventDefault() {}, stopPropagation() {},
                  bubbles: true, type: 'change',
                };
                const fiberKey = Object.keys(el).find(
                  k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                );
                let fiber = fiberKey ? el[fiberKey] : null;
                for (let i = 0; i < 12 && fiber; i++, fiber = fiber.return) {
                  const props = fiber.memoizedProps || {};
                  if (typeof props.onChange === 'function') {
                    try { props.onChange(evt); } catch (e) {}
                  }
                }
                const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
                if (propsKey && el[propsKey] && typeof el[propsKey].onChange === 'function') {
                  try { el[propsKey].onChange(evt); } catch (e) {}
                }
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return el.value || opt.value;
            }""",
            [index, candidates],
        )
        return result or None

    def _fill_dob_selects(self, page: Page, f: dict) -> bool:
        """#dobY uses three nameless <select>s: month, day, year."""
        m, d, y = f.get("dob_m", ""), f.get("dob_d", ""), f.get("dob_y", "")
        if not (m and d and y):
            return False
        try:
            visible = []
            for i in range(page.locator("select").count()):
                s = page.locator("select").nth(i)
                try:
                    if s.is_visible():
                        visible.append(s)
                except Exception:
                    pass
            if len(visible) < 3:
                return False

            month_got = self._select_matching(page, 0, m)
            self._field_pause()
            deadline = time.time() + 5
            day_got = None
            while time.time() < deadline:
                day_got = self._select_matching(page, 1, d)
                if day_got:
                    break
                time.sleep(0.3)
            self._field_pause()
            year_got = self._select_matching(page, 2, y)
            log.info("form.dob_set", month=month_got, day=day_got, year=year_got)
            print(f"[TGFC DOB] month={month_got} day={day_got} year={year_got}", flush=True)
            return bool(month_got and day_got and year_got)
        except Exception as exc:
            log.warning("form.dob_failed", error=str(exc)[:90])
            return False

    def _fill_dob(self, page: Page, f: dict) -> bool:
        return self._fill_dob_selects(page, f)

    def _pick_loan_amount(self, page: Page, f: dict) -> bool:
        amount = int(f.get("loan_amount", 5000))
        label = "35,000"
        for cap, lbl in _LOAN_BUCKETS:
            if amount <= cap:
                label = lbl
                break
        return self._click_button_text(page, label)

    def _pick_choice(self, page: Page, label: str) -> bool:
        if not label:
            return False
        # Exact-ish first, then includes (handles "Employment ›", "5 Years or more ›")
        if self._click_button_text(page, label):
            return True
        try:
            return bool(page.evaluate(
                """(want) => {
                    const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    const w = want.toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('button,label,[role=button],.f-option'));
                    let best = null;
                    for (const n of nodes) {
                        if (!vis(n)) continue;
                        const t = (n.innerText || n.textContent || '').replace(/\\s+/g,' ').trim();
                        const tl = t.toLowerCase();
                        if (tl === w || tl.startsWith(w) || tl.includes(w)) {
                            best = n;
                            if (tl.startsWith(w)) break;
                        }
                    }
                    if (best) { best.click(); return true; }
                    return false;
                }""",
                label,
            ))
        except Exception:
            return False

    def _fill_location_step(self, page: Page, f: dict) -> bool:
        """#state step is ZIP + City + State select (select often has no name)."""
        ok = False
        if self._text_wizard(page, "zip", f.get("zip", "")):
            ok = True
            self._field_pause()
        if self._text_wizard(page, "city", f.get("city", "")):
            ok = True
            self._field_pause()
        if self._fill_state_select(page, f.get("state", "")):
            ok = True
        return ok

    def _fill_state_select(self, page: Page, state: str) -> bool:
        """Select a US state — live TGFC select often has empty name attribute."""
        if not state:
            return False
        state = state.upper()[:2]
        # Prefer named selects, then any visible select with state options.
        selectors = [
            f'{_WIZARD} select[name="state"]',
            f'{_WIZARD} select[name="driverLicenseState"]',
            'select[name="state"]',
            'select[name="driverLicenseState"]',
            f'{_WIZARD} select',
            "select",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() == 0:
                    continue
                loc.wait_for(state="visible", timeout=4000)
                # Confirm it looks like a state dropdown.
                opts = loc.evaluate(
                    "el => Array.from(el.options).slice(0,5).map(o => o.value)"
                ) or []
                if sel.endswith("select") and "AL" not in opts and state not in opts:
                    # nameless generic select — still try if it has two-letter codes
                    if not any(len(str(o)) == 2 for o in opts if o):
                        continue
                loc.select_option(value=state, timeout=5000)
                # Fire React change events
                page.evaluate(
                    """([sel, v]) => {
                        const el = document.querySelector(sel) || Array.from(document.querySelectorAll('select')).find(s => s.offsetParent);
                        if (!el) return;
                        el.value = v;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    [sel if "name=" in sel else "select", state],
                )
                return True
            except Exception:
                continue
        # Fallback: click option text / button labelled with state code
        return self._click_button_text(page, state) or self._pick_choice(page, state)

    def _pick_state(self, page: Page, state: str) -> bool:
        return self._fill_state_select(page, state)

    def _pick_tenure(self, page: Page, months: str) -> bool:
        # Live labels: "1 Year or less ›", "2 Years ›", …, "5 Years or more ›"
        labels = {
            "60": "5 Years",
            "48": "4 Years",
            "36": "3 Years",
            "24": "2 Years",
            "12": "1 Year",
        }
        return self._pick_choice(page, labels.get(months, "5 Years"))

    def _pick_income_bracket(self, page: Page, f: dict) -> bool:
        """Monthly Gross Income choice buttons on live TGFC."""
        try:
            income = int(float(f.get("tgfc_income") or 3000))
        except (ValueError, TypeError):
            income = 3000
        if income < 1500:
            label = "Less than $1500"
        elif income < 2000:
            label = "$1500 - $2000"
        elif income < 2500:
            label = "$2000 - $2500"
        elif income < 3000:
            label = "$2500 - $3000"
        elif income < 3500:
            label = "$3000 - $3500"
        elif income < 4000:
            label = "$3500 - $4000"
        elif income < 5000:
            label = "$4000 - $5000"
        else:
            label = "$5000 or more"
        return self._pick_choice(page, label)

    def _fill_credit_and_purpose(self, page: Page, f: dict) -> bool:
        """#loanPurpose shows two nameless selects: credit score + loan purpose."""
        credit = f.get("tgfc_credit") or "Good"
        purpose = f.get("tgfc_loan_purpose") or "Other"
        visible = []
        for i in range(page.locator("select").count()):
            sel = page.locator("select").nth(i)
            try:
                if sel.is_visible():
                    visible.append(sel)
            except Exception:
                pass
        if len(visible) < 2:
            # Fallback to choice buttons if present
            return self._pick_choice(page, credit) and self._pick_choice(page, purpose)

        def _select_by_label(sel, want: str) -> bool:
            want_l = want.lower()
            try:
                opts = sel.evaluate(
                    "el => Array.from(el.options).map(o => ({v:o.value, t:o.textContent.trim()}))"
                ) or []
                hit = None
                for o in opts:
                    t = (o.get("t") or "").lower()
                    v = (o.get("v") or "").lower()
                    if want_l == t or want_l in t or want_l == v:
                        hit = o["v"]
                        break
                if hit is None:
                    # skip empty first option
                    for o in opts:
                        if o.get("v"):
                            hit = o["v"]
                            break
                if hit is None:
                    return False
                sel.select_option(value=str(hit), timeout=4000)
                page.evaluate(
                    """([idx, v]) => {
                      const sels = Array.from(document.querySelectorAll('select')).filter(e => e.offsetParent);
                      const el = sels[idx];
                      if (!el) return;
                      el.value = v;
                      el.dispatchEvent(new Event('input', {bubbles:true}));
                      el.dispatchEvent(new Event('change', {bubbles:true}));
                    }""",
                    [visible.index(sel) if sel in visible else 0, str(hit)],
                )
                return True
            except Exception:
                return False

        ok1 = _select_by_label(visible[0], credit)
        self._field_pause()
        ok2 = _select_by_label(visible[1], purpose)
        return ok1 or ok2

    def _pick_loan_purpose(self, page: Page, f: dict) -> bool:
        return self._fill_credit_and_purpose(page, f)

    def _pick_debt(self, page: Page, f: dict) -> bool:
        """Live TGFC debt brackets: No Debt, then $7,500+ ranges."""
        try:
            amount = int(f.get("tgfc_debt_amount", 0) or 0)
        except (ValueError, TypeError):
            amount = 0
        if amount < 7500:
            label = "No Debt"
        elif amount < 10000:
            label = "$7,500 - $10,000"
        elif amount < 15000:
            label = "$10,000 - $15,000"
        elif amount < 20000:
            label = "$15,000 - $20,000"
        elif amount < 35000:
            label = "$20,000 - $35,000"
        else:
            label = "$35,000 or more"
        if self._pick_choice(page, label):
            return True
        # Yes/No debt-relief interstitial
        if self._pick_choice(page, "No") or self._pick_choice(page, "Yes"):
            return True
        return self._pick_choice(page, "No Debt")

    def _fill_visible_inputs(self, page: Page, step: str, f: dict) -> bool:
        names = _STEP_FIELDS.get(step, [step])
        for name in names:
            val = self._field_value_for(name, f)
            if val and self._text_wizard(page, name, val):
                return True
        for inp in self._visible_inputs(page):
            n = inp.get("name", "")
            if n:
                val = self._field_value_for(n, f)
                if val and self._text_wizard(page, n, val):
                    return True
        if "ssn" in (step or "").lower():
            return False
        return bool(self._visible_inputs(page))

    def _click_button_text(self, page: Page, fragment: str) -> bool:
        if not fragment:
            return False
        try:
            return bool(page.evaluate(
                """(frag) => {
                    const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    const want = frag.toLowerCase();
                    const btns = Array.from(document.querySelectorAll('button,input[type=submit],a'));
                    for (const b of btns) {
                        if (!vis(b)) continue;
                        const t = (b.innerText || b.value || '').replace(/\\s+/g,' ').trim();
                        if (t.toLowerCase().includes(want)) { b.click(); return true; }
                    }
                    return false;
                }""",
                fragment,
            ))
        except Exception:
            return False

    def _click_next(self, page: Page) -> bool:
        """Advance wizard.

        Most steps accept a normal Playwright click. The finish CTA and a few
        late steps need React onClick — try both.
        """
        for sel in (
            f"{_WIZARD} button.f-wizard-step--buttons--next",
            "button.f-wizard-step--buttons--next",
        ):
            loc = page.locator(sel).first
            try:
                if loc.count() == 0 or not loc.is_visible():
                    continue
                label = (loc.inner_text(timeout=1000) or "").strip()[:40] or "NEXT"
                # Prefer React handler when CTA is Submit Loan Request.
                if "submit" in label.lower():
                    if getattr(self, "_finish_clicked", False):
                        log.debug("form.next", label=label, via="already-submitted")
                        return True
                    if self._react_click(page, sel, once=True):
                        self._finish_clicked = True
                        log.debug("form.next", label=label, via="react")
                        return True
                try:
                    loc.click(timeout=5000)
                    log.debug("form.next", label=label, via="playwright")
                    return True
                except Exception:
                    if self._react_click(page, sel):
                        log.debug("form.next", label=label, via="react-fallback")
                        return True
            except Exception:
                continue
        # Text fallback
        try:
            result = page.evaluate(
                """() => {
                    const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                    const btn = Array.from(document.querySelectorAll('button')).find(b => {
                      if (!vis(b)) return false;
                      const t = (b.innerText || '').replace(/\\s+/g,' ').trim();
                      return /^(next)$/i.test(t) || /submit loan request/i.test(t);
                    });
                    if (!btn) return null;
                    btn.click();
                    return (btn.innerText || '').replace(/\\s+/g,' ').trim().slice(0, 40);
                }"""
            )
            if result:
                log.debug("form.next", label=result, via="dom")
                return True
        except Exception:
            pass
        return False

    def _react_click(self, page: Page, selector: str, once: bool = False) -> bool:
        """Call React onClick on a button (Playwright/DOM click often does not).

        Important: always re-query the node so we get fresh props after a setState.

        once=True: the synthetic DOM click is only a fallback when no React
        handler was found.  React also handles that DOM click, so firing both
        ran onClick twice — on Submit Loan Request that posted every lead twice.
        """
        try:
            # Give any prior setState a chance to commit before reading props.
            time.sleep(0.15)
            result = page.evaluate(
                """([sel, once]) => {
                    const btn = document.querySelector(sel);
                    if (!btn) return 'missing';
                    const fire = (el) => {
                        // Re-read props from the live node (post-re-render).
                        const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
                        if (propsKey && el[propsKey] && typeof el[propsKey].onClick === 'function') {
                            el[propsKey].onClick({
                                preventDefault() {}, stopPropagation() {},
                                target: el, currentTarget: el, type: 'click',
                            });
                            return 'props';
                        }
                        const fiberKey = Object.keys(el).find(
                            k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                        );
                        if (!fiberKey) return null;
                        let fiber = el[fiberKey];
                        for (let i = 0; i < 10 && fiber; i++, fiber = fiber.return) {
                            const props = fiber.memoizedProps || fiber.pendingProps || {};
                            if (typeof props.onClick === 'function') {
                                props.onClick({
                                    preventDefault() {}, stopPropagation() {},
                                    target: el, currentTarget: el, type: 'click',
                                });
                                return 'fiber-' + i;
                            }
                        }
                        return null;
                    };
                    let how = fire(btn);
                    if (!how) {
                        let el = btn.parentElement;
                        for (let i = 0; i < 4 && el && !how; i++, el = el.parentElement) {
                            how = fire(el);
                        }
                    }
                    if (!how || !once) {
                        try {
                            btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                        } catch (e) {}
                    }
                    return how || 'dom-only';
                }""",
                [selector, once],
            )
            log.debug("form.react_click", selector=selector, result=result)
            return result not in (None, "missing")
        except Exception as exc:
            log.debug("form.react_click_fail", selector=selector, error=str(exc)[:80])
            return False

    def _react_set_input(self, page: Page, name: str, value: str) -> bool:
        """Set a controlled React input so step state (not just DOM) updates."""
        try:
            result = page.evaluate(
                """([name, value]) => {
                    const el = document.querySelector(`input[name="${name}"]`);
                    if (!el) return 'missing';
                    el.focus();
                    // Native setter + tracker so React sees a real value change.
                    const proto = HTMLInputElement.prototype;
                    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                    const last = el.value;
                    desc.set.call(el, value);
                    if (el._valueTracker) el._valueTracker.setValue(last === value ? last + ' ' : last);
                    // Event whose target IS the live input (handlers read e.target.value).
                    const evt = {
                      target: el,
                      currentTarget: el,
                      preventDefault() {},
                      stopPropagation() {},
                      bubbles: true,
                      type: 'change',
                    };
                    const fiberKey = Object.keys(el).find(
                      k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                    );
                    let fiber = fiberKey ? el[fiberKey] : null;
                    let called = false;
                    for (let i = 0; i < 12 && fiber; i++, fiber = fiber.return) {
                      const props = fiber.memoizedProps || {};
                      if (typeof props.onChange === 'function') {
                        try {
                          props.onChange(evt);
                          called = true;
                          if (props.name === name) break;
                        } catch (e) {}
                      }
                    }
                    const propsKey = Object.keys(el).find(k => k.startsWith('__reactProps'));
                    if (propsKey && el[propsKey] && typeof el[propsKey].onChange === 'function') {
                      try { el[propsKey].onChange(evt); called = true; } catch (e) {}
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.blur();
                    return called ? 'ok' : 'dom-only';
                }""",
                [name, str(value)],
            )
            time.sleep(0.45)
            log.debug("form.react_set", name=name, result=result)
            return result not in (None, "missing")
        except Exception:
            return False

    def _open_finish_for_popup(self, page: Page, bank: str, acct: str) -> bool:
        """Merge bank into React form and force #finish so Submit Loan Request appears."""
        try:
            result = page.evaluate(
                """([bank, acct]) => {
                  try {
                    if (document.applyForm && !document.applyForm.__tgfcSubmitPatched) {
                      document.applyForm.__tgfcSubmitPatched = true;
                      document.applyForm.submit = function () {
                        window.__tgfc_native_submit_blocked = true;
                        return false;
                      };
                    }
                  } catch (e) {}

                  const roots = [
                    document.querySelector('#f-wizard-form'),
                    document.querySelector('input[name="bankAccountNumber"]'),
                    document.body,
                  ].filter(Boolean);

                  let formUpdated = false;
                  let stepUpdated = false;

                  const walk = (el) => {
                    const fiberKey = Object.keys(el).find(
                      k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                    );
                    if (!fiberKey) return;
                    let fiber = el[fiberKey];
                    for (let depth = 0; depth < 45 && fiber; depth++, fiber = fiber.return) {
                      let hook = fiber.memoizedState;
                      while (hook) {
                        const v = hook.memoizedState;
                        const q = hook.queue;
                        if (q && typeof q.dispatch === 'function') {
                          // Form object state
                          if (
                            v && typeof v === 'object' && !Array.isArray(v)
                            && (v.email || v.firstName || v.bankRoutingNumber)
                          ) {
                            q.dispatch(Object.assign({}, v, {
                              bankName: bank,
                              bankAccountNumber: acct,
                            }));
                            formUpdated = true;
                          }
                          // currentStep string state
                          if (typeof v === 'string' && (
                            v === 'bankAccountNumber' || v === 'bankRoutingNumber' || v === 'bankAccountType'
                          )) {
                            q.dispatch('finish');
                            stepUpdated = true;
                          }
                        }
                        hook = hook.next;
                      }
                    }
                  };

                  roots.forEach(walk);

                  const prev = location.hash;
                  location.hash = '#finish';
                  try {
                    window.dispatchEvent(new HashChangeEvent('hashchange', {
                      oldURL: location.href.replace(/#.*$/, '') + prev,
                      newURL: location.href,
                    }));
                  } catch (e) {
                    window.dispatchEvent(new Event('hashchange'));
                  }

                  return {
                    formUpdated, stepUpdated,
                    hash: (location.hash || '').replace(/^#/, ''),
                    btn: (() => {
                      const b = document.querySelector('button.f-wizard-step--buttons--next');
                      return b ? (b.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 40) : '';
                    })(),
                  };
                }""",
                [bank, acct],
            )
            log.info("form.open_finish", result=result)
            # Allow React to paint Finish.
            for _ in range(20):
                step = self._current_step(page)
                label = ""
                try:
                    label = page.locator("button.f-wizard-step--buttons--next").first.inner_text(timeout=500)
                except Exception:
                    pass
                if step == "finish" or "submit loan request" in (label or "").lower():
                    log.info("form.finish_ready", step=step, label=(label or "")[:40])
                    return True
                time.sleep(0.35)
            # One more force
            try:
                page.evaluate("() => { location.hash = '#finish'; }")
                time.sleep(1.0)
            except Exception:
                pass
            return self._current_step(page) == "finish"
        except Exception as exc:
            log.warning("form.open_finish_fail", error=str(exc)[:120])
            return False

    def _await_bank_exit(self, page: Page, row_number: int, stop_event) -> str | None:
        """After bank: prefer #finish → Submit Loan Request → processing popup."""
        deadline = time.time() + 50
        while time.time() < deadline:
            self._check_stop(stop_event)

            step = self._current_step(page)
            if step == "finish" or page.locator("button:has-text('Submit Loan Request')").count():
                log.info("form.bank_exit", row=row_number, outcome="hash=finish → CTA")
                self._submit_finish(page, row_number)
                return self._wait_completion(page, row_number, stop_event) or "submitted (finish)"

            outcome = self._completion_state(page, require_visual=True)
            if outcome:
                log.info("form.bank_exit", row=row_number, outcome=outcome)
                return outcome

            if step and step != "bankAccountNumber" and step != "finish":
                log.info("form.bank_exit", row=row_number, next_step=step)
                return None
            time.sleep(0.4)

        outcome = self._completion_state(page, require_visual=True)
        if outcome:
            return outcome
        # If still on finish, try CTA once more.
        if self._current_step(page) == "finish":
            self._submit_finish(page, row_number)
            return self._wait_completion(page, row_number, stop_event)
        raise FormFillerError(
            "Bank step done but Finish CTA / processing popup never appeared",
            error_type="stuck",
        )

    def _call_wizard_on_next(self, page: Page, payload: dict) -> bool:
        """Call step onNext(payload). Wizard merges into form then goToNextStep."""
        try:
            result = page.evaluate(
                """(payload) => {
                    const roots = [
                      document.querySelector('input[name="bankAccountNumber"]'),
                      document.querySelector('input[name="bankName"]'),
                      document.querySelector('button.f-wizard-step--buttons--next'),
                      document.querySelector('#f-wizard-form'),
                    ].filter(Boolean);
                    for (const el of roots) {
                      const fiberKey = Object.keys(el).find(
                        k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                      );
                      let fiber = fiberKey ? el[fiberKey] : null;
                      for (let i = 0; i < 25 && fiber; i++, fiber = fiber.return) {
                        const props = fiber.memoizedProps || {};
                        // Step components expose both onNext and onError.
                        if (typeof props.onNext === 'function' && typeof props.onError === 'function') {
                          props.onNext(payload);
                          return 'step-onNext-' + i;
                        }
                      }
                    }
                    for (const el of roots) {
                      const fiberKey = Object.keys(el).find(
                        k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                      );
                      let fiber = fiberKey ? el[fiberKey] : null;
                      for (let i = 0; i < 25 && fiber; i++, fiber = fiber.return) {
                        const props = fiber.memoizedProps || {};
                        if (typeof props.onNext === 'function') {
                          props.onNext(payload);
                          return 'onNext-' + i;
                        }
                      }
                    }
                    return 'missing';
                }""",
                payload,
            )
            log.info("form.wizard_on_next", result=result, keys=list(payload.keys())[:6])
            time.sleep(0.5)
            return result not in (None, "missing")
        except Exception as exc:
            log.warning("form.wizard_on_next_fail", error=str(exc)[:100])
            return False

    def _await_step_change(self, page: Page, old_step: str, timeout: float = 12) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._current_step(page) != old_step:
                return True
            if self._completion_state(page, require_visual=True):
                return True
            time.sleep(0.12)
        return False

    def _submit_finish(self, page: Page, row_number: int) -> None:
        """Click Submit Loan Request exactly once, then wait for processing popup.

        Every click that reaches the button's handler posts the lead again.  This
        used to fire React onClick, a synthetic DOM click and a forced Playwright
        click in a row, and the buyer's panel logged each person twice within a
        second.  A second click now happens only when the first visibly did
        nothing, and never on a later call for the same row."""
        self._finish_popup = None
        if getattr(self, "_finish_clicked", False):
            log.info("form.finish_cta", row=row_number, via="already-clicked")
            self._wait_finish_modal(page, row_number)
            return
        time.sleep(0.8)
        try:
            page.locator("button.f-wizard-step--buttons--next").first.scroll_into_view_if_needed(timeout=8000)
        except Exception:
            pass

        clicked = False
        if self._react_click(page, "button.f-wizard-step--buttons--next", once=True):
            clicked = True
            log.info("form.finish_cta", row=row_number, via="react-css")
        else:
            try:
                ok = page.evaluate(
                    """() => {
                      const btn = Array.from(document.querySelectorAll('button,[role=button]'))
                        .find(b => /submit loan request/i.test((b.textContent||'').trim()))
                        || document.querySelector('.f-wizard-step--buttons--next');
                      if (!btn) return false;
                      const propsKey = Object.keys(btn).find(k => k.startsWith('__reactProps'));
                      if (propsKey && btn[propsKey] && typeof btn[propsKey].onClick === 'function') {
                        btn[propsKey].onClick({
                          preventDefault() {}, stopPropagation() {},
                          target: btn, currentTarget: btn, type: 'click',
                        });
                      } else {
                        btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                      }
                      return true;
                    }"""
                )
                if ok:
                    clicked = True
                    log.info("form.finish_cta", row=row_number, via="react-text")
            except Exception as exc:
                log.warning("form.finish_cta_failed", row=row_number, error=str(exc)[:100])

        if not clicked:
            try:
                page.locator("button.f-wizard-step--buttons--next").first.click(timeout=3000)
                clicked = True
                log.info("form.finish_cta", row=row_number, via="playwright")
            except Exception:
                log.warning("form.finish_cta", row=row_number, via="none")
        elif not self._finish_started(page, 10):
            # The handler call registered nothing at all — one real click.
            log.warning("form.finish_cta_retry", row=row_number, via="playwright")
            try:
                page.locator("button.f-wizard-step--buttons--next").first.click(timeout=3000)
            except Exception:
                pass
        self._finish_clicked = clicked
        self._wait_finish_modal(page, row_number)

    def _finish_started(self, page: Page, secs: float) -> bool:
        """True once the submit visibly kicked off: popup, submit flag, or the
        page left the finish step."""
        deadline = time.time() + secs
        while time.time() < deadline:
            try:
                if self._completion_state(page) or self._current_step(page) != "finish":
                    return True
                if page.evaluate("() => !!window.__tgfc_native_submit_blocked"):
                    return True
            except Exception as exc:
                if self._is_nav_error(exc):
                    return True
            time.sleep(0.4)
        return False

    def _wait_finish_modal(self, page: Page, row_number: int) -> None:
        try:
            page.wait_for_selector(
                ".final-processing-modal, .f-modal.final-processing-modal, "
                ".f-modal, .shared-modal-content, .f-modal-dialog",
                state="visible",
                timeout=30000,
            )
            log.info("form.finish_modal", row=row_number, state="visible")
        except Exception:
            log.warning("form.finish_modal", row=row_number, state="not-seen-yet")
        time.sleep(1.5)

    def _completion_state(self, page: Page, require_visual: bool = False) -> str | None:
        try:
            url = page.url or ""
            h = self._current_step(page)
            info = page.evaluate(
                """() => {
                  const modal = document.querySelector(
                    '.final-processing-modal, .f-modal.final-processing-modal, '
                    + '.f-modal, .shared-modal-content, .f-modal-dialog, [class*=congrat]'
                  );
                  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
                  const modalText = (modal && vis(modal) ? (modal.innerText || '') : '').toLowerCase();
                  const body = (document.body ? document.body.innerText : '').slice(0, 5000).toLowerCase();
                  return { modalText, body, modalVisible: !!(modal && vis(modal)) };
                }"""
            ) or {}
            body = (info.get("modalText") or "") + "\n" + (info.get("body") or "")
            modal_visible = bool(info.get("modalVisible"))

            congrat_keys = (
                "congrat",
                "great news",
                "you qualify",
                "you're approved",
                "you’re approved",
                "we found",
                "lenders found",
                "options available",
                "thank you",
            )
            hay = (info.get("modalText") or "") or body
            if modal_visible and any(k in hay for k in congrat_keys):
                return "submitted (congratulations popup)"

            if modal_visible and any(
                k in hay
                for k in (
                    "verifying",
                    "connecting",
                    "processing",
                    "loan provider",
                    "waiting for decision",
                    "matching",
                    "initiating loan",
                    "searching",
                    "confirming",
                )
            ):
                return "submitted (processing popup)"

            if h == "finish" and modal_visible and any(k in hay for k in congrat_keys):
                return "submitted (congratulations popup)"
            if "bkoffers.com" in url or "requestedresults.com" in url:
                return f"redirected ({url[:60]})"
            if "togetfastcash.com" not in url and url.startswith("http"):
                return f"redirected ({url[:60]})"
            popup = getattr(self, "_finish_popup", None)
            if popup is not None:
                try:
                    if not popup.is_closed():
                        return f"submitted (popup { (popup.url or '')[:60] })"
                except Exception:
                    pass

            if require_visual:
                return None

            # Soft signals (submit kicked off) — only when caller allows.
            try:
                submitted = page.evaluate(
                    """() => {
                      try {
                        const fd = localStorage.getItem('_fd');
                        if (fd && fd.length > 20) return 'localStorage:_fd';
                      } catch (e) {}
                      if (window.__tgfc_submitted) return 'flag';
                      return null;
                    }"""
                )
                if submitted:
                    return f"submitted ({submitted})"
            except Exception:
                pass
        except Exception:
            pass
        return None

    def _wait_completion(self, page: Page, row_number: int, stop_event) -> str | None:
        # Processing modal can run for ~1–2 minutes, then congratulations.
        deadline = time.time() + 120
        saw_modal = False
        while time.time() < deadline:
            self._check_stop(stop_event)
            outcome = self._completion_state(page, require_visual=True)
            if outcome:
                if "processing popup" in outcome or "congratulations" in outcome:
                    saw_modal = True
                    log.info("form.finish_wait", row=row_number, state=outcome)
                    soft = time.time() + 70
                    while time.time() < soft:
                        self._check_stop(stop_event)
                        off = self._offsite_page(page)
                        if off is not None:
                            return f"redirected ({(off.url or '')[:60]})"
                        nxt = self._completion_state(page, require_visual=True)
                        if nxt and nxt.startswith("redirected"):
                            return nxt
                        time.sleep(1.5)
                    return outcome
                return outcome
            time.sleep(1.5)
        if saw_modal:
            return "submitted (processing popup)"
        if self._current_step(page) == "finish":
            self._screenshot(page, row_number, "finish_no_confirm")
            raise FormFillerError(
                "Finish CTA clicked but submission popup/redirect did not confirm",
                error_type="captcha",
            )
        return None
