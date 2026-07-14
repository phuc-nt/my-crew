"""`assign_team_task` ops-chat command: CEO brief → decomposed DAG → confirmed team task.

Split out of `ops_catalog.py` (kept under the repo's ~200 LOC guideline) because this
command's `preview`/`run` need real collaborators (LLM, staff registry, the team-task
store) beyond a simple slot → admin-primitive call, unlike every other catalog entry.

Flow (mirrors `ops_chat.py`'s existing collect → preview → confirm state machine,
`OpsDraft.slots` is the only channel between the two calls):

  1. `preview(slots)` (called once, when the `brief` slot is finally filled): mints a
     `task_id`, runs ONE bounded decompose LLM call (retry on validation failure, capped
     — `_MAX_DECOMPOSE_ATTEMPTS`), validates the result in CODE (`validate_decomposition`),
     persists the PROPOSED plan via `TeamTaskStore.set_draft_plan` (status stays
     `planning` — not yet dispatchable), records the decompose LLM cost against the task,
     writes `task_id` + the plan's content hash into `slots` (so `run` can bind to the
     EXACT plan the CEO is about to see), and renders the full DAG as the confirmation
     text.
  2. `run(slots)` (called only after the CEO's explicit "xác nhận"): calls
     `TeamTaskStore.confirm_plan(task_id, plan_hash)` — TOCTOU-proof: it only flips the
     task to `open` (dispatchable by the coordinator ticker) if the hash still matches
     the plan `preview` persisted; it never re-decomposes or re-writes steps. A stale/
     mismatched hash reports a clean "kế hoạch đã đổi, thử lại" rather than dispatching a
     different plan than the one the CEO approved.
  3. `on_cancel(slots)` (called when the CEO's reply is NOT a confirm, i.e. "huỷ" or
     anything unclear): terminalizes the `planning` draft row via `cancel_draft` so it
     can never later be picked up by the ticker — a cancel-at-the-chat-layer alone
     (clearing only the `OpsConversationStore` draft) would leave the store's `planning`
     row abandoned but still `list_dispatchable`-invisible-yet-ticker-untouched forever;
     `cancel_draft` makes the abandonment terminal (status `cancelled`) instead of
     silently orphaned.
"""

from __future__ import annotations

import logging
import re

from src.agent.task_decomposition import (
    DecompositionError,
    parse_decomposed_task,
    validate_decomposition,
)

logger = logging.getLogger(__name__)

#: Bounded retry for a malformed/invalid decomposition (schema violation, unknown
#: assignee, cycle, step-count) — re-prompts with the validation error appended, so a
#: transient model slip self-corrects instead of failing the whole command outright.
_MAX_DECOMPOSE_ATTEMPTS = 3


def _agent_has_operator_route(agent_id: str) -> bool:
    """The agent's own `telegram.ops_operator_id` is set AND in its `chat_ids`
    allowlist (`telegram_write.send_telegram_message` refuses any chat_id outside
    `chat_ids` — configured-but-not-allowlisted would silently drop every send)."""
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        return False
    telegram = getattr(loaded.config, "telegram", None)
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        return False
    return operator in telegram.chat_ids


def _escalation_routable() -> bool:
    """True iff a `step_failed`/`step_timeout`/... escalation for THIS team task can
    actually reach the CEO on Telegram, via EITHER route `team_tick_collaborators
    .make_escalate` uses at escalation time:

    1. Fast path — the COORDINATOR agent's own Telegram binding (direct DM), or
    2. Mirror path — every escalation is also appended to the office room as a
       `milestone` event, and the admin agent's milestone-mirror pseudo-kind polls the
       room and DMs the CEO. So an enabled admin-domain agent with a working operator
       route makes escalations deliverable even when the coordinator has no bot of its
       own (the 1-click bootstrap coordinator ships without one).

    Checked at ASSIGN time (before a draft is even created) rather than discovered only
    when the first escalation silently fails days later. Hard block: a team task with
    no working escalation path at all has no safety net for a stuck/failed step.
    """
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.company import load_company
    from src.runtime.registry import load_registry

    coordinator_id = load_company().coordinator_id
    if not coordinator_id:
        return False
    if _agent_has_operator_route(coordinator_id):
        return True
    # Mirror path: any enabled admin-domain agent with a working operator route.
    for entry in load_registry():
        if not entry.enabled:
            continue
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
        except (FileNotFoundError, RuntimeError):
            continue
        if getattr(loaded, "domain", "") == "admin" and _agent_has_operator_route(entry.id):
            return True
    return False


