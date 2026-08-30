"""accounting-pack ToolProvider (P6) — normalized ledger reads: Google Sheet or CSV.

Two sources, same normalized `LedgerRow` shape:
- Google Sheet (via the `gws` CLI, exactly hr-pack's `_gws_sheet_rows` transport —
  a spawn-and-parse-JSON adapter, no new dependency).
- Local CSV file (`ACCOUNTING_LEDGER_CSV_PATH` env) — an offline/no-Google fallback,
  since "mỗi doanh nghiệp mỗi sheet khác nhau" (phase risk note) and not every business
  has `gws` configured yet.

Standardized minimal ledger schema (header row, case-insensitive, Vietnamese or English
column names both accepted): date, type (thu/chi | income/expense), amount, description.
A row missing `date` or `amount` is skipped (not silently zeroed) — same "skip fully
blank, otherwise keep" posture as hr-pack's `_rows_to_tasks`.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SHEET_ID_ENV = "ACCOUNTING_SHEET_ID"
_SHEET_RANGE_ENV = "ACCOUNTING_SHEET_RANGE"
_CSV_PATH_ENV = "ACCOUNTING_LEDGER_CSV_PATH"
_DEFAULT_RANGE = "A1:F1000"

_INCOME_TOKENS = ("thu", "income", "revenue")
_EXPENSE_TOKENS = ("chi", "expense", "cost")


class LedgerReadError(RuntimeError):
    """Raised when the configured ledger source (Sheet or CSV) could not be read.

    Caught by `AccountingToolProvider.read`, which returns `None` (not this exception)
    to the graph — same THIẾU fail-degrade contract as ads-pack, never fabricated rows.
    """


@dataclass(frozen=True)
class LedgerRow:
    """One normalized ledger entry."""

    date: str  # ISO-ish string, verbatim from the source (no date-parsing/guessing)
    kind: str  # "income" | "expense" | "unknown"
    amount: float
    description: str


def _gws_sheet_rows(spreadsheet_id: str, cell_range: str) -> list[list[str]]:
    """Read a sheet range via the `gws` CLI. Identical transport to hr-pack's
    `_gws_sheet_rows` (kept pack-local rather than shared: YAGNI on a cross-pack helper
    module until a third pack needs the same few lines — see registry.py's own
    "add a field then" precedent for premature sharing)."""
    try:
        proc = subprocess.run(
            [
                "gws", "sheets", "spreadsheets", "values", "get",
                "--params", json.dumps({"spreadsheetId": spreadsheet_id, "range": cell_range}),
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except FileNotFoundError as exc:
        raise LedgerReadError(
            "gws CLI not found — install the Google Workspace CLI to read the ledger sheet."
        ) from exc
    if proc.returncode != 0:
        raise LedgerReadError(
            f"gws sheets read failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    out = proc.stdout
    brace = out.find("{")
    if brace == -1:
        raise LedgerReadError(f"gws sheets read returned no JSON: {out.strip()[:200]}")
    try:
        data = json.loads(out[brace:])
    except json.JSONDecodeError as exc:
        # Truncated/garbled stdout (mixed-in banner text, a gws version that changes
        # its output format mid-stream) is an external-source failure, not a bug here —
        # same fail-degrade posture as every other gws/CSV failure in this module.
        raise LedgerReadError(
            f"gws sheets read returned malformed JSON: {out.strip()[:200]}"
        ) from exc
    if "values" not in data:
        raise LedgerReadError(
            f"gws sheets read returned no values (error response?): {out.strip()[:200]}"
        )
    return [[str(c) for c in row] for row in data["values"]]


def _csv_rows(path: Path) -> list[list[str]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return [row for row in csv.reader(f)]
    except OSError as exc:
        raise LedgerReadError(f"cannot read ledger CSV at {path}: {exc}") from exc
    except csv.Error as exc:
        # A null byte or an unterminated quoted field raises csv.Error, not OSError —
        # same external-file-is-broken failure mode, same fail-degrade treatment.
        raise LedgerReadError(f"cannot parse ledger CSV at {path}: {exc}") from exc


def _classify_kind(raw: str) -> str:
    lowered = raw.strip().lower()
    if any(tok in lowered for tok in _INCOME_TOKENS):
        return "income"
    if any(tok in lowered for tok in _EXPENSE_TOKENS):
        return "expense"
    return "unknown"


def _first(cells: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = cells.get(k, "").strip()
        if v:
            return v
    return ""


def rows_to_ledger(rows: list[list[str]]) -> list[LedgerRow]:
    """Map header+data rows into normalized `LedgerRow`s. A row with no date or no
    parseable amount is skipped — never coerced to 0 (that would silently understate
    cashflow)."""
    if not rows:
        return []
    headers = [h.strip().lower() for h in rows[0]]
    out: list[LedgerRow] = []
    for row in rows[1:]:
        cells = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
        if not any(v.strip() for v in cells.values()):
            continue
        date = _first(cells, ("date", "ngày", "ngay"))
        amount_raw = _first(cells, ("amount", "số tiền", "so tien", "value"))
        kind_raw = _first(cells, ("type", "loại", "loai", "kind"))
        desc = _first(cells, ("description", "diễn giải", "dien giai", "note", "ghi chú"))
        if not date or not amount_raw:
            continue
        try:
            amount = float(amount_raw.replace(",", "").replace(" ", ""))
        except ValueError:
            continue  # unparseable amount — skip rather than guess
        out.append(LedgerRow(date=date, kind=_classify_kind(kind_raw), amount=amount,
                              description=desc))
    return out


class AccountingToolProvider:
    """accounting-pack read seam: `read(kind, config, settings)` → list[LedgerRow] | None.

    Prefers the Sheet source when `ACCOUNTING_SHEET_ID` is set; falls back to the CSV
    path when only `ACCOUNTING_LEDGER_CSV_PATH` is set. Neither configured ⇒ raises
    (misconfiguration, fail-loud — mirrors hr-pack). A configured-but-broken source
    (gws error, missing CSV file) ⇒ returns None (fail-degrade, THIẾU in the report).
    """

    def read(self, kind: str, config: Any, settings: Any) -> list[LedgerRow] | None:
        sheet_id = os.environ.get(_SHEET_ID_ENV, "").strip()
        csv_path_raw = os.environ.get(_CSV_PATH_ENV, "").strip()
        if not sheet_id and not csv_path_raw:
            raise RuntimeError(
                f"cashflow-weekly needs a data source: set {_SHEET_ID_ENV} and/or "
                f"{_CSV_PATH_ENV} in the environment."
            )
        try:
            if sheet_id:
                cell_range = os.environ.get(_SHEET_RANGE_ENV, "").strip() or _DEFAULT_RANGE
                return rows_to_ledger(_gws_sheet_rows(sheet_id, cell_range))
            return rows_to_ledger(_csv_rows(Path(csv_path_raw)))
        except LedgerReadError:
            return None  # degrade — the analyzer renders THIẾU, never fabricates numbers


#: The pack's tool provider instance. Loaded by PackRegistry into Pack.tools.
TOOL_PROVIDER = AccountingToolProvider()
