"""Confluence READ tool — fetch a page's body and parse the OKR table.

Used by Phase 3 to read the OKR definition: one Confluence page whose body is a
table with columns ``Objective | Key Result | Epic Key(s) | Weight``. The agent
reads it (no write), rolls up progress from Jira, and reports it.

Integration reality (verified 2026-06-22 against the running Confluence MCP):
- the fetch tool is ``getPageContent`` (arg ``pageId``), NOT ``getPage``;
- ``call_tool`` returns a list of human-readable text-block strings, the LAST of
  which (after a ``📝 Content:`` marker) is the page body as **raw XHTML storage**
  — ``<table><tbody><tr><th>…</th></tr><tr><td>…</td></tr></tbody></table>``
  survives intact, so the table is parseable.

All parsing here is pure (no network) so it is unit-testable with fixtures.
READ does not go through the Action Gateway (only mutations do).
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

from src.adapters.mcp_adapter import call_tool
from src.config.reporting_config import McpServerSpec, ReportingConfig
from src.tools.models import OkrProblem

logger = logging.getLogger(__name__)

# The OKR table's expected header titles (lower-cased, matched loosely so a header
# row is dropped rather than parsed as data).
_HEADER_CELLS = {"objective", "key result", "epic key(s)", "epic keys", "weight"}

# A valid Jira issue/epic key: PROJECT-123. OKR cells are user-typed on Confluence,
# so keys are validated to this shape before they ever reach a JQL string — a
# malformed token is dropped (→ an "epic không hợp lệ" problem downstream) rather
# than interpolated into a query.
_EPIC_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def _blocks_text_list(result: Any) -> list[str]:
    """Flatten an MCP text-block result into a list of strings.

    Each block may be a plain string or a ``{"text": ...}`` dict (the two shapes
    `_coerce_result` can surface). Non-list results become a single-element list.
    """
    if isinstance(result, list):
        out = []
        for b in result:
            if isinstance(b, dict) and "text" in b:
                out.append(str(b["text"]))
            else:
                out.append(str(b))
        return out
    return [str(result)]


def _extract_body(blocks: list[str]) -> str:
    """Return the page body block from a getPageContent result.

    The body follows a ``📝 Content:`` marker block; in practice it is the last
    block. Prefer the block after the marker; else fall back to the last block
    that looks like markup (contains both ``<`` and ``>``); else the last block.
    """
    for i, b in enumerate(blocks):
        if "Content:" in b and i + 1 < len(blocks):
            return blocks[i + 1]
    markup = [b for b in blocks if "<" in b and ">" in b]
    if markup:
        return markup[-1]
    return blocks[-1] if blocks else ""


def get_page_content(
    page_id: str, *, config: ReportingConfig, server: McpServerSpec | None = None
) -> str:
    """Fetch a Confluence page's body (XHTML storage) via the MCP server.

    Returns the raw storage body string for `parse_okr_table`. This is the only
    place that knows the server's result shape, so a server change is a 1-function
    fix.
    """
    spec = server or config.confluence_server
    result = call_tool(spec, "getPageContent", {"pageId": page_id})
    return _extract_body(_blocks_text_list(result))


class _OkrTableParser(HTMLParser):
    """Collect rows of cell texts from the top-level ``<table>`` in the body.

    Tolerant: ignores nested formatting tags (``<strong>`` etc.), captures the
    text of each ``<td>``/``<th>``. One ``<tr>`` ⇒ one row of cell strings.

    Nested tables (a ``<table>`` inside a cell — common in Confluence storage)
    are NOT treated as new rows: while inside an open cell their ``<tr>/<td>`` are
    swallowed as part of the cell's text, so a nested table can't drop or split the
    real OKR row. Tracked via `_table_depth` / `_in_cell`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] | None = None
        # Cell nesting depth: a cell opened while already inside a cell is part of
        # a nested table; its tr/td must NOT start/close the outer row's cells.
        self._cell_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if self._in_cell:
            # Inside a cell: nested table/tr are swallowed as text; a nested td/th
            # only deepens the cell nesting so its close doesn't end the outer cell.
            if tag in ("td", "th"):
                self._cell_depth += 1
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell_depth = 1
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            self._cell_depth -= 1
            if self._cell_depth == 0 and self._row is not None:
                self._row.append("".join(self._cell_parts).strip())
                self._in_cell = False
        elif tag == "tr" and not self._in_cell and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def _is_header_row(cells: list[str]) -> bool:
    """True if a row's cells match the known OKR column titles (loose)."""
    lowered = [c.strip().lower() for c in cells]
    return sum(1 for c in lowered if c in _HEADER_CELLS) >= 2


def parse_okr_table(content: str) -> tuple[list[tuple[str, str, str, str]], list[OkrProblem]]:
    """Extract OKR rows from a Confluence page body (XHTML storage).

    Returns ``(quads, problems)`` where each quad is
    ``(objective, key_result, epic_keys_cell, weight_cell)`` — purely structural,
    no epic resolution or weight parsing (that is the analyzer's job).

    Resilience rules:
    - the header row (cells matching the known column titles) is dropped;
    - a row without the 4 logical columns becomes an `OkrProblem`, the rest still
      parse;
    - an empty Objective cell means "continuation of the Objective above" — the
      last non-empty objective is carried forward (a multi-KR objective). Only the
      FIRST data row missing an objective is a problem.
    """
    parser = _OkrTableParser()
    parser.feed(content or "")

    quads: list[tuple[str, str, str, str]] = []
    problems: list[OkrProblem] = []
    last_objective = ""

    for cells in parser.rows:
        if _is_header_row(cells):
            continue
        if len(cells) < 4:
            label = " | ".join(cells) if cells else "(hàng rỗng)"
            problems.append(OkrProblem(row=label, reason="hàng thiếu cột (cần 4 cột)"))
            continue
        objective, key_result, epic_cell, weight_cell = (c.strip() for c in cells[:4])
        if objective:
            last_objective = objective
        elif last_objective:
            objective = last_objective  # continuation row
        else:
            problems.append(
                OkrProblem(row=f"{key_result}", reason="thiếu Objective ở hàng đầu")
            )
            continue
        quads.append((objective, key_result, epic_cell, weight_cell))

    return quads, problems


def parse_epic_keys(cell: str) -> tuple[str, ...]:
    """Split an Epic Key(s) cell into valid keys (split, upper, validate, dedupe).

    Only tokens matching the ``PROJECT-123`` shape are kept — user-typed cells must
    not interpolate arbitrary text into a JQL query. Malformed tokens are dropped;
    a KR whose cell yields no valid key becomes an OkrProblem in the analyzer.
    """
    raw = (cell or "").replace(",", " ").split()
    seen: list[str] = []
    for token in raw:
        key = token.strip().upper()
        if _EPIC_KEY_RE.match(key) and key not in seen:
            seen.append(key)
    return tuple(seen)


def parse_weight(cell: str) -> float | None:
    """Parse a Weight cell. Empty ⇒ None (equal weighting). ``%`` accepted.

    Raises ValueError on a non-numeric value so the caller records an OkrProblem
    rather than silently treating it as zero.
    """
    text = (cell or "").strip()
    if not text:
        return None
    if text.endswith("%"):
        return float(text[:-1].strip()) / 100.0
    return float(text)
