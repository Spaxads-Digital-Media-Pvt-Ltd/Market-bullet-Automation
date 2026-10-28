"""
utils/sheet_handler.py
──────────────────────
Google Sheets integration via Service Account.

Responsibilities:
  • Authenticate with Google using a service-account JSON key.
  • Fetch all rows where Status == "Pending".
  • Lock a row by setting Status → "In Progress".
  • Write back results (Success / Failed / Retry) with metadata.

Writes use the worksheet's numeric sheetId (UpdateCells), never a bare A1
range.  That way Status cannot land on the first tab of the workbook.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import gspread
import requests
from google.auth.exceptions import TransportError
from google.oauth2.service_account import Credentials
import structlog

log = structlog.get_logger(__name__)


def is_transient(e: BaseException) -> bool:
    """True for network / quota errors that are worth retrying.  A token
    refresh that times out raises google.auth's TransportError, which is
    neither an OSError nor a requests exception — missing it here let a
    single network blip crash a paced run that had hours left."""
    if isinstance(e, gspread.exceptions.APIError):
        code = getattr(getattr(e, "response", None), "status_code", 0)
        return code in (429, 500, 502, 503, 504)
    return isinstance(e, (OSError, requests.exceptions.RequestException, TransportError))

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_STATUS_COLORS = {
    "success": {"red": 0.72, "green": 0.88, "blue": 0.80},
    "in progress": {"red": 0.99, "green": 0.91, "blue": 0.70},
    "failed": {"red": 0.96, "green": 0.78, "blue": 0.76},
    "retry": {"red": 1.0, "green": 0.85, "blue": 0.70},
    "stopped": {"red": 0.85, "green": 0.85, "blue": 0.85},
    "declined": {"red": 0.90, "green": 0.80, "blue": 0.95},
    "filtered": {"red": 0.80, "green": 0.85, "blue": 0.95},
}


class SheetHandler:
    """Manages all interactions with a single Google Sheet worksheet."""

    def __init__(
        self,
        config: dict,
        sheet_url: str | None = None,
        worksheet_name: str | None = None,
    ) -> None:
        self._config = config
        self._col_map: dict[str, str] = config.get("sheet_columns", {})
        self._sheet_url = sheet_url or os.getenv("GOOGLE_SHEET_URL", "")
        self._worksheet_name = worksheet_name or os.getenv("GOOGLE_SHEET_WORKSHEET", "Sheet1")

        self._spreadsheet = None
        self._worksheet = self._open_worksheet()
        self._headers: list[str] = self._worksheet.row_values(1)
        self._ensure_result_columns()
        log.info("sheet.connected", worksheet=self._worksheet_name, columns=len(self._headers),
                 sheet_id=self._worksheet.id)

    def _open_worksheet(self):
        creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/credentials.json")
        credentials = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
        client = gspread.authorize(credentials)
        if self._sheet_url.startswith("http"):
            self._spreadsheet = client.open_by_url(self._sheet_url)
        else:
            self._spreadsheet = client.open_by_key(self._sheet_url)
        return self._spreadsheet.worksheet(self._worksheet_name)

    def _ss(self):
        return self._spreadsheet or self._worksheet.spreadsheet

    # ── helpers ──────────────────────────────────────────────────────

    def _ensure_result_columns(self) -> None:
        result_fields = ["status", "notes", "proxy_used", "ip", "last_attempt",
                         "submission_id", "retry_count"]
        have = {str(h).strip().lower() for h in self._headers}
        missing = []
        for field in result_fields:
            header = self._col_map.get(field, field)
            if str(header).strip().lower() not in have:
                missing.append(header)
                have.add(str(header).strip().lower())
        if not missing:
            return

        needed_cols = len(self._headers) + len(missing)
        if needed_cols > self._worksheet.col_count:
            self._worksheet.resize(
                rows=self._worksheet.row_count,
                cols=needed_cols,
            )

        for col_name in missing:
            next_col = len(self._headers) + 1
            self._write_cells([(1, next_col, col_name)])
            self._headers.append(col_name)

        log.info("sheet.columns_added", columns=missing)

    def _all_col_indexes(self, internal_name: str) -> list[int]:
        header = self._col_map.get(internal_name, internal_name)
        want = str(header).strip().lower()
        found = [
            i + 1
            for i, h in enumerate(self._headers)
            if str(h).strip().lower() == want
        ]
        if not found:
            raise KeyError(f"Column '{header}' not found in sheet headers: {self._headers}")
        return found

    def _col_index(self, internal_name: str) -> int:
        return self._all_col_indexes(internal_name)[0]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def _reconnect(self) -> None:
        self._worksheet = self._open_worksheet()
        self._headers = self._worksheet.row_values(1)

    def _retry(self, fn):
        # ~3.5 min of backoff (plus request timeouts) so a short network drop
        # or a laptop waking from sleep is ridden out instead of raised.
        last_err: Exception | None = None
        for attempt in range(8):
            try:
                return fn()
            except Exception as e:
                if not is_transient(e):
                    raise
                last_err = e
            log.warning("sheet.retry", attempt=attempt + 1, error=str(last_err)[:90])
            time.sleep(min(2 ** attempt, 60))
            try:
                self._reconnect()
            except Exception:
                pass
        raise last_err  # type: ignore[misc]

    def _write_cells(self, cells: list[tuple[int, int, Any]], *, paint_status: str | None = None) -> None:
        """Write cells by sheetId (row, col are 1-based). Cannot hit another tab."""
        if not cells:
            return
        sheet_id = self._worksheet.id
        requests_body = []
        for row, col, value in cells:
            cell_value: dict
            if isinstance(value, bool):
                cell_value = {"boolValue": value}
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cell_value = {"numberValue": float(value)}
            else:
                cell_value = {"stringValue": "" if value is None else str(value)}
            cell: dict[str, Any] = {"userEnteredValue": cell_value}
            fields = "userEnteredValue"
            if paint_status is not None and col in self._safe_status_cols():
                color = _STATUS_COLORS.get(paint_status.strip().lower())
                if color:
                    cell["userEnteredFormat"] = {
                        "backgroundColor": color,
                        "textFormat": {"bold": True},
                    }
                    fields = "userEnteredValue,userEnteredFormat"
            requests_body.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col - 1,
                        "endColumnIndex": col,
                    },
                    "rows": [{"values": [cell]}],
                    "fields": fields,
                }
            })
        self._retry(lambda: self._ss().batch_update({"requests": requests_body}))

    def _safe_status_cols(self) -> set[int]:
        try:
            return set(self._all_col_indexes("status"))
        except KeyError:
            return set()

    def _read_cell(self, row: int, col: int) -> str:
        title = self._worksheet_name.replace("'", "''")
        a1 = gspread.utils.rowcol_to_a1(row, col)
        rng = f"'{title}'!{a1}"
        data = self._retry(lambda: self._ss().values_get(rng))
        values = data.get("values") or []
        if not values or not values[0]:
            return ""
        return str(values[0][0]).strip()

    def _write_status(self, row_number: int, status: str, extra: list[tuple[str, Any]] | None = None) -> str:
        cells: list[tuple[int, int, Any]] = []
        for col in self._all_col_indexes("status"):
            cells.append((row_number, col, status))
        if extra:
            for field, value in extra:
                try:
                    for col in self._all_col_indexes(field):
                        cells.append((row_number, col, value))
                except KeyError:
                    log.warning("sheet.column_missing", field=field)
        self._write_cells(cells, paint_status=status)
        status_col = self._col_index("status")
        got = self._read_cell(row_number, status_col)
        if got.lower() != str(status).strip().lower():
            # One retry after reconnect — stale worksheet metadata.
            self._retry(self._reconnect)
            self._write_cells(cells, paint_status=status)
            got = self._read_cell(row_number, self._col_index("status"))
        if got.lower() != str(status).strip().lower():
            raise RuntimeError(
                f"Status write failed on '{self._worksheet_name}' row {row_number}: "
                f"wanted {status!r}, sheet has {got!r}"
            )
        a1 = gspread.utils.rowcol_to_a1(row_number, status_col)
        label = f"'{self._worksheet_name}'!{a1}"
        log.info("sheet.row_updated", row=row_number, status=status, cell=label, verified=got)
        print(f"SHEET {label} = {status} (verified)", flush=True)
        return label

    # ── public API ───────────────────────────────────────────────────

    def reclaim_in_progress_rows(self) -> int:
        """Return rows stuck on 'In Progress' to Pending (crash / Stop recovery)."""
        all_records = self._retry(
            lambda: self._worksheet.get_all_records(numericise_ignore=["all"])
        )
        status_col = self._col_map.get("status", "Status")
        reclaimed = 0
        for idx, record in enumerate(all_records, start=2):
            val = str(
                record.get(status_col)
                or record.get("Status")
                or record.get("status")
                or ""
            ).strip().lower()
            if val == "in progress":
                self._write_status(idx, "Pending", [("notes", "[reclaimed] previous run interrupted")])
                reclaimed += 1
        if reclaimed:
            log.info("sheet.reclaimed_in_progress", count=reclaimed,
                     worksheet=self._worksheet_name)
        return reclaimed

    def get_pending_rows(self) -> list[dict[str, Any]]:
        all_records = self._retry(
            lambda: self._worksheet.get_all_records(numericise_ignore=["all"])
        )
        status_col = self._col_map.get("status", "Status")
        pending: list[dict[str, Any]] = []

        for idx, record in enumerate(all_records, start=2):
            val = str(
                record.get(status_col)
                or record.get("Status")
                or record.get("status")
                or ""
            ).strip().lower()
            if val in ("pending", ""):
                record["_row_number"] = idx
                pending.append(record)

        log.info("sheet.pending_rows", count=len(pending))
        return pending

    def mark_in_progress(self, row_number: int) -> None:
        self._write_status(row_number, "In Progress")

    def update_row(
        self,
        row_number: int,
        *,
        status: str,
        notes: str = "",
        proxy_used: str = "",
        ip: str = "",
        submission_id: str = "",
        retry_count: int | None = None,
    ) -> None:
        extra: list[tuple[str, Any]] = [
            ("notes", notes),
            ("proxy_used", proxy_used),
            ("ip", ip),
            ("last_attempt", self._now_iso()),
            ("submission_id", submission_id),
        ]
        if retry_count is not None:
            extra.append(("retry_count", retry_count))
        self._write_status(row_number, status, extra)
