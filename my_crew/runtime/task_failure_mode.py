"""One fixed tag for every way a team task can end without a deliverable.

The ticker already tells the CEO *that* a task stopped, with an `event_kind` chosen
by whichever node gave up. Those kinds are named after the code path that fired
("task_stalled_dead_step", "gave_up"), so counting them tells you which node
tripped, not what went wrong for the CEO. The escalation stamps one of the modes
below onto the task's route record instead, and `route_stats` counts that: a
stable vocabulary the retro can be read against release after release.

The grouping follows the MAST taxonomy of multi-agent failures — did the crew misread
the brief (`spec`), did the checker and the worker never converge (`verification`),
or did the machinery run out of road (`system`)? A release whose stalls are mostly
`verification` needs a better rubric; one whose stalls are mostly `system` needs a
bigger budget. The counts cannot say which without the group.
"""

from __future__ import annotations

#: `event_kind` the ticker escalates with → failure mode. Only TERMINAL kinds appear:
#: an escalation that puts the step back to pending (`stuck`, `step_failed`) is not a
#: failure of the task yet, and stamping it would count tasks that later finished.
_MODE_FOR_EVENT: dict[str, str] = {
    "cost_cap_exceeded": "cost_cap",
    "plan_hash_mismatch": "plan_mismatch",
    "review_rounds_exhausted": "verification_exhausted",
    "task_stalled_dead_step": "dead_step",
    "gave_up": "step_exhausted",
}

#: Failure mode → MAST group. `spec` = the plan or brief was wrong for the work;
#: `verification` = the work never satisfied its checker; `system` = a budget or
#: retry ceiling ended the task before either question was settled.
FAILURE_MODE_GROUP: dict[str, str] = {
    "cost_cap": "system",
    "plan_mismatch": "spec",
    "verification_exhausted": "verification",
    "dead_step": "system",
    "step_exhausted": "system",
}

#: Every mode `failure_mode_for` can return, in the order the retro lists them.
FAILURE_MODES: tuple[str, ...] = tuple(FAILURE_MODE_GROUP)

#: Reader-facing labels (Vietnamese is the user-facing layer; ids stay English).
FAILURE_MODE_LABELS: dict[str, str] = {
    "cost_cap": "vượt trần chi phí",
    "plan_mismatch": "kế hoạch bị đổi giữa chừng",
    "verification_exhausted": "soát mãi không đạt",
    "dead_step": "một bước chết kéo cả việc",
    "step_exhausted": "hết lượt thử ở một bước",
}

GROUP_LABELS: dict[str, str] = {
    "spec": "đề/kế hoạch",
    "verification": "kiểm chứng",
    "system": "hệ thống",
}


def failure_mode_for(event_kind: str) -> str | None:
    """The failure mode a terminal `event_kind` maps to, or None for anything else.

    None is the common case and means "write nothing": step-level rulings, unknown
    kinds and blank input all fall through, so a caller never has to know the list
    of terminal kinds to use this safely.
    """
    return _MODE_FOR_EVENT.get(str(event_kind or "").strip())


def failure_group_for(mode: str) -> str | None:
    """MAST group of a failure mode; None for a mode this release does not know
    (a route stamped by a newer release must still count under its raw name)."""
    return FAILURE_MODE_GROUP.get(str(mode or "").strip())