def _build_llm():
    from src.config.config_builders import build_settings_from_env
    from src.llm.client import LlmClient

    settings = build_settings_from_env()
    return LlmClient(settings), settings


def _staff_roster() -> list[tuple[str, str]]:
    """`[(agent_id, domain), ...]` for every ENABLED registry agent eligible for a
    team-task step — see `team_task_roster.assignable_staff` for the exclusion rules
    (coordinator + admin agent are never assignable) shared with the dispatch-time
    re-check (`task_decomposition.validate_decomposition`'s docstring)."""
    from src.agent.team_task_roster import assignable_staff

    return assignable_staff()


#: v15 PIC prefix: "@<id> <việc>" — the CEO names the responsible staffer directly.
#: "@all <việc>" (or no @ at all) means "team decides": the decompose LLM proposes a
#: PIC instead (validated in code either way). Id charset mirrors registry ids.
_PIC_PREFIX_RE = re.compile(r"^@([A-Za-z0-9_.-]+)\s+(\S.*)$", re.S)


def parse_pic_prefix(brief: str) -> tuple[str, str]:
    """Split an optional leading @-mention off a CEO brief.

    Returns `(pic_requested, clean_brief)`: `"@noi-dung viết bài" -> ("noi-dung",
    "viết bài")`; `"@all ..."` and a brief with no leading @ both return `("", ...)`
    (LLM proposes the PIC). Whether `pic_requested` is actually assignable is the
    CALLER's check (roster in hand there) — this is pure text parsing."""
    m = _PIC_PREFIX_RE.match(brief.strip())
    if not m:
        return "", brief.strip()
    handle, rest = m.group(1), m.group(2).strip()
    if handle.lower() == "all":
        return "", rest
    return handle, rest


def _decompose_with_retries(
    brief: str, staff: list[tuple[str, str]], pic_requested: str = "",
) -> tuple:
    """Run the bounded decompose loop. Returns `(DecomposedTask, total_cost_usd)`.

    `pic_requested` (v15): the CEO's @-named PIC — rides into the prompt as a hard
    instruction AND into `validate_decomposition(pic_id=...)` as a code-side override
    (red-team F4: the model's own `pic_id` can never swap a CEO-named one). Blank ⇒
    the model proposes `pic_id` itself and validation runs against that proposal.

    Raises `DecompositionError` (CEO-facing message) if every attempt fails — either the
    model's output never validated, or there is no staff to assign to at all.
    """
    from src.llm.team_task_prompt import build_team_decompose_messages

    if not staff:
        raise DecompositionError("chưa có nhân sự nào để giao việc — hãy tạo agent trước")

    llm, _settings = _build_llm()
    total_cost = 0.0
    last_error = ""
    for _attempt in range(_MAX_DECOMPOSE_ATTEMPTS):
        messages = build_team_decompose_messages(
            brief=brief, staff=staff, retry_error=last_error, pic_requested=pic_requested,
        )
        result = llm.complete(messages)
        if result.cost_usd:
            total_cost += result.cost_usd
        try:
            task = parse_decomposed_task(result.content)
            task = validate_decomposition(
                task, staff_ids={a for a, _ in staff},
                pic_id=pic_requested if pic_requested else None,
            )
            # v15 acceptance (review M1): every NEW task gets a PIC — when the CEO
            # didn't @-name one, the model MUST propose it; an empty pic_id would
            # silently skip every PIC rule. Enforced here (not inside
            # validate_decomposition) because the amend path legitimately validates
            # pre-v15 tasks whose pic_id is "".
            if not task.pic_id:
                raise DecompositionError(
                    "thiếu pic_id — phải chọn MỘT nhân sự chịu trách nhiệm chính (PIC)"
                )
            return task, total_cost
        except DecompositionError as exc:
            last_error = str(exc)
            logger.warning("assign_team_task decompose attempt failed: %s", exc)
    raise DecompositionError(f"không phân rã được kế hoạch hợp lệ sau {_MAX_DECOMPOSE_ATTEMPTS} "
                             f"lần thử: {last_error}")


