"""`adjust_team_task` ops-chat command: full replan of a team task's PENDING tail.

Mirrors `ops_assign_team_task.py`'s preview -> confirm -> cancel state machine exactly,
but operates on an EXISTING task's DAG instead of minting a new one:

  1. `preview_adjust_team_task(slots)` (called once, when `task_id` + `yêu cầu` are both
     filled): loads the task's current DAG, runs ONE bounded amend LLM call (retry
     capped — `team_task_amend_prompt.amend_with_retries`), validates the RESULTING
     full DAG (kept done/running/failed steps + the LLM's new pending steps) through
     the SAME `validate_decomposition` decompose uses (bounds/acyclic/authz — no
     separate amend-specific validator needed), and persists a SINGLE-slot draft via
     `TeamTaskStore.set_amendment_draft` binding `base_plan_hash` to the task's
     FULL-DAG hash (`team_task_amend.full_dag_plan_hash`, not the confirmed-subset hash
     `coordinator_graph._verify_plan_hash` uses) — see that function's docstring for why
     the amend TOCTOU guard needs the wider hash. Renders a diff (giữ/bỏ/thêm) for the
     CEO to confirm.
  2. `run_adjust_team_task(slots)` (called only after the CEO's explicit "xác nhận"):
     calls `TeamTaskStore.confirm_amendment(task_id, amendment_id)` — the ONE `BEGIN
     IMMEDIATE` transaction that re-validates the draft is still live AND the DAG has
     not changed since draft time, swaps only the pending tail, binds the new plan
     hash, and consumes the draft. A rejection (`ConfirmAmendmentResult.ok=False`)
     never partially applies anything; it reports a friendly Vietnamese message keyed
     off `reason` and tells the CEO to re-run the command (fresh preview).
  3. `cancel_adjust_team_task(slots)` (CEO replies anything other than a confirm):
     terminalizes the draft via `cancel_amendment_draft` so an abandoned amend can
     never later be confirmed against a DAG the CEO stopped reviewing.

Done/running/failed steps are FROZEN by construction: the amend LLM only ever sees
their `step_id`/`title`/`assigned_to`/`status` (never their result text — the amend
context stays small and the completed-prefix is read-only context, not something the
model is asked to reproduce), and `validate_decomposition`/the swap itself only ever
touches the pending tail.
"""

from __future__ import annotations

from my_crew.agent.task_decomposition import DecompositionError
from my_crew.agent.team_task_amend_prompt import amend_with_retries

#: `ConfirmAmendmentResult.reason` -> CEO-facing Vietnamese message. Every reason
#: `confirm_amendment` can return must have an entry here (a missing one falls back to
#: a generic message below, never a raw internal reason string).
_REASON_MESSAGES = {
    "amendment_not_found": "không tìm thấy bản chỉnh — hãy thử chỉnh kế hoạch lại từ đầu",
    "amendment_not_live": "bản chỉnh đã dùng/huỷ/hết hạn — hãy thử chỉnh kế hoạch lại từ đầu",
    "plan_changed_since_draft": "kế hoạch đã đổi từ lúc xem — hãy xem lại và xác nhận lại",
    "pending_step_just_reserved": "có bước vừa bắt đầu chạy — hãy xem lại và xác nhận lại",
}


def _staff_roster() -> list[tuple[str, str]]:
    from my_crew.agent.team_task_roster import assignable_staff

    return assignable_staff()


def _render_diff(task, new_pending: list[dict]) -> str:
    lines = ["Kế hoạch chỉnh sửa:"]
    for s in task.steps:
        if s.status == "pending":
            lines.append(f"- bỏ [{s.step_id}] {s.title} → {s.assigned_to}")
        else:
            lines.append(f"- giữ [{s.step_id}] {s.title} → {s.assigned_to} ({s.status})")
    for s in new_pending:
        deps_txt = f" (sau: {', '.join(s['deps'])})" if s["deps"] else ""
        lines.append(f"- thêm [{s['step_id']}] {s['title']} → {s['assigned_to']}{deps_txt}")
    return "\n".join(lines)


def preview_adjust_team_task(slots: dict[str, str]) -> str:
    """Load the current DAG, run the amend LLM call, validate, persist the draft."""
    from my_crew.agent.task_decomposition import decomposition_content_hash
    from my_crew.runtime.team_task_amend import full_dag_plan_hash
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    task_id = slots.get("task_id", "").strip()
    request = slots.get("yêu cầu", "").strip()
    if not task_id or not request:
        raise ValueError("cần mã việc và yêu cầu chỉnh sửa")

    store = TeamTaskStore(team_tasks_db_path())
    try:
        task = store.get(task_id)
        if task is None:
            raise ValueError(f"không tìm thấy việc #{task_id}")
        if not any(s.status == "pending" for s in task.steps):
            raise ValueError(f"việc #{task_id} không còn bước nào đang chờ để chỉnh")

        staff = _staff_roster()
        try:
            new_pending, combined, amend_cost = amend_with_retries(task, request, staff)
        except DecompositionError as exc:
            raise ValueError(str(exc)) from None

        base_hash = full_dag_plan_hash(task.steps)
        old_pending_ids = [s.step_id for s in task.steps if s.status == "pending"]
        new_hash = decomposition_content_hash(combined)

        amendment_id = store.set_amendment_draft(
            task_id, base_plan_hash=base_hash, new_plan_hash=new_hash,
            new_pending_steps=new_pending, old_pending_step_ids=old_pending_ids,
        )
        if amend_cost:
            store.record_task_cost(task_id, decompose=amend_cost)
    finally:
        store.close()

    slots["amendment_id"] = amendment_id

    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    append_office_event(room_for_task(task_id), author="ceo", kind="ceo", body={"text": request})

    return (f"{_render_diff(task, new_pending)}\n\nMã việc: {task_id}\n"
            "Xác nhận chỉnh kế hoạch này? (trả lời: xác nhận / huỷ)")


def run_adjust_team_task(slots: dict[str, str]) -> str:
    """Confirm-time: re-validate + swap the EXACT previewed draft — never re-amend."""
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    task_id = slots.get("task_id", "").strip()
    amendment_id = slots.get("amendment_id", "")
    if not task_id or not amendment_id:
        raise ValueError("thiếu thông tin bản chỉnh — hãy thử chỉnh kế hoạch lại từ đầu")

    store = TeamTaskStore(team_tasks_db_path())
    try:
        result = store.confirm_amendment(task_id, amendment_id)
        task = store.get(task_id) if result.ok else None
    finally:
        store.close()

    if not result.ok:
        raise ValueError(_REASON_MESSAGES.get(result.reason, "không áp dụng được bản chỉnh"))

    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    if task is not None:
        pending = [s.step_id for s in task.steps if s.status == "pending"]
        pending_txt = ", ".join(pending) or "(không)"
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="milestone",
            body={"task_id": task_id, "task_title": task.title, "milestone": "plan_adjusted",
                  "message": f"Kế hoạch đã chỉnh — bước chờ mới: {pending_txt}"},
            also_office=True,
        )
    return f"Đã chỉnh kế hoạch việc #{task_id}."


def cancel_adjust_team_task(slots: dict[str, str]) -> None:
    """`on_cancel` hook: the CEO declined/never confirmed the previewed amendment."""
    amendment_id = slots.get("amendment_id", "")
    if not amendment_id:
        return
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.cancel_amendment_draft(amendment_id)
    finally:
        store.close()
