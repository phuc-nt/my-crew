"""Goal-directed replan (v75 phase 2) — autopilot rung 2 for stalled tasks.

The mechanical ladder (retry → accept/drop) never CHANGES the plan, so a task whose
plan itself is the problem (wrong split, assignee without the needed tool, dead-end
approach — the bench-3b shape) burned both rungs and stalled anyway. This rung asks
the amend LLM for a DIFFERENT approach for the still-pending tail, through the exact
machinery a CEO amendment uses: `amend_with_retries` (frozen-prefix + full-DAG
validation) → amendment draft → hash-guarded confirm → reopen. No new write path,
no new permissions — the plan-hash invariant holds because this IS the amend flow.

Fail-CLOSED by refusal (the Hermes `/goal` judge is fail-open; with real write power
we invert that): LLM error, identity proposal ("no better idea"), no pending steps,
or a lost confirm race all raise ValueError — the rung is spent, the stall and its
CEO escalation stand, and the next rung falls back to mechanical accept/drop.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_goal_replan(slots: dict[str, str]) -> str:
    """One replan attempt for a stalled task. Mirrors the `ops_stalled_task` handler
    contract (slots {"task_id"}, ValueError = refusal) so the autopilot ladder treats
    it exactly like the CEO's own one-touch handlers."""
    from my_crew.agent.task_decomposition import DecompositionError, decomposition_content_hash
    from my_crew.agent.team_task_amend_prompt import amend_with_retries
    from my_crew.agent.team_task_roster import assignable_staff
    from my_crew.runtime.office_room_append import append_office_event, room_for_task
    from my_crew.runtime.team_task_amend import full_dag_plan_hash
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    task_id = (slots.get("task_id") or "").strip()
    store = TeamTaskStore(team_tasks_db_path())
    try:
        task = store.get(task_id)
        if task is None:
            raise ValueError(f"không tìm thấy việc #{task_id}")
        if task.status != "stalled":
            raise ValueError(f"việc #{task_id} không ở trạng thái 'stalled'")
        if not any(s.status == "pending" for s in task.steps):
            raise ValueError("không còn bước chờ để chỉnh — nhường nhánh accept/drop")

        try:
            new_pending, combined, cost = amend_with_retries(
                task, _replan_request(task), assignable_staff(),
            )
        except DecompositionError as exc:
            raise ValueError(f"không soạn được kế hoạch thay thế: {exc}") from None
        if _is_identity(task, new_pending):
            # The model had no better idea. An identity swap would burn a rung while
            # changing nothing — refuse so the stall (and its escalation) stand.
            raise ValueError("đề xuất không thay đổi kế hoạch — giữ nguyên bế tắc cho CEO")

        amendment_id = store.set_amendment_draft(
            task_id,
            base_plan_hash=full_dag_plan_hash(task.steps),
            new_plan_hash=decomposition_content_hash(combined),
            new_pending_steps=new_pending,
            old_pending_step_ids=[s.step_id for s in task.steps if s.status == "pending"],
        )
        if cost:
            store.record_task_cost(task_id, decompose=cost)
        result = store.confirm_amendment(task_id, amendment_id)
        if not result.ok:
            raise ValueError(f"không áp dụng được bản chỉnh ({result.reason})")
        store.reopen_stalled(task_id)
        titles = ", ".join(f"'{d.get('title', '')}'" for d in new_pending[:4])
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="milestone",
            body={"task_id": task_id, "task_title": task.title,
                  "milestone": "plan_adjusted",
                  "message": f"Autopilot chỉnh kế hoạch sau bế tắc — bước chờ mới: {titles}."},
            also_office=True,
        )
        return f"đổi cách tiếp cận, bước chờ mới: {titles}"
    finally:
        store.close()


def _replan_request(task: Any) -> str:
    """The evidence-grounded amend instruction. `final_summary` is second-order LLM
    content (it may echo absorbed injection phrasing), so it gets the same
    `format_internal_content` wrap every prior-step text gets before re-entering a
    prompt."""
    from my_crew.tools.search_result_formatter import format_internal_content

    dead = [s for s in task.steps if s.status in ("failed", "timeout")]
    dead_txt = "; ".join(
        f"'{s.title}' ({s.status}, giao {s.assigned_to})" for s in dead[:3]
    ) or "(không có bước chết — bế tắc ở vòng soát/chất lượng)"
    summary = format_internal_content(
        (getattr(task, "final_summary", "") or "").strip()[:400],
        label="kết luận bế tắc",
    ) or "(chưa có kết luận)"
    return (
        "Việc đang BẾ TẮC sau khi đội đã thử và điều phối viên đã can thiệp hết trần. "
        f"Kết luận hiện tại:\n{summary}\nBước không hoàn thành: {dead_txt}. "
        "Hãy CHỈNH các bước còn CHỜ để vẫn đạt YÊU CẦU GỐC bằng một cách tiếp cận KHÁC: "
        "đổi cách chia bước, đổi người có công cụ phù hợp hơn, hoặc thay bước bế tắc "
        "bằng bước thay thế khả thi — tuyệt đối không lặp lại nguyên cách cũ. Nếu thật "
        "sự không có cách khả thi nào, trả về danh sách bước chờ GIỮ NGUYÊN như hiện tại."
    )


def _is_identity(task: Any, new_pending: list[dict]) -> bool:
    """True when the proposal keeps the pending tail exactly as-is (id/title/assignee/
    deps) — the model's honest "no better approach" answer, which must refuse."""
    old = {
        (s.step_id, s.title, s.assigned_to, tuple(s.deps))
        for s in task.steps if s.status == "pending"
    }
    new = {
        (str(d.get("step_id") or ""), str(d.get("title") or ""),
         str(d.get("assigned_to") or ""), tuple(d.get("deps") or ()))
        for d in new_pending
    }
    return old == new
