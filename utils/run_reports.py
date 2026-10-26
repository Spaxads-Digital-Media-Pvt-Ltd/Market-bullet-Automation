"""
utils/run_reports.py
────────────────────
Paced-run reports: one JSON file per paced plan, rewritten each time one of
its offer engines finishes, so the last write holds every offer's outcome.
Kept for KEEP_DAYS and then deleted automatically.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPORT_DIR = Path("reports")
KEEP_DAYS = 3
_ID_RE = re.compile(r"^[a-z0-9-]{4,40}$")


def _path(report_id: str) -> Path:
    return REPORT_DIR / f"{report_id}.json"


def cleanup(now: float | None = None) -> int:
    """Delete reports older than KEEP_DAYS. Returns how many were removed."""
    if not REPORT_DIR.exists():
        return 0
    cutoff = (now or time.time()) - KEEP_DAYS * 86400
    removed = 0
    for f in REPORT_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def save(report: dict) -> str:
    """Write atomically (a reader never sees half a file) and return the id."""
    REPORT_DIR.mkdir(exist_ok=True)
    rid = report["id"]
    tmp = _path(rid).with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str))
    os.replace(tmp, _path(rid))
    cleanup()
    return rid


def load(report_id: str) -> dict | None:
    if not _ID_RE.match(report_id or ""):
        return None
    try:
        return json.loads(_path(report_id).read_text())
    except (OSError, ValueError):
        return None


def list_reports() -> list[dict]:
    """Summaries of the reports still within KEEP_DAYS, newest first."""
    cleanup()
    out = []
    for f in REPORT_DIR.glob("*.json") if REPORT_DIR.exists() else []:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        expires = f.stat().st_mtime + KEEP_DAYS * 86400
        out.append({
            "id": r.get("id"), "run_id": r.get("run_id"), "status": r.get("status"),
            "updated": r.get("updated"), "window": r.get("window"),
            "offers": [o.get("name") for o in r.get("offers", [])],
            "planned": r.get("totals", {}).get("planned"), "done": r.get("totals", {}).get("done"),
            "success": r.get("totals", {}).get("success"), "failed": r.get("totals", {}).get("failed"),
            "expires": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
        })
    out.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return out


def build(run_id: str, pacer, offer_runs: dict, offer_names: dict) -> dict:
    """Assemble a report from the pacer's hour-by-hour plan and what each
    offer's engine recorded. ``offer_runs`` maps offer_id -> the engine's run
    record (or None if that offer never started for this run)."""
    hours = []
    for s in pacer.slots:
        hours.append({
            "label": pacer._slot_label(s),
            "planned": {o: s.offer_budgets.get(o, 0) for o in pacer.offers},
            "actual": {o: s.offer_actuals.get(o, 0) for o in pacer.offers},
        })
    offers, leads = [], []
    running = False
    for o in pacer.offers:
        run = offer_runs.get(o) or {}
        running = running or bool(run.get("running"))
        recs = run.get("leads", [])
        counts: dict[str, int] = {}
        for rec in recs:
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        offers.append({
            "id": o, "name": offer_names.get(o, o),
            "planned": pacer.offer_leads.get(o, 0),
            "done": sum(h["actual"][o] for h in hours),
            "outcomes": counts,
            "state": "running" if run.get("running") else ("not started" if not run else "finished"),
            "reason": run.get("reason") or ("" if run.get("running") else "never started"),
            "started": run.get("started"), "ended": run.get("ended"),
        })
        leads.extend(dict(rec, offer=offer_names.get(o, o)) for rec in recs)
    leads.sort(key=lambda r: r.get("time") or "")
    fmt = "%b %d, %I:%M %p"
    return {
        "id": f"paced-{run_id}", "run_id": run_id,
        "tz": getattr(pacer.tz, "key", None) or "America/New_York",
        "status": "running" if running else "finished",
        "updated": datetime.now(timezone.utc).isoformat(),
        "window": f"{pacer.start_time.strftime(fmt)} – {pacer.end_time.strftime(fmt)} "
                  f"({pacer.start_time.tzname() or 'local'})",
        "offers": offers, "hours": hours, "leads": leads,
        "totals": {
            "planned": sum(o["planned"] for o in offers),
            "done": sum(o["done"] for o in offers),
            "success": sum(o["outcomes"].get("Success", 0) for o in offers),
            "failed": sum(n for o in offers for k, n in o["outcomes"].items() if k != "Success"),
        },
    }


def render_html(r: dict) -> str:
    e = lambda v: html.escape(str(v if v is not None else ""))
    ids = [o["id"] for o in r["offers"]]
    offer_rows = "".join(
        f"<tr><td>{e(o['name'])}</td><td>{o['planned']}</td><td>{o['done']}</td>"
        f"<td>{e(', '.join(f'{k}: {n}' for k, n in o['outcomes'].items()) or '—')}</td>"
        f"<td>{e(o['state'])}</td><td class='reason'>{e(o['reason'])}</td></tr>"
        for o in r["offers"])
    hour_rows = ""
    for h in r["hours"]:
        cells = "".join(f"<td>{h['actual'][o]}/{h['planned'][o]}</td>" for o in ids)
        tp, ta = sum(h["planned"].values()), sum(h["actual"].values())
        cls = "" if ta >= tp else " class='short'"
        hour_rows += f"<tr{cls}><td>{e(h['label'])}</td>{cells}<td>{ta}/{tp}</td></tr>"
    lead_rows = "".join(
        f"<tr><td>{e(_local(l.get('time'), r.get('tz') or 'America/New_York'))}</td><td>{e(l.get('offer'))}</td><td>{e(l.get('row'))}</td>"
        f"<td>{e(l.get('name'))}</td><td class='st-{e(l.get('status'))}'>{e(l.get('status'))}</td>"
        f"<td class='notes'>{e(l.get('notes'))}</td></tr>"
        for l in r["leads"]) or "<tr><td colspan=6>No leads were processed.</td></tr>"
    t = r["totals"]
    tz = r.get("tz") or "America/New_York"
    loc = lambda iso: _local(iso, tz)
    tzname = datetime.now(ZoneInfo(tz)).strftime("%Z")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Paced run {e(r['run_id'])}</title>
<style>
body{{font:14px -apple-system,Segoe UI,sans-serif;background:#0f1420;color:#e2e8f0;margin:24px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:26px 0 8px;color:#7dd3fc}}
.sub{{color:#94a3b8;margin-bottom:14px}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #1e2d40;padding:6px 8px;text-align:left;vertical-align:top}} th{{background:#131926;color:#94a3b8}}
.short td{{background:#2a1d10}} .reason{{color:#fbbf24}} .notes{{color:#94a3b8;max-width:520px}}
.st-Success{{color:#4ade80}} .st-Failed,.st-Declined,.st-Filtered{{color:#f87171}} .st-Stopped{{color:#fbbf24}}
.badge{{display:inline-block;padding:2px 8px;border-radius:9px;background:#1e3a5f;margin-left:6px;font-size:12px}}
</style></head><body>
<h1>Paced run {e(r['run_id'])} <span class="badge">{e(r['status'])}</span></h1>
<div class="sub">Plan window: {e(r['window'])} · last updated {e(loc(r['updated']))} {e(tzname)} ·
planned {t['planned']}, done {t['done']} ({t['success']} success, {t['failed']} not successful)</div>
{f'<div class="sub reason">{e(r["note"])}</div>' if r.get("note") else ''}
<h2>Offers</h2><table><tr><th>Offer</th><th>Planned</th><th>Done</th><th>Outcomes</th><th>State</th><th>Why it ended</th></tr>{offer_rows}</table>
<h2>Hour by hour (done / planned)</h2><table><tr><th>Hour</th>{''.join(f'<th>{e(o["name"])}</th>' for o in r['offers'])}<th>Total</th></tr>{hour_rows}</table>
<h2>Leads</h2><table><tr><th>Time ({e(tzname)})</th><th>Offer</th><th>Sheet row</th><th>Name</th><th>Result</th><th>Notes</th></tr>{lead_rows}</table>
<div class="sub" style="margin-top:20px">Reports are deleted automatically {KEEP_DAYS} days after their last update.</div>
</body></html>"""


def _local(iso: str | None, tz: str = "America/New_York") -> str:
    """In the plan's timezone, so lead times line up with the hour-by-hour table."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz)).strftime("%b %d, %I:%M:%S %p")
    except (ValueError, KeyError):
        return iso
