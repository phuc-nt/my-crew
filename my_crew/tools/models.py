"""Normalized data models shared by the READ tools + risk analyzer.

Tools return these dataclasses (not raw Jira/GitHub JSON) so the LLM and the
analyzer work against a stable, tool-agnostic shape. Raw-API field mapping lives
in each `*_read.py`; everything downstream depends only on these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# --- v3 M5 S6: generic domain-neutral entities ---
# `Task`/`Event` are the cross-domain vocabulary a domain pack maps its source entity
# onto, so the core no longer assumes "Jira Issue". PM maps Issue → Task (see
# `domain_models.issue_to_task`); HR maps a headcount row, Admin a cross-agent metric.
# Field names are deliberately neutral (`id`/`title`, not `key`/`summary`) but carry the
# same semantics the analyzers need (status, assignee, due_date, labels, flagged). `kind`
# labels the domain entity ("issue", "headcount-row", ...); `extra` holds domain fields
# the generic shape doesn't name, so a pack never loses information in the mapping.


@dataclass(frozen=True)
class Task:
    """A generic unit of tracked work/record any domain pack maps its entity to."""

    id: str
    title: str
    status: str
    assignee: str | None = None
    due_date: date | None = None
    labels: tuple[str, ...] = ()
    flagged: bool = False
    kind: str = "task"  # domain label: "issue" (PM) | "headcount-row" (HR) | ...
    extra: tuple[tuple[str, str], ...] = ()  # domain-specific fields, name→value


@dataclass(frozen=True)
class Event:
    """A generic timestamped activity/occurrence (for HR/Admin timelines)."""

    id: str
    summary: str
    occurred_on: date | None = None
    actor: str | None = None
    kind: str = "event"
    extra: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Issue:
    """A normalized Jira issue."""

    key: str
    summary: str
    status: str
    assignee: str | None
    due_date: date | None
    labels: tuple[str, ...] = ()
    flagged: bool = False


@dataclass(frozen=True)
class PullRequest:
    """A normalized GitHub pull request with computed staleness."""

    number: int
    title: str
    author: str | None
    updated_at: date | None
    review_decision: str | None  # APPROVED | REVIEW_REQUIRED | CHANGES_REQUESTED | None
    checks_state: str | None  # SUCCESS | FAILURE | PENDING | None
    age_days: int | None
    stale: bool = False


@dataclass(frozen=True)
class CiRun:
    """A normalized recent CI/workflow run."""

    workflow: str
    status: str  # queued | in_progress | completed
    conclusion: str | None  # success | failure | cancelled | ...


@dataclass(frozen=True)
class Sprint:
    """A normalized Jira sprint (for weekly sprint review)."""

    id: str
    name: str
    state: str  # active | closed | future
    start_date: date | None
    end_date: date | None


@dataclass(frozen=True)
class Risk:
    """One detected risk, with a suggested action (design-guidelines: actionable)."""

    kind: str  # "overdue_task" | "stale_pr" | "blocker" | "ci_failure"
    severity: str  # "high" | "medium" | "low"
    subject: str  # e.g. issue key or PR number
    detail: str
    suggested_action: str
    refs: tuple[str, ...] = field(default_factory=tuple)


# --- Phase 3: OKR / objective tracking ---
# OKR is defined outside Jira (a Confluence table) as a 2-tier model
# (Objective → Key Results); each KR maps to one or more Jira epics. Progress is
# computed in Python from each epic's child issues (the running Jira MCP exposes
# no epic-progress tool). Percentages are stored as 0..100 floats to match how
# Jira reports progress; the prompt layer rounds for display.


@dataclass(frozen=True)
class EpicProgress:
    """An epic's progress, computed from its child issues (done / total).

    `found=False` means no children resolved in Jira (a bad key or an empty
    epic) — the analyzer turns that into a problem row, never a crash.
    `total_count == 0` ⇒ `progress_pct` is None (cannot divide).
    """

    epic_key: str
    progress_pct: float | None  # 0..100, or None when total_count == 0
    done_count: int | None
    total_count: int | None
    found: bool


@dataclass(frozen=True)
class KeyResult:
    """One Key Result of an Objective, mapped to one or more Jira epics."""

    description: str
    epic_keys: tuple[str, ...]
    weight: float | None  # None ⇒ equal weighting among the Objective's KRs
    progress_pct: float | None = None  # 0..100, rolled up from the mapped epics


@dataclass(frozen=True)
class Objective:
    """One Objective with its Key Results and a rolled-up progress %."""

    name: str
    key_results: tuple[KeyResult, ...]
    progress_pct: float | None = None  # 0..100, weighted average of its KRs


@dataclass(frozen=True)
class OkrProblem:
    """A row/epic skipped during OKR rollup, with a human-readable reason.

    Surfaced in the report ("OKR có vấn đề") so a person can fix the source
    table; a problem never aborts the report.
    """

    row: str  # short label of the offending row (e.g. "Objective | KR")
    reason: str


# --- Phase 4: Resource (capacity) + Cost reporting ---
# Capacity is computed from Jira issues grouped by assignee (the running Jira MCP
# exposes no story points). "overloaded" is RELATIVE — open_count above the team
# mean times a configurable ratio — so it self-adjusts to team size.


@dataclass(frozen=True)
class AssigneeLoad:
    """One person's workload, counted from their open (not-done) Jira issues."""

    assignee: str
    open_count: int
    overdue_count: int
    blocker_count: int
    overloaded: bool


@dataclass(frozen=True)
class ResourceReport:
    """Team workload snapshot: per-assignee loads + the overloaded set."""

    loads: tuple[AssigneeLoad, ...]
    team_mean: float  # mean open_count across assignees with load (0.0 if none)
    overloaded: tuple[str, ...]  # names flagged overloaded
    unassigned_count: int  # open issues with no assignee (not a load)


@dataclass(frozen=True)
class CostSummary:
    """Cost snapshot: real LLM budget + a labeled labor estimate.

    `llm_*` come from the existing BudgetTracker (read at the call site).
    `labor_estimate = open_issue_count × cost_per_issue` is a rough estimate;
    `cost_per_issue == 0` means it is not configured (the render omits it).
    """

    llm_spent: float
    llm_cap: float
    llm_ratio: float
    llm_status: str  # "ok" | "warn" | "over"
    labor_estimate: float
    open_issue_count: int
    cost_per_issue: float