def _render_plan(task) -> str:
    lines = ["Kế hoạch phân rã:"]
    for step in task.steps:
        deps_txt = f" (sau: {', '.join(step.deps)})" if step.deps else ""
        lines.append(f"- [{step.step_id}] {step.title} → {step.assigned_to}{deps_txt}")
    return "\n".join(lines)


def preview_assign_team_task(slots: dict[str, str]) -> str:
    """Decompose the brief, persist the DRAFT plan, and render the full-DAG preview."""
    import uuid

    from src.agent.task_decomposition import decomposition_content_hash
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    brief = slots.get("brief", "").strip()
    if not brief:
        raise ValueError("cần mô tả việc cần giao")

    if not _escalation_routable():
        raise ValueError(
            "chưa có đường báo cáo sự cố (Telegram) — cần MỘT trong hai: (a) agent "
            "điều phối có ops_operator_id nằm trong chat_ids của chính nó, hoặc (b) "
            "một agent quản trị (domain admin) đang bật có ops_operator_id hợp lệ để "
            "mirror phòng làm việc chuyển tin. Thiết lập xong hãy giao việc lại."
        )

    # v15: optional "@<id> " / "@all " PIC prefix on the brief.
    pic_requested, clean_brief = parse_pic_prefix(brief)
    staff = _staff_roster()
    if pic_requested and not any(a == pic_requested for a, _ in staff):
        raise ValueError(
            f"@{pic_requested} không có trong danh sách nhân sự có thể giao việc — "
            "kiểm tra lại mã nhân sự (hoặc dùng @all để đội tự chọn người chịu trách nhiệm)"
        )
    try:
        task, decompose_cost = _decompose_with_retries(clean_brief, staff, pic_requested)
    except DecompositionError as exc:
        raise ValueError(str(exc)) from None

    task_id = uuid.uuid4().hex[:12]
    plan_hash = decomposition_content_hash(task)
    step_dicts = [
        {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
         "deps": list(s.deps), "acceptance": s.acceptance,
         "step_type": s.step_type, "needs_review": s.needs_review,
         "needs_shell": s.needs_shell}  # v45 tier-0 routing
        for s in task.steps
    ]

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.create_task(task_id=task_id, title=clean_brief[:120], original_request=brief,
                          assigned_by="ceo-chat", pic_id=task.pic_id,
                          room_id=slots.get("room_id", "").strip())
        store.set_draft_plan(task_id, step_dicts, plan_hash)
        if decompose_cost:
            store.record_task_cost(task_id, decompose=decompose_cost)
    finally:
        store.close()

    # Bind the CEO's later confirm to THIS exact plan — see module docstring.
    slots["task_id"] = task_id
    slots["plan_hash"] = plan_hash
    slots["pic_id"] = task.pic_id

    # Room event: the CEO's brief, appended to the (not-yet-dispatchable) task's own
    # room — try/degrade (a failed append must never block the preview/confirm flow).
    from src.runtime.office_room_append import append_office_event, room_for_task

    append_office_event(room_for_task(task_id), author="ceo", kind="ceo", body={"text": brief})

    pic_line = f"\nPIC (chịu trách nhiệm chính): {task.pic_id}" if task.pic_id else ""

    # v15 auto-confirm (Decision Q1 + red-team F3/F9): when the company flag is on,
    # confirm the JUST-previewed plan immediately with the SAME hash-bind path the CEO's
    # manual "xác nhận" uses — nothing about the bind/audit/room-event trail changes,
    # only who presses the button. `auto_confirmed` in slots tells the ops-chat state
    # machine NOT to park an awaiting_confirm draft (no ghost "huỷ/xác nhận" turn).
    from src.runtime.company import load_company

    # getattr-default: pre-v15 Company doubles (tests) and any stale cached shape
    # simply mean "flag off" — the safe branch.
    if getattr(load_company(), "team_task_auto_confirm", False) \
            and not slots.get("no_auto_confirm"):
        # `no_auto_confirm` (v16 red-team M3): an LLM-classified chat intent may reuse
        # this preview but must NEVER inherit the auto-confirm privilege — only the
        # CEO's explicit hard-prefix commands (@/giao/chỉnh, or the composer button
        # flow) are allowed to skip the manual confirm.
        try:
            run_text = run_assign_team_task(slots)
        except Exception as exc:  # noqa: BLE001 — ANY auto-run failure (stale hash
            # ValueError, sqlite OperationalError, ...) must terminalize the planning
            # draft instead of orphaning it, then surface as a clean reply (F9).
            cancel_assign_team_task(slots)
            raise ValueError(f"tự xác nhận thất bại: {exc}") from None
        slots["auto_confirmed"] = "1"
        return (f"{_render_plan(task)}{pic_line}\n\nMã việc: {task_id}\n"
                f"ĐÃ TỰ XÁC NHẬN (chế độ tự xác nhận đang bật) — {run_text}")

    return (f"{_render_plan(task)}{pic_line}\n\nMã việc: {task_id}\n"
            "Xác nhận giao việc này cho đội? (trả lời: xác nhận / huỷ)")


