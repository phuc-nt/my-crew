"""team_task_create / team_task_move WRITE — kanban card actions (v31 P3).

An agent proposes a work card ("tạo việc X giao cho noi-dung") or moves one's status
("chuyển việc T sang done") through the Action Gateway: Lớp A scans the payload
(hard_block._hard_deny_team_task), Lớp B queues it in guarded mode / runs it audited
in autonomous (v30).

Permissions are STORE-VERIFIED here, never trusted from args (red-team #2, giả mạo
assignee):
- create: the assignee must be on `assignable_staff()` — the same roster gate the
  CEO's assign flow and the coordinator's dispatch re-verify use.
- move: the ACTOR (a closure over the call site's own agent id, like schedule_update —
  never a payload field) must be the task's PIC, its creator, or assigned to one of
  its steps. The target status is re-checked against the store's own status set.

A created card lands in `planning` — visible on the Việc board and the office room,
NOT dispatchable (the ticker only acts on open/running): an agent PROPOSES work, the
existing confirm/plan flow makes it runnable. Office-room events are appended fail-soft
(`append_office_event` never raises) — observability must not block the write.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

Handler = Callable[[dict[str, Any]], str]


def make_team_task_handler(actor_id: str) -> Handler:
    """Build the gateway handler bound to ONE acting agent's identity.

    `actor_id` comes from the call site's `loaded` profile (chat auto-handler,
    web/mpm approve) — the payload has no actor field to forge.
    """

    def _handler(action: dict[str, Any]) -> str:
        atype = str(action.get("type", "")).lower()
        if atype == "team_task_create":
            return _create(actor_id, action)
        if atype == "team_task_move":
            return _move(actor_id, action)
        raise PermissionError(f"team task handler refuses action type {atype!r}")

    return _handler


def _open_store():
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


def _create(actor_id: str, action: dict[str, Any]) -> str:
    title = str(action.get("title") or "").strip()
    assignee = str(action.get("assignee") or "").strip()
    if not title or not assignee:
        raise PermissionError("team_task_create refused: title and assignee are required")

    from src.agent.team_task_roster import is_assignable

    # Store-verified permission: roster membership, not payload trust. Excludes the
    # coordinator + admin by the same rule the CEO assign flow enforces.
    if not is_assignable(assignee):
        raise PermissionError(
            f"team_task_create refused: {assignee!r} không nằm trong danh sách nhân sự "
            "có thể giao việc"
        )

    task_id = uuid.uuid4().hex[:12]
    detail = str(action.get("detail") or "").strip()
    store = _open_store()
    try:
        store.create_task(
            task_id=task_id, title=title, original_request=detail or title,
            assigned_by=actor_id, pic_id=assignee,
        )
    finally:
        store.close()

    from src.runtime.office_room_append import append_office_event

    append_office_event(
        task_id, author=actor_id, kind="assignment",
        body={"text": f"{actor_id} đề xuất việc mới cho {assignee}",
              "task_title": title, "pic": assignee, "task_id": task_id},
        also_office=True,
    )
    return (f"team task created: '{title}' (id={task_id}, giao {assignee}, "
            "trạng thái planning — cần xác nhận kế hoạch để chạy)")


def _move(actor_id: str, action: dict[str, Any]) -> str:
    task_id = str(action.get("task_id") or "").strip()
    status = str(action.get("status") or "").strip()
    if not task_id or not status:
        raise PermissionError("team_task_move refused: task_id and status are required")

    store = _open_store()
    try:
        task = store.get(task_id)
        if task is None:
            raise PermissionError(f"team_task_move refused: không có việc {task_id!r}")
        # Store-verified permission: the actor must actually be a participant of THIS
        # task — its PIC, its creator, or an assignee of one of its steps.
        participants = {task.pic_id, task.assigned_by} | {
            s.assigned_to for s in task.steps
        }
        participants.discard("")
        if actor_id not in participants:
            raise PermissionError(
                f"team_task_move refused: '{actor_id}' không phải PIC/người tạo/"
                f"người nhận bước nào của việc {task_id!r}"
            )
        # A `planning` task may have a DRAFT plan awaiting the CEO's hash-bound confirm
        # (`confirm_plan` is deliberately the ONLY planning→dispatchable door — see
        # team_task_store's list_open/list_dispatchable split). Letting a participant
        # move it straight to open/running would dispatch an unconfirmed plan.
        if task.status == "planning" and status in ("open", "running"):
            raise PermissionError(
                "team_task_move refused: việc đang ở bước lập kế hoạch — phải xác nhận "
                "kế hoạch (confirm) mới chạy được, không chuyển trạng thái tay"
            )
        try:
            store.set_task_status(task_id, status)  # store re-validates the status set
        except ValueError as exc:
            raise PermissionError(f"team_task_move refused: {exc}") from None
        title = task.title
    finally:
        store.close()

    from src.runtime.office_room_append import append_office_event, room_for_task

    append_office_event(
        room_for_task(task_id), author=actor_id, kind="milestone",
        body={"milestone": status, "task_id": task_id,
              "text": f"{actor_id} chuyển '{title}' sang {status}"},
        also_office=True,
    )
    return f"team task moved: '{title}' (id={task_id}) → {status}"
