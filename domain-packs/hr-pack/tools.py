"""hr-pack ToolProvider (v3 M6 S2) — the real test of the ToolProvider abstraction.

HR reads two sources the core never modeled:
- Confluence (REUSED): `my_crew.tools.confluence_read.get_page_content` — the same read PM
  uses, no change. The HR page id comes from env (`HR_CONFLUENCE_PAGE_ID`), the pack's
  own config, so the core needs no HR-specific config field.
- Google Sheet (NEW ADAPTER): spawns the `gws` CLI (`gws sheets spreadsheets values
  get`) exactly as PM's github_read spawns `gh` — a transport (HTTP-behind-a-CLI) the
  core never knew about. If this slots in with `git diff my_crew/` = empty, the M5
  ToolProvider abstraction is proven transport-agnostic.

Both sources map their rows into the generic `Task` model (kind "headcount-row"), so the
analyzer downstream is domain-neutral. Credentials are env-only: `gws` manages its own
OAuth (like `gh`); no token lives in the pack or on any action.
"""

from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from typing import Any

from my_crew.tools.models import Task

# Env config the HR pack reads (the pack owns its own config source; env-only).
_SHEET_ID_ENV = "HR_SHEET_ID"
_SHEET_RANGE_ENV = "HR_SHEET_RANGE"  # e.g. "Sheet1!A1:D100"; default a wide A:Z scan
_CONFLUENCE_PAGE_ENV = "HR_CONFLUENCE_PAGE_ID"
_DEFAULT_RANGE = "A1:Z1000"


def _gws_sheet_rows(spreadsheet_id: str, cell_range: str) -> list[list[str]]:
    """Read a sheet range via the `gws` CLI → list of string rows (header row first).

    Mirrors github_read's `gh` spawn: run a CLI subprocess, parse its JSON. `gws`
    prints a one-line keyring banner before the JSON, so we slice from the first `{`.
    """
    try:
        proc = subprocess.run(
            [
                "gws", "sheets", "spreadsheets", "values", "get",
                "--params", json.dumps({"spreadsheetId": spreadsheet_id, "range": cell_range}),
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gws CLI not found — install the Google Workspace CLI to read HR sheets."
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"gws sheets read failed: {proc.stderr.strip() or proc.stdout.strip()}")
    out = proc.stdout
    brace = out.find("{")
    if brace == -1:
        raise RuntimeError(f"gws sheets read returned no JSON: {out.strip()[:200]}")
    data = json.loads(out[brace:])
    # A successful read has a `values` key (possibly empty for a blank sheet). Its ABSENCE
    # means gws returned an error-shaped object with exit 0 — fail loud, don't treat as
    # an empty sheet (which would publish a false zero-headcount report).
    if "values" not in data:
        raise RuntimeError(
            f"gws sheets read returned no values (error response?): {out.strip()[:200]}"
        )
    return [[str(c) for c in row] for row in data["values"]]


def _rows_to_tasks(rows: list[list[str]], *, source: str) -> list[Task]:
    """Map sheet/table rows (header row + data rows) to generic Task records.

    The header row names the columns; each data row becomes a Task whose `extra` carries
    every column verbatim (name→value). `title`/`status`/`assignee` are pulled from the
    conventional headcount columns when present (name/role/department/status), so the
    analyzer can group without knowing the sheet's exact layout.
    """
    if not rows:
        return []
    headers = [h.strip().lower() for h in rows[0]]
    tasks: list[Task] = []
    for i, row in enumerate(rows[1:], start=1):
        cells = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
        if not any(v.strip() for v in cells.values()):
            continue  # skip fully-blank rows
        name = _first(cells, ("name", "họ tên", "tên", "employee", "nhân viên"))
        dept = _first(cells, ("department", "phòng ban", "team", "bộ phận"))
        status = _first(cells, ("status", "trạng thái", "employment"))
        role = _first(cells, ("role", "title", "vai trò", "chức danh"))
        tasks.append(
            Task(
                id=f"{source}:{i}",
                title=name or role or f"row-{i}",
                status=status or "unknown",
                assignee=name or None,
                labels=tuple(x for x in (dept, role) if x),
                kind="headcount-row",
                extra=tuple((k, v) for k, v in cells.items()),
            )
        )
    return tasks


def _first(cells: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = cells.get(k, "").strip()
        if v:
            return v
    return ""


class _TableRowParser(HTMLParser):
    """Collect rows of cell texts from the first <table> in a Confluence storage body.

    Pack-local (HR owns its Confluence-table parsing) so it depends only on
    `get_page_content` from the reused `confluence_read`, not on any private helper.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_table = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _confluence_table_rows(page_id: str, config: Any) -> list[list[str]]:
    """Read a Confluence page and extract its first table's rows (header + data).

    Reuses the PM `confluence_read.get_page_content` unchanged; the table parse is
    pack-local so the core needs no HR-specific parser.
    """
    from my_crew.tools import confluence_read

    content = confluence_read.get_page_content(page_id, config=config)
    if not content:
        return []
    parser = _TableRowParser()
    parser.feed(content)
    return parser.rows


class HrToolProvider:
    """HR reads: Confluence table (reused) + Google Sheet (new gws adapter) → Tasks.

    Conforms to `my_crew.packs.tool_provider.ToolProvider`: one `read(kind, config,
    settings)` returning normalized records. Both sources are optional — whichever env
    config is present is read; their Task lists are concatenated.
    """

    def read(self, kind: str, config: Any, settings: Any) -> list[Task]:
        sheet_id = os.environ.get(_SHEET_ID_ENV, "").strip()
        page_id = os.environ.get(_CONFLUENCE_PAGE_ENV, "").strip()
        # Fail loud on a missing data source: a headcount run with no sheet AND no
        # Confluence page is a misconfiguration, not an empty team — never let it
        # silently publish a "0 nhân sự" report.
        if not sheet_id and not page_id:
            raise RuntimeError(
                f"HR headcount needs a data source: set {_SHEET_ID_ENV} and/or "
                f"{_CONFLUENCE_PAGE_ENV} in the environment."
            )
        tasks: list[Task] = []
        if sheet_id:
            cell_range = os.environ.get(_SHEET_RANGE_ENV, "").strip() or _DEFAULT_RANGE
            tasks += _rows_to_tasks(_gws_sheet_rows(sheet_id, cell_range), source="sheet")
        if page_id:
            tasks += _rows_to_tasks(_confluence_table_rows(page_id, config), source="confluence")
        return tasks


#: The pack's tool provider instance. Loaded by PackRegistry into Pack.tools.
TOOL_PROVIDER = HrToolProvider()