def run_assign_team_task(slots: dict[str, str]) -> str:
    """Confirm-time: flip the EXACT previewed plan to `open` — never re-decompose."""
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    task_id = slots.get("task_id", "")
    plan_hash = slots.get("plan_hash", "")
    if not task_id or not plan_hash:
        raise ValueError("thiếu thông tin kế hoạch — hãy thử giao việc lại từ đầu")

    store = TeamTaskStore(team_tasks_db_path())
    try:
        confirmed = store.confirm_plan(task_id, plan_hash)
        task = store.get(task_id) if confirmed else None
    finally:
        store.close()
    if not confirmed:
        raise ValueError("kế hoạch đã thay đổi hoặc hết hạn — hãy thử giao việc lại từ đầu")

    # Room events: the confirmed DAG (assignment) + a milestone ("task received") — both
    # try/degrade, appended AFTER the store confirm so a failed append never undoes the
    # actual dispatch decision.
    from src.runtime.office_room_append import append_office_event, room_for_task

    if task is not None:
        assignees = ", ".join(sorted({s.assigned_to for s in task.steps}))
        summary = f"Phân công: {assignees}"
        if task.pic_id:
            summary = f"PIC: {task.pic_id} — {summary}"
        # `pic`/`task_id` ride in the body (v15) so the FE can badge the PIC's desk and
        # later clear it on this task's `milestone: done` event (red-team F6 contract).
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="assignment",
            body={"task_title": task.title, "step_count": len(task.steps),
                  "summary": summary, "pic": task.pic_id, "task_id": task_id},
            also_office=True,
        )
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="milestone",
            body={"task_id": task_id, "task_title": task.title, "milestone": "received",
                  "message": f"Đội đã nhận việc '{task.title}' ({len(task.steps)} bước)."},
            also_office=True,
        )
    return f"Đã giao việc #{task_id} cho đội — điều phối viên sẽ bắt đầu phân công."


def cancel_assign_team_task(slots: dict[str, str]) -> None:
    """`on_cancel` hook: the CEO declined/never confirmed the previewed plan.

    A missing `task_id` (preview never ran, or already cleared) is a silent no-op —
    there is nothing to cancel. `TeamTaskStore.cancel_draft` itself only terminalizes a
    row still in `planning`, so a race where `run_assign_team_task` already confirmed
    it (the CEO somehow both confirmed and this hook fired) is also a safe no-op.
    """
    task_id = slots.get("task_id", "")
    if not task_id:
        return
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.cancel_draft(task_id)
    finally:
        store.close()
