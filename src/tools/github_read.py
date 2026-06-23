"""GitHub READ tool — pull PRs + CI via `gh`, normalized to models.

Runs `gh ... --json ...` through `cli_adapter` and maps the JSON into
`PullRequest` / `CiRun`. Staleness is computed here (gh has no native flag).
The raw→model mapping is pure (`parse_pr` / `parse_ci`) for unit testing.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from src.adapters.cli_adapter import run_gh
from src.config.reporting_config import ReportingConfig
from src.tools.models import CiRun, PullRequest

logger = logging.getLogger(__name__)

_PR_FIELDS = "number,title,author,createdAt,updatedAt,reviewDecision,statusCheckRollup"
_RUN_FIELDS = "workflowName,status,conclusion,createdAt"


def _parse_dt(raw: Any) -> date | None:
    """Parse an ISO-8601 timestamp ('...Z') to a date, or None."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _rollup_state(rollup: Any) -> str | None:
    """Reduce statusCheckRollup to one state: FAILURE > PENDING > SUCCESS."""
    if not isinstance(rollup, list) or not rollup:
        return None
    states = set()
    for check in rollup:
        if not isinstance(check, dict):
            continue
        # GitHub mixes 'conclusion' (checks) and 'state' (statuses).
        val = (check.get("conclusion") or check.get("state") or "").upper()
        if val:
            states.add(val)
    if {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED"} & states:
        return "FAILURE"
    if {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED"} & states:
        return "PENDING"
    if states:
        return "SUCCESS"
    return None


def _safe_int(value: Any) -> int:
    """Coerce to int, 0 on failure — matches the tolerant posture of other parsers."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_pr(raw: dict[str, Any], *, today: date, stale_days: int) -> PullRequest:
    """Map one raw gh PR object to a normalized PullRequest with staleness."""
    updated = _parse_dt(raw.get("updatedAt"))
    age_days = (today - updated).days if updated else None
    author_obj = raw.get("author") or {}
    return PullRequest(
        number=_safe_int(raw.get("number", 0)),
        title=str(raw.get("title") or ""),
        author=(author_obj.get("login") if isinstance(author_obj, dict) else None),
        updated_at=updated,
        review_decision=(raw.get("reviewDecision") or None),
        checks_state=_rollup_state(raw.get("statusCheckRollup")),
        age_days=age_days,
        stale=(age_days is not None and age_days > stale_days),
    )


def parse_ci(raw: dict[str, Any]) -> CiRun:
    """Map one raw gh run object to a normalized CiRun."""
    return CiRun(
        workflow=str(raw.get("workflowName") or ""),
        status=str(raw.get("status") or ""),
        conclusion=(raw.get("conclusion") or None),
    )


def _today_utc() -> date:
    return datetime.now(UTC).date()


def get_open_prs(
    repo: str | None = None,
    *,
    config: ReportingConfig,
    today: date | None = None,
    stale_days: int | None = None,
) -> list[PullRequest]:
    """Fetch open PRs for a repo and normalize them with staleness."""
    target = repo or config.github_repo
    if not target:
        raise RuntimeError("GITHUB_REPO is not set (in .env or passed explicitly).")
    ref_today = today or _today_utc()
    days = stale_days if stale_days is not None else config.pr_stale_days

    rows = run_gh(
        ["pr", "list", "--repo", target, "--state", "open", "--json", _PR_FIELDS, "--limit", "100"]
    )
    if not isinstance(rows, list):
        return []
    return [parse_pr(row, today=ref_today, stale_days=days) for row in rows]


def get_recent_ci(
    repo: str | None = None, *, config: ReportingConfig, limit: int = 20
) -> list[CiRun]:
    """Fetch recent workflow runs for a repo and normalize them."""
    target = repo or config.github_repo
    if not target:
        raise RuntimeError("GITHUB_REPO is not set (in .env or passed explicitly).")
    rows = run_gh(
        ["run", "list", "--repo", target, "--json", _RUN_FIELDS, "--limit", str(limit)]
    )
    if not isinstance(rows, list):
        return []
    return [parse_ci(row) for row in rows]
