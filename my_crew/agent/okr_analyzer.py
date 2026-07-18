"""OKR analyzer — roll up Objective/KR progress from parsed rows + epic progress.

Pure and deterministic (no network, no clock), mirroring `risk_analyzer.analyze`:
thresholds are injected, inputs are plain data, outputs are typed. A separate
analyzer (not a new Risk kind) because OKR data is `Objective`/`KeyResult`, not
`Issue`/`PullRequest`/`CiRun` — overloading the risk pipeline would force the
wrong contract.

Resilience: malformed weights, missing epic keys, and unknown epics become
`OkrProblem`s and are excluded from the rollup; the valid rows still roll up so a
bad source row never aborts the report.

Rollup rules (decisions of record, see plan phase-01/phase-02):
- A KR mapped to multiple epics aggregates by CHILD COUNT — Σdone / Σtotal across
  its found epics (not a mean of per-epic percentages), since the running Jira MCP
  has no story points. Falls back to the mean of available `progress_pct` if any
  epic lacks counts.
- An Objective's progress is the WEIGHTED average of its KR progresses using the
  Weight column. If ANY KR weight in an Objective is blank, the whole Objective
  uses equal weighting (KISS — avoids ambiguous mixed math).
- Percentages are 0..100 floats (display rounding happens in the prompt layer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from my_crew.tools.confluence_read import parse_epic_keys, parse_weight
from my_crew.tools.models import EpicProgress, KeyResult, Objective, OkrProblem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OkrRollup:
    """Result of rolling up the OKR table: objectives + problems + at-risk names."""

    objectives: tuple[Objective, ...]
    problems: tuple[OkrProblem, ...]
    at_risk: tuple[str, ...]  # names of objectives below the behind threshold


def _kr_progress(
    epic_keys: tuple[str, ...],
    epic_progress: dict[str, EpicProgress],
    *,
    row_label: str,
    problems: list[OkrProblem],
) -> float | None:
    """Aggregate one KR's progress across its epics (child-count weighted).

    Records a problem for each unknown/empty epic and excludes it. Returns None
    (KR contributes nothing to its Objective) when no epic resolves.
    """
    found = []
    for key in epic_keys:
        ep = epic_progress.get(key)
        if ep is None or not ep.found:
            problems.append(
                OkrProblem(row=row_label, reason=f"epic {key} không tồn tại / không có child")
            )
            continue
        found.append(ep)

    if not found:
        return None

    # Preferred: child-count weighting (Σdone / Σtotal) over epics that have counts.
    counted = [ep for ep in found if ep.total_count]
    if len(counted) == len(found):
        total = sum(ep.total_count for ep in counted)
        done = sum(ep.done_count or 0 for ep in counted)
        return 100.0 * done / total if total else None

    # Fallback: mean of available percentages (some epic lacked counts).
    pcts = [ep.progress_pct for ep in found if ep.progress_pct is not None]
    return sum(pcts) / len(pcts) if pcts else None


def _objective_progress(krs: list[KeyResult]) -> float | None:
    """Weighted average of a KR list's progresses; equal weighting if any blank."""
    contributing = [kr for kr in krs if kr.progress_pct is not None]
    if not contributing:
        return None
    any_blank = any(kr.weight is None for kr in contributing)
    if any_blank:
        return sum(kr.progress_pct for kr in contributing) / len(contributing)
    total_w = sum(kr.weight for kr in contributing)
    if total_w == 0:
        return sum(kr.progress_pct for kr in contributing) / len(contributing)
    return sum(kr.progress_pct * kr.weight for kr in contributing) / total_w


def build_objectives(
    raw_rows: list[tuple[str, str, str, str]],
    epic_progress: dict[str, EpicProgress],
    *,
    behind_threshold: float,
) -> OkrRollup:
    """Turn parsed OKR rows + an epic-progress map into computed Objectives.

    `raw_rows`: `(objective, key_result, epic_keys_cell, weight_cell)` quads from
    `parse_okr_table`. `behind_threshold`: fraction 0..1 — an Objective whose
    progress (as a fraction) is below this is "at risk". Rows are grouped by
    objective name in first-seen order.
    """
    problems: list[OkrProblem] = []
    # Preserve first-seen objective order while grouping their KRs.
    order: list[str] = []
    grouped: dict[str, list[KeyResult]] = {}

    for objective, key_result, epic_cell, weight_cell in raw_rows:
        row_label = f"{objective} | {key_result}"
        try:
            weight = parse_weight(weight_cell)
        except ValueError:
            problems.append(
                OkrProblem(row=row_label, reason=f"weight không hợp lệ: {weight_cell!r}")
            )
            continue

        epic_keys = parse_epic_keys(epic_cell)
        if not epic_keys:
            problems.append(OkrProblem(row=row_label, reason="thiếu Epic Key"))
            continue

        progress = _kr_progress(
            epic_keys, epic_progress, row_label=row_label, problems=problems
        )
        kr = KeyResult(
            description=key_result, epic_keys=epic_keys, weight=weight, progress_pct=progress
        )
        if objective not in grouped:
            order.append(objective)
            grouped[objective] = []
        grouped[objective].append(kr)

    objectives: list[Objective] = []
    at_risk: list[str] = []
    for name in order:
        krs = grouped[name]
        obj_progress = _objective_progress(krs)
        objectives.append(
            Objective(name=name, key_results=tuple(krs), progress_pct=obj_progress)
        )
        if obj_progress is not None and obj_progress / 100.0 < behind_threshold:
            at_risk.append(name)

    return OkrRollup(
        objectives=tuple(objectives),
        problems=tuple(problems),
        at_risk=tuple(at_risk),
    )
