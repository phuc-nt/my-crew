"""Runtime fan-out rule (v34 P4) — the ticker turns a done step's split proposal into
sub rows + one gather row, exactly the way the M32 review-insert rule mints its rows.

The LLM only ever PROPOSES (a `split` list riding the same pre-work propose call the
consult block pays for — see `team_task_consult_propose`); minting rows stays the
TICKER's monopoly, validated in code:

  - 2..4 subs (single sub is pointless; parse already truncated at 4);
  - sub titles non-empty (control chars stripped);
  - assignee must be roster-ok, else it falls back to the parent's assignee;
  - hard ceiling on the task's total row count (`MAX_TASK_STEPS`) so repeated splits
    can never balloon a task.

Row shapes (all `system_inserted=1` → excluded from the plan-hash recompute, the
same Decision-A carve-out review/rework rows ride):
  - N sub rows: `step_type="work"`, `deps=[]` (ready at once — the existing parallel
    dispatcher fans them out under `team_task_concurrency`), `needs_review=False`
    (quality gating moves to the gather), `parent_step_id=<parent>`.
  - 1 gather row: `step_type="work"`, `deps=[every sub id]` — the EXISTING fan-in
    handoff (`_read_deps_handoff` concatenates all dep artifacts) feeds it every sub
    result; `needs_review` INHERITS the parent's flag (explicit opt-in through
    `insert_step`'s keyword — the merged output gets the review the parent would
    have had).

Two more pieces keep downstream steps honest:
  - `ready_pending_steps` (tick_actions) refuses to ready a step whose dep still has
    un-done fan-out children — a plan step depending on the split parent must wait
    for the subs+gather, not read the parent's "Đã chia bước" notice as content.
  - `maybe_copy_gather_results` copies a done gather's artifact onto the PARENT's
    seq (artifacts are not hashed), so those downstream steps read the real merged
    content through the dep edge they were confirmed with.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from src.runtime.office_room_append import append_office_event, room_for_task
from src.runtime.team_task_store import TeamStep, TeamTask

if TYPE_CHECKING:
    from src.agent.coordinator_graph import CoordinatorDeps, TickResult

logger = logging.getLogger(__name__)

#: Hard ceiling on a task's TOTAL step rows after a fan-out insert — the last brake
#: against repeated splits ballooning a task (plan caps at 7; reviews/reworks/subs
#: all count toward this).
MAX_TASK_STEPS = 15

_MIN_SUBS = 2
_TITLE_MAX = 200
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _fanout_children(task: TeamTask, parent_step_id: str) -> list[TeamStep]:
    """This parent's minted fan-out rows (subs + gather) — review/rework children are
    NOT fan-out (step_type != 'work')."""
    return [
        s for s in task.steps
        if s.parent_step_id == parent_step_id and s.system_inserted
        and s.step_type == "work"
    ]


def maybe_insert_fanout(deps: CoordinatorDeps, task: TeamTask) -> TickResult | None:
    """Mint sub+gather rows for the first done step carrying an unconsumed split
    proposal. Returns a TickResult when rows were minted (caller lets the next tick
    re-read the task, same contract as the review-insert rule), else None.

    Idempotency: the children's existence is the guard — deterministic step_ids
    (`<parent>-sub<i>` / `<parent>-gather`) additionally make a double insert a
    UNIQUE-constraint error rather than silent duplication.
    """
    from src.agent.coordinator_graph import TickResult

    for step in task.steps:
        if step.status != "done" or not step.split_proposal_json:
            continue
        if step.step_type != "work" or step.system_inserted:
            continue  # defense-in-depth: only original work steps fan out (depth-1)
        if _fanout_children(task, step.step_id):
            continue  # already expanded

        subs = _validated_subs(deps, task, step)
        if subs is None:
            # invalid proposal — say so in the room and let the task proceed on the
            # parent's own (notice) artifact; never stall on a bad proposal.
            append_office_event(
                room_for_task(task.id), author="coordinator", kind="milestone",
                body={"task_id": task.id, "task_title": task.title,
                      "milestone": "fanout_rejected",
                      "message": f"Đề xuất chia của bước '{step.title}' không hợp lệ "
                                 "— bỏ qua, việc chạy tiếp bình thường."},
                also_office=True,
            )
            # consume the proposal so this branch never re-fires for the same step
            deps.store.consume_split_proposal(task.id, step.step_id)
            continue

        # One transaction for the WHOLE mint (review M1): a crash between per-row
        # commits would strand subs without their gather forever (the children-exist
        # guard would refuse a re-mint), and downstream would then read the parent's
        # notice as content once the subs finished.
        rows: list[tuple[dict, bool]] = [
            ({
                "step_id": f"{step.step_id}-sub{i}", "title": sub["title"],
                "assigned_to": sub["assigned_to"], "deps": [],
                "step_type": "work", "parent_step_id": step.step_id,
                "acceptance": f"- Hoàn thành trọn vẹn phần: {sub['title']}",
            }, False)
            for i, sub in enumerate(subs, start=1)
        ]
        rows.append((
            {
                "step_id": f"{step.step_id}-gather",
                "title": f"Tổng hợp: {step.title}",
                "assigned_to": step.assigned_to,
                "deps": [f"{step.step_id}-sub{i}" for i in range(1, len(subs) + 1)],
                "step_type": "work", "parent_step_id": step.step_id,
                "acceptance": step.acceptance,
            },
            step.needs_review,
        ))
        deps.store.insert_steps_atomic(task.id, rows)
        append_office_event(
            room_for_task(task.id), author="coordinator", kind="milestone",
            body={"task_id": task.id, "task_title": task.title,
                  "milestone": "fanout_inserted",
                  "message": f"Bước '{step.title}' được chia thành {len(subs)} việc con "
                             "chạy song song + 1 bước tổng hợp."},
            also_office=True,
        )
        return TickResult(task_id=task.id, action="fanout_inserted",
                          detail=f"{step.step_id} → {len(subs)} sub + gather")
    return None


def _validated_subs(deps: CoordinatorDeps, task: TeamTask, step: TeamStep) -> list[dict] | None:
    """Code validation of the LLM's proposal — None means refuse (event + consume)."""
    try:
        raw = json.loads(step.split_proposal_json or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    subs: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _CTRL_RE.sub("", " ".join(str(item.get("title", "")).split()))[:_TITLE_MAX]
        if not title:
            continue
        assignee = str(item.get("assigned_to", "")).strip()
        if not assignee or not deps.roster_ok(assignee):
            assignee = step.assigned_to  # fallback: the parent's own assignee
        subs.append({"title": title, "assigned_to": assignee})
    if not (_MIN_SUBS <= len(subs) <= 4):
        return None
    if len(task.steps) + len(subs) + 1 > MAX_TASK_STEPS:
        return None
    # The deterministic child ids must not collide with ANY existing row (a plan
    # could legitimately contain a step named "<parent>-sub1") — collision would be
    # a per-tick IntegrityError loop, so it reads as an invalid proposal instead.
    existing = {s.step_id for s in task.steps}
    minted = {f"{step.step_id}-sub{i}" for i in range(1, len(subs) + 1)}
    minted.add(f"{step.step_id}-gather")
    if minted & existing:
        return None
    return subs


def maybe_copy_gather_results(deps: CoordinatorDeps, task: TeamTask) -> None:
    """For every DONE gather row whose parent artifact still holds the split notice:
    copy the gather's artifact onto the parent's seq, so confirmed plan steps that
    dep on the parent read the merged content, not "Đã chia bước". Idempotent via the
    `gathered_from` marker; best-effort (a failed copy retries next tick). Never
    consumes the tick (pure hygiene, returns None)."""
    from src.agent.team_task_artifact import read_step_artifact, write_step_artifact
    from src.runtime.team_task_paths import team_tasks_root

    for gather in task.steps:
        if (gather.status != "done" or not gather.system_inserted
                or gather.step_type != "work" or not gather.parent_step_id
                or not gather.deps):
            continue  # only a DONE gather (the fan-out child WITH deps) qualifies
        parent = next((s for s in task.steps if s.step_id == gather.parent_step_id), None)
        if parent is None:
            continue
        try:
            root = team_tasks_root()
            parent_artifact = read_step_artifact(root, task.id, parent.seq) or {}
            if parent_artifact.get("gathered_from") == gather.seq:
                continue  # already copied
            gather_artifact = read_step_artifact(root, task.id, gather.seq)
            if gather_artifact is None:
                continue  # gather marked done but artifact not visible yet — retry next tick
            merged = dict(gather_artifact)
            merged["gathered_from"] = gather.seq
            merged["step_title"] = parent.title
            write_step_artifact(root, task.id, parent.seq, merged)
            logger.info("fanout: gather %s result copied onto parent %s",
                        gather.step_id, parent.step_id)
        except Exception:  # noqa: BLE001 — hygiene; a failed copy retries next tick
            logger.warning("fanout: gather copy failed for %s", gather.step_id,
                           exc_info=True)
