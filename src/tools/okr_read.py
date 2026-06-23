"""OKR epic-progress fetch — compute each epic's progress from its child issues.

The running Jira MCP (v3.0.0) exposes no epic-progress / story-points tool, so
progress is computed in Python: query an epic's children via `enhancedSearchIssues`
(JQL ``parent = <EPIC>``, falling back to ``"Epic Link" = <EPIC>``), normalize
them with the existing `jira_read.parse_issue`, and take ``done / total``.

`compute_epic_progress` is pure (fixture-testable); the fetch functions are the
single Jira-touching entry the OKR analyzer (Slice B) consumes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.adapters.mcp_adapter import call_tool
from src.config.reporting_config import McpServerSpec, ReportingConfig
from src.tools.jira_read import is_done, parse_issue
from src.tools.models import EpicProgress, Issue

logger = logging.getLogger(__name__)

_MAX_CHILDREN = 100


def compute_epic_progress(children: list[Issue], *, epic_key: str) -> EpicProgress:
    """Compute progress (done / total) from an epic's child issues. Pure.

    `found` is True when the epic has at least one child; an epic with no children
    yields ``progress_pct=None`` (cannot divide) and ``found=False`` so the
    analyzer treats it as a problem (bad key or empty epic) rather than 0%.
    """
    total = len(children)
    if total == 0:
        return EpicProgress(epic_key=epic_key, progress_pct=None, done_count=0,
                            total_count=0, found=False)
    done = sum(1 for issue in children if is_done(issue))
    return EpicProgress(
        epic_key=epic_key,
        progress_pct=100.0 * done / total,
        done_count=done,
        total_count=total,
        found=True,
    )


def _query_children(jql: str, spec: McpServerSpec) -> list[Issue]:
    """Run an epic-children JQL and normalize the flat issue results.

    Warns if the result fills the page cap — progress would then be computed over a
    truncated child set (under-count). Epics with >100 children are out of MVP
    scope; the warning makes the silent case visible rather than wrong-and-quiet.
    """
    result = call_tool(spec, "enhancedSearchIssues", {"jql": jql, "maxResults": _MAX_CHILDREN})
    issues_raw = result.get("issues", []) if isinstance(result, dict) else []
    if len(issues_raw) >= _MAX_CHILDREN:
        logger.warning(
            "Epic-children query hit the %d cap (jql=%r); progress may be undercounted.",
            _MAX_CHILDREN, jql,
        )
    return [parse_issue(item) for item in issues_raw]


def get_epic_progress(
    epic_key: str, *, config: ReportingConfig, server: McpServerSpec | None = None
) -> EpicProgress:
    """Fetch an epic's children from Jira and compute its progress.

    Tries ``parent = <EPIC>`` first, then ``"Epic Link" = <EPIC>`` (Jira instances
    differ in which links epic children). Returns ``found=False`` when neither
    yields children — a problem row, never a raise. Adapter/transport errors from
    `call_tool` propagate (they are real failures, not "epic not found").
    """
    spec = server or config.jira_server

    children = _query_children(f"parent = {epic_key}", spec)
    if not children:
        children = _query_children(f'"Epic Link" = {epic_key}', spec)
    return compute_epic_progress(children, epic_key=epic_key)


def get_epic_progress_map(
    epic_keys: Iterable[str], *, config: ReportingConfig, server: McpServerSpec | None = None
) -> dict[str, EpicProgress]:
    """Fetch progress for each distinct epic key once (memoized within the call).

    Two KRs sharing an epic do not double-fetch. Returns key→EpicProgress; this is
    the single Jira read the analyzer consumes. `config` is forwarded to each
    per-epic fetch (this function reads no config of its own).
    """
    out: dict[str, EpicProgress] = {}
    for key in epic_keys:
        if key in out:
            continue
        out[key] = get_epic_progress(key, config=config, server=server)
    return out
