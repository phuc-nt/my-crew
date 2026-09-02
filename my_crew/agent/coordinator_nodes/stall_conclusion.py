"""The one way a team task ends in failure: a delivered conclusion, never a bare stall.

Four paths stall a task: the stuck ladder giving up, a dead `failed`/`timeout` step
with no retry left, a breached cost ceiling, and a plan-hash mismatch. Only the first
used to write a `final_summary` and post it to the room; the other three flipped the
status and raised an escalation event, so the CEO saw "bị dừng" in the office feed and
NOTHING in the task's own delivery — no verdict, no salvage of the work that had
already finished. Measured on the lanes15 bench: every such task sat `stalled` with an
empty `final_summary`, and the CEO's only recourse was to read the event log.

This module makes every failure end the way `_give_up` did: headline first (the
"KHÔNG LÀM ĐƯỢC" marker is what `make_deliver_room` and the lane judge read to
classify the delivery), the best finished result attached after it, delivery recorded,
escalation raised with the same text, lesson reflected. A failure the CEO can read is
a conclusion; a status flip is not.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.agent.coordinator_graph import CoordinatorDeps, TickResult
    from my_crew.runtime.team_task_steps import TeamStep
    from my_crew.runtime.team_task_store import TeamTask

logger = logging.getLogger(__name__)

#: The bar for "this done step produced something worth handing the CEO anyway".
#: Same order of magnitude as the lane-judge's minimum-deliverable threshold (600
#: chars) but deliberately lower: salvage accompanies an honest failure note, so a
#: shorter-but-real intermediate result still beats delivering nothing.
_MIN_SALVAGE_CHARS = 400

#: Ceiling on how much salvaged text rides the delivery summary — the summary lands
#: in a chat room, not a file store, so a full report is trimmed at a line boundary
#: rather than posted wholesale.
_MAX_SALVAGE_CHARS = 6000

#: Every failure headline starts with this after the task title — the marker every
#: downstream classifier keys on (`make_deliver_room` labels the delivery failed when
#: it appears in the first 160 chars; the aggregate must NEVER emit it, since an
#: aggregated task delivered something).
FAILED_MARKER = "KHÔNG LÀM ĐƯỢC"


def best_done_result(task: TeamTask) -> tuple[str, str] | None:
    """The most-downstream substantive result this task actually produced.

    Walks the task's steps from highest `seq` down and returns `(step title,
    result_text)` for the first `done` step whose artifact carries at least
    `_MIN_SALVAGE_CHARS` of result text — or None when nothing qualifies. Highest seq
    wins because later steps consume earlier ones: a finished draft outranks the raw
    source list it was built from.
    """
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    root = team_tasks_root()
    for s in sorted(task.steps, key=lambda s: s.seq, reverse=True):
        if s.status != "done":
            continue
        artifact = read_step_artifact(root, task.id, s.seq) or {}
        text = str(artifact.get("result_text") or "").strip()
        if len(text) >= _MIN_SALVAGE_CHARS:
            return s.title, text
    return None


def failure_summary(task: TeamTask, headline: str) -> str:
    """`headline` + the best finished result, if any.

    Measured live (lanes6, team/ecommerce): a finished report sat in the step-3
    artifact while the QA step stalled the task, and the delivery carried only the
    abandonment note — the CEO never saw work that already existed. The salvage goes
    AFTER the failure line: the first sentence must keep saying the task failed
    (humans and the lane judge both read that line to classify the outcome).
    """
    salvage = best_done_result(task)
    if salvage is None:
        return headline
    salvage_title, salvage_text = salvage
    if len(salvage_text) > _MAX_SALVAGE_CHARS:
        cut = salvage_text.rfind("\n", 0, _MAX_SALVAGE_CHARS)
        salvage_text = (
            salvage_text[: cut if cut > 0 else _MAX_SALVAGE_CHARS].rstrip()
            + "\n[... đã cắt bớt cho vừa bản tin]"
        )
    return (
        f"{headline}\n\nPhần đã làm được trước khi kẹt (bước '{salvage_title}'):\n"
        f"{salvage_text}"
    )


def conclude_task_failed(
    deps: CoordinatorDeps, task: TeamTask, headline: str, *,
    step: TeamStep | None, event_kind: str, reflect_outcome: str, reflect_detail: str,
    action: str, detail: str,
) -> TickResult:
    """Stall `task` WITH a delivered conclusion.

    Order matters and mirrors the success path's delivery leg: the summary is
    persisted as `pending` first (so a crash between here and the room post still
    leaves a readable verdict on the task), the status flips to `stalled` (which
    removes the task from `list_dispatchable()`, making this run at most once per
    task), the room post decides `delivered`/`failed`, and only then does the
    escalation event fire — with the HEADLINE alone, since the CEO just received the
    full summary through the delivery and the escalation's job is the alert plus its
    one-touch follow-ups (amend, upgrade to team), not a second copy of the salvage.
    The caller's own step-level terminal write (if any) happens BEFORE this: by the
    time the conclusion lands, no step of the task is left alive.
    """
    from my_crew.agent.coordinator_graph import TickResult, _reflect_safely

    summary = failure_summary(task, headline)
    deps.store.set_delivery(task.id, status="pending", summary=summary)
    deps.store.set_task_status(task.id, "stalled")
    delivered = deps.deliver_room(task, summary) is not False
    deps.store.set_delivery(task.id, status="delivered" if delivered else "failed")
    deps.escalate(task, step, event_kind, headline)
    _reflect_safely(deps, task, reflect_outcome, reflect_detail)
    return TickResult(task_id=task.id, action=action, detail=detail[:80])
