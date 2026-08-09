"""CEO chat-ops command catalog (v6 M14). The hard ceiling of what chat can administer.

Like the M12 chat-command catalog, this is CODE, not prompt: the LLM only fills slots,
CODE validates them and calls the existing admin primitives. The catalog here is fixed
in core (not pack-contributed) — administering the fleet is a platform concern, not a
domain one. NO destructive command is declared (no delete-agent via chat — M14 decision),
so a prompt-injected "xóa hết agent" has no catalog entry to hit.

Each command:
- `description`: shown to the CEO when listing / when a command is unsupported.
- `slots`: ordered {name: {prompt, required, ...}} — the engine asks for each missing
  required slot one at a time (slot-filling). A slot rule mirrors M12's arg schema
  (required / max_len / pattern / choices).
- `run(slots)`: CODE that performs the admin write AFTER the CEO confirms. Returns a
  human summary string. Raises ValueError with a user-facing message on a bad slot value
  the schema could not catch (e.g. unknown domain).
- `preview(slots)`: the confirmation text shown before `run` — the CEO sees exactly what
  will change.
- `readonly`: True for status/cost queries — these skip the confirm step (no write).
"""

from __future__ import annotations

from typing import Any

from my_crew.agent.ops_adjust_team_task import (
    cancel_adjust_team_task,
    preview_adjust_team_task,
    run_adjust_team_task,
)
from my_crew.agent.ops_approvals import (
    preview_approve_pending_action,
    preview_reject_pending_action,
    run_approve_pending_action,
    run_list_approvals,
    run_reject_pending_action,
)
from my_crew.agent.ops_assign_team_task import (
    cancel_assign_team_task,
    preview_assign_team_task,
    run_assign_team_task,
)
from my_crew.agent.ops_autopilot import (
    preview_set_autopilot,
    run_get_autopilot,
    run_set_autopilot,
)
from my_crew.agent.ops_calendar_event import (
    preview_create_calendar_event,
    run_create_calendar_event,
)
from my_crew.agent.ops_company_activity import run_company_activity
from my_crew.agent.ops_heartbeat_cmds import (
    preview_add_heartbeat_watch,
    preview_enable_heartbeat,
    preview_stop_heartbeat_watch,
    run_add_heartbeat_watch,
    run_enable_heartbeat,
    run_stop_heartbeat_watch,
)
from my_crew.agent.ops_list_lessons import run_list_lessons
from my_crew.agent.ops_list_team_tasks import run_list_team_tasks
from my_crew.agent.ops_send_message import preview_send_message, run_send_message
from my_crew.agent.ops_stalled_task import (
    preview_accept_stalled_result,
    preview_drop_stalled_step,
    preview_retry_stalled_step,
    run_accept_stalled_result,
    run_drop_stalled_step,
    run_retry_stalled_step,
)

#: An agent whose work comes only from `assign_team_task` (e.g. office roles) has no
#: report kind of its own — the CEO says this instead of a report-kind list.
_NO_REPORTS_WORDS = frozenset({"không", "khong", "none", "no", "-", ""})


def _parse_reports(raw: str) -> list[str]:
    if raw.strip().lower() in _NO_REPORTS_WORDS:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _run_create_agent(slots: dict[str, str]) -> str:
    """Create an agent via the SAME primitive the web wizard uses (agent_create)."""
    from my_crew.server import agent_create

    spec: dict[str, Any] = {
        "id": slots["id"],
        "name": slots.get("name") or slots["id"],
        "domain": slots["domain"],
        "reports": _parse_reports(slots.get("reports", "")),
    }
    jira_key = slots.get("jira_project_key")
    if jira_key:
        spec["bindings"] = {"jira": {"project_key": jira_key}}
    try:
        created = agent_create.create_agent(spec)
    except agent_create.ValidationError as exc:
        raise ValueError(f"cấu hình chưa hợp lệ: {exc}") from None
    except agent_create.ConflictError as exc:
        raise ValueError(f"trùng agent: {exc}") from None
    return (
        f"Đã tạo agent '{created['id']}' (domain {created['domain']}, "
        f"báo cáo: {', '.join(created['reports'])}). Nhớ điền token vào .env trước khi bật chạy."
    )


def _preview_create_agent(slots: dict[str, str]) -> str:
    reports_text = ", ".join(_parse_reports(slots.get("reports", "")))
    lines = [
        "Mình sẽ TẠO một agent mới:",
        f"- Mã (id): {slots['id']}",
        f"- Tên: {slots.get('name') or slots['id']}",
        f"- Vai trò (domain): {slots['domain']}",
        f"- Báo cáo: {reports_text or '(không có — nhận việc qua giao việc)'}",
    ]
    if slots.get("jira_project_key"):
        lines.append(f"- Jira project: {slots['jira_project_key']}")
    lines.append("\nXác nhận tạo? (trả lời: xác nhận / huỷ)")
    return "\n".join(lines)


def _state_is_on(state: str) -> bool:
    """The `state` slot is normalized to 'on'/'off' by the choices map before it reaches here."""
    return state.strip().lower() == "on"


def _run_set_enabled(slots: dict[str, str]) -> str:
    from my_crew.runtime.registry_edit import UnknownRegistryAgentError, set_registry_enabled

    on = _state_is_on(slots["state"])
    try:
        set_registry_enabled(None, slots["agent_id"], on)
    except UnknownRegistryAgentError:
        raise ValueError(f"không có agent '{slots['agent_id']}' trong registry") from None
    return f"Đã {'BẬT' if on else 'TẮT'} agent '{slots['agent_id']}'."


def _preview_set_enabled(slots: dict[str, str]) -> str:
    on = _state_is_on(slots["state"])
    return (f"Mình sẽ {'BẬT' if on else 'TẮT'} agent '{slots['agent_id']}'.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def _run_get_cost(slots: dict[str, str]) -> str:
    """Read-only fleet cost rollup from the generic accessor (M8 data — plain dicts)."""
    from my_crew.runtime.agent_state_reader import read_all_agent_states

    states = read_all_agent_states()
    if not states:
        return "Chưa có agent nào để tính chi phí."
    lines = ["Chi phí LLM tháng này theo agent:"]
    total = 0.0
    for st in states:
        spent = float(st.get("budget_spent_usd") or 0.0)
        total += spent
        cap = st.get("budget_cap_usd") or 0.0
        cap_txt = f"/${cap:.0f}" if cap else ""
        lines.append(f"- {st.get('agent_id', '?')}: ${spent:.4f}{cap_txt}")
    lines.append(f"Tổng: ${total:.4f}")
    return "\n".join(lines)


def _run_get_status(slots: dict[str, str]) -> str:
    """Read-only fleet status: agent count, enabled, pending approvals, alerts."""
    from my_crew.runtime.agent_state_reader import read_all_agent_states, team_alerts

    states = read_all_agent_states()
    if not states:
        return "Chưa có agent nào."
    lines = [f"Đội hiện có {len(states)} agent:"]
    for st in states:
        pend = len(st.get("pending_approvals") or [])
        pend_txt = f", {pend} việc chờ duyệt" if pend else ""
        on = "bật" if st.get("enabled") else "tắt"
        lines.append(f"- {st.get('agent_id', '?')} ({on}){pend_txt}")
    alerts = team_alerts(states)
    if alerts:
        lines.append(f"\n⚠️ {len(alerts)} cảnh báo — xem /approvals & dashboard.")
    # v63: team tasks waiting on a decision (stalled / draft never confirmed) belong in
    # the one status answer the CEO actually asks for — best-effort, a store hiccup
    # must never break the fleet status itself.
    try:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        tstore = TeamTaskStore(team_tasks_db_path())
        try:
            # Stalled: uncapped (list_stalled — an old stalled task must never fall
            # off the count); planning drafts: recent-only is fine, drafts are new by
            # nature (they expire into cancel/confirm within a conversation).
            stalled = tstore.list_stalled()
            drafts = [t for t in tstore.list_recent_tasks(limit=50, include_planning=True)
                      if t.status == "planning"]
            waiting = stalled + drafts
        finally:
            tstore.close()
        if waiting:
            lines.append(f"\n⏳ {len(waiting)} thẻ việc nhóm đang chờ quyết định — "
                         "xem `list_team_tasks`.")
    except Exception:  # noqa: BLE001 — status must render even if the team store is unavailable
        pass
    return "\n".join(lines)


def _run_search_history(slots: dict[str, str]) -> str:
    """v33 P5: read-only search over the team's past work (steps + audit) with cited
    sources — the CEO's "tuần trước team làm/quyết gì?" answer path."""
    from my_crew.runtime.history_search_index import HistorySearchIndex

    query = (slots.get("query") or "").strip()
    if not query:
        return "Cần từ khoá để tìm."
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        hits = idx.search(query)
    finally:
        idx.close()
    if not hits:
        return f"Không tìm thấy gì về “{query}” trong lịch sử làm việc."
    lines = [f"Tìm thấy {len(hits)} kết quả về “{query}”:"]
    for h in hits:
        where = (f"việc {h['ref'].split(':')[0][:12]}" if h["source"] == "step"
                 else "nhật ký hành động")
        lines.append(f"- [{h['ts'][:10]} · {h['agent_id']} · {where}] {h['excerpt'][:220]}")
    lines.append("Xem đầy đủ trong trang Kết quả.")
    return "\n".join(lines)


def _task_store_for(agent_id: str):
    """Open the assigned-task store for one agent. Raises ValueError if the agent is
    unknown, so the ops reply is a clean message rather than a 500."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.task_scheduling import _store_path
    from my_crew.runtime.task_store import TaskStore

    try:
        load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        # Wrap, don't interpolate: a FileNotFoundError carries the full profile PATH, which
        # should not leak into a chat reply (M2). The id alone is enough for the operator.
        raise ValueError(f"không tìm thấy agent '{agent_id}'") from None
    return TaskStore(_store_path(agent_data_dir(agent_id)))


def _run_watch_pr(slots: dict[str, str]) -> str:
    """Assign a watch-task: agent tracks a PR until it merges/closes, reminding on cadence."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    agent_id = slots["agent_id"]
    try:
        number = int(slots["pr_number"])
    except (KeyError, ValueError):
        raise ValueError("số PR không hợp lệ") from None
    loaded = None
    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise ValueError(f"không tìm thấy agent '{agent_id}'") from None
    if not loaded.config.github_repo:
        raise ValueError(f"agent '{agent_id}' chưa cấu hình github_repo — không theo dõi PR được")

    store = _task_store_for(agent_id)
    try:
        params = {"target": "pr", "number": number}
        note = slots.get("note")
        if note:
            params["note"] = note
        task_id = store.create(kind="watch", params=params, schedule="0 8 * * *",
                               assigned_by="ceo-chat")
    except RuntimeError as exc:  # open-task cap
        raise ValueError(str(exc)) from None
    finally:
        store.close()
    return (f"Đã giao việc #{task_id} cho '{agent_id}': theo dõi PR #{number} "
            f"({loaded.config.github_repo}) tới khi merge/đóng, nhắc mỗi ngày.")


def _preview_watch_pr(slots: dict[str, str]) -> str:
    note = slots.get("note")
    lines = [
        "Mình sẽ GIAO một việc theo dõi:",
        f"- Agent: {slots['agent_id']}",
        f"- Theo dõi: PR #{slots.get('pr_number')}",
        "- Nhịp nhắc: mỗi ngày, tới khi PR merge/đóng (tối đa 14 ngày)",
    ]
    if note:
        lines.append(f"- Ghi chú: {note}")
    lines.append("\nXác nhận giao? (trả lời: xác nhận / huỷ)")
    return "\n".join(lines)


def _run_report_task(slots: dict[str, str]) -> str:
    """Assign a report-task: agent runs a report kind on its own cadence until cancelled."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    agent_id = slots["agent_id"]
    kind = slots["kind"]
    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise ValueError(f"không tìm thấy agent '{agent_id}'") from None
    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load(loaded.domain)
    if kind not in pack.report_kinds:
        raise ValueError(f"agent '{agent_id}' (domain {loaded.domain}) không có báo cáo "
                         f"'{kind}' (có: {', '.join(sorted(pack.report_kinds))})")
    store = _task_store_for(agent_id)
    try:
        task_id = store.create(kind="report", params={"kind": kind, "audience": "internal"},
                               schedule="0 8 * * *", assigned_by="ceo-chat")
    except RuntimeError as exc:
        raise ValueError(str(exc)) from None
    finally:
        store.close()
    return f"Đã giao việc #{task_id} cho '{agent_id}': chạy báo cáo '{kind}' định kỳ."


def _preview_report_task(slots: dict[str, str]) -> str:
    return (f"Mình sẽ giao việc định kỳ cho '{slots['agent_id']}': chạy báo cáo "
            f"'{slots.get('kind')}' mỗi ngày (tối đa 14 ngày).\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def _run_qa_task(slots: dict[str, str]) -> str:
    """Assign a qa-task: agent answers a fixed recurring question on cadence."""
    store = _task_store_for(slots["agent_id"])
    try:
        question = str(slots["question"]).strip()
        task_id = store.create(kind="qa", params={"question": question},
                               schedule="0 8 * * *", assigned_by="ceo-chat")
    except RuntimeError as exc:
        raise ValueError(str(exc)) from None
    finally:
        store.close()
    return (f"Đã giao việc #{task_id} cho '{slots['agent_id']}': trả lời định kỳ câu "
            f"'{question[:60]}'.")


def _preview_qa_task(slots: dict[str, str]) -> str:
    return (f"Mình sẽ giao việc định kỳ cho '{slots['agent_id']}': trả lời câu "
            f"'{slots.get('question')}' mỗi ngày (tối đa 14 ngày).\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def _run_list_tasks(slots: dict[str, str]) -> str:
    """Read-only: list an agent's open assigned tasks."""
    store = _task_store_for(slots["agent_id"])
    try:
        tasks = store.list_open()
    finally:
        store.close()
    if not tasks:
        return f"Agent '{slots['agent_id']}' hiện không có việc nào đang mở."
    lines = [f"Việc đang mở của '{slots['agent_id']}':"]
    for t in tasks:
        lines.append(f"- #{t.id}: {_task_summary(t)} ({t.status})")
    return "\n".join(lines)


def _task_summary(task) -> str:
    """One-line what-this-task-does, per kind."""
    if task.kind == "watch":
        return f"theo dõi PR #{task.params.get('number')}"
    if task.kind == "report":
        return f"báo cáo định kỳ '{task.params.get('kind')}'"
    if task.kind == "qa":
        return f"trả lời định kỳ '{str(task.params.get('question') or '')[:40]}'"
    return task.kind


def _run_team_metrics(slots: dict[str, str]) -> str:
    """v76: the CAPTURE→ANALYZE surface — per-agent rates with Wilson CI, min-sample
    badges, and zero-contrast honesty, rendered for Telegram. Read-only."""
    from my_crew.runtime.agent_metrics import agent_metrics, render_team_metrics_vi

    return render_team_metrics_vi(agent_metrics())


def _run_cancel_task(slots: dict[str, str]) -> str:
    store = _task_store_for(slots["agent_id"])
    try:
        try:
            task_id = int(slots["task_id"])
        except (KeyError, ValueError):
            raise ValueError("mã việc không hợp lệ") from None
        task = store.get(task_id)
        if task is None:
            raise ValueError(f"không có việc #{task_id} của '{slots['agent_id']}'")
        if task.status not in ("open", "running"):
            return f"Việc #{task_id} đã ở trạng thái '{task.status}', không cần huỷ."
        store.set_status(task_id, "cancelled")
    finally:
        store.close()
    return f"Đã huỷ việc #{task_id} của '{slots['agent_id']}'."


def _preview_cancel_task(slots: dict[str, str]) -> str:
    return (f"Mình sẽ HUỶ việc #{slots.get('task_id')} của agent '{slots['agent_id']}'.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


#: command_id → spec. slots = ordered {name: {prompt, required, max_len?, pattern?}}.
OPS_COMMANDS: dict[str, dict] = {
    "create_agent": {
        "description": "Tạo một nhân sự ảo (agent) mới cho đội",
        "readonly": False,
        "slots": {
            "id": {"prompt": "Mã định danh agent (chữ thường/số/gạch, vd 'sales-team')?",
                   "required": True, "max_len": 40, "pattern": r"[a-z0-9][a-z0-9_-]*",
                   "lower": True,
                   "hint": "một mã kỹ thuật viết thường, không dấu, không khoảng trắng "
                           "(vd 'sales-pm')"},
            "domain": {"prompt": "Vai trò của agent? (pm = quản lý dự án, hr = nhân sự, "
                                 "admin = giám sát đội, office = nhân viên văn phòng, "
                                 "personal = thư ký riêng)",
                       "required": True, "max_len": 20,
                       "choices": {
                           "pm": ("quản lý dự án", "quan ly du an", "project", "dự án", "du an"),
                           "hr": ("nhân sự", "nhan su", "human resources", "tuyển dụng"),
                           "admin": ("giám sát", "giam sat", "vận hành", "van hanh", "quản trị"),
                           "office": ("văn phòng", "van phong", "nhân viên văn phòng",
                                      "nhan vien van phong", "office"),
                           "personal": ("thư ký", "thu ky", "thư ký riêng", "thu ky rieng",
                                        "trợ lý riêng", "tro ly rieng"),
                       },
                       "hint": "đúng MỘT mã: pm, hr, admin, office, hoặc personal"},
            "reports": {"prompt": "Loại báo cáo agent sẽ làm (vd 'daily' cho pm, "
                                  "'headcount' cho hr, 'briefing' cho personal; nếu agent "
                                  "chỉ nhận việc qua giao "
                                  "việc — không có báo cáo định kỳ — nhắn 'không')? "
                                  "Nhiều loại cách nhau bởi dấu phẩy.",
                        "required": True, "max_len": 100, "lower": True,
                        "hint": "mã báo cáo VIẾT THƯỜNG cách nhau bởi dấu phẩy (vd 'daily' "
                                "hoặc 'daily,weekly'), hoặc 'không' nếu không có"},
            "name": {"prompt": "Tên hiển thị (tuỳ chọn, bỏ qua để dùng mã)?",
                     "required": False, "max_len": 60},
            "jira_project_key": {"prompt": "Mã Jira project (tuỳ chọn, vd 'SCRUM')?",
                                 "required": False, "max_len": 20},
        },
        "run": _run_create_agent,
        "preview": _preview_create_agent,
    },
    "set_enabled": {
        "description": "Bật hoặc tắt một agent",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Bật/tắt agent nào (mã agent)?", "required": True,
                         "max_len": 40, "lower": True},
            "state": {"prompt": "Bật hay tắt?", "required": True, "max_len": 10,
                      "choices": {"on": ("bật", "bat", "mở", "mo", "enable", "chạy", "chay"),
                                  "off": ("tắt", "tat", "dừng", "dung", "disable", "ngừng")},
                      "hint": "đúng MỘT mã: on hoặc off"},
        },
        "run": _run_set_enabled,
        "preview": _preview_set_enabled,
    },
    "get_status": {
        "description": "Xem trạng thái cả đội (số agent, việc chờ duyệt, cảnh báo)",
        "readonly": True,
        "slots": {},
        "run": _run_get_status,
    },
    "get_cost": {
        "description": "Xem chi phí LLM của cả đội tháng này",
        "readonly": True,
        "slots": {},
        "run": _run_get_cost,
    },
    "search_history": {
        "description": "Tìm trong lịch sử làm việc của đội (kết quả bàn giao + hành động)"
                       " — vd 'tuần trước quyết gì về agenda'",
        "readonly": True,
        "slots": {
            "query": {"prompt": "Tìm gì trong lịch sử làm việc?", "required": True,
                      "max_len": 120},
        },
        "run": _run_search_history,
    },
    "company_activity": {
        "description": "Tóm tắt hoạt động cả công ty (mọi agent đã tự làm gì) trong N ngày qua",
        "readonly": True,
        # v31 P1: this readonly command itself calls the LLM to narrate the (already
        # code-projected + untrusted-wrapped) activity rows — the engine passes the
        # turn's client in via `run(slots, llm=)` (see ops_chat readonly dispatch).
        "needs_llm": True,
        "slots": {
            "days": {"prompt": "Xem hoạt động trong bao nhiêu ngày qua (mặc định 7)?",
                     "required": False, "max_len": 3, "pattern": r"[0-9]+",
                     "hint": "chỉ con số ngày (vd '7')"},
        },
        "run": run_company_activity,
    },
    "watch_pr": {
        "description": "Giao việc theo dõi một PR tới khi merge/đóng, nhắc mỗi ngày",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Giao cho agent nào (mã agent có github_repo)?",
                         "required": True, "max_len": 40, "lower": True},
            "pr_number": {"prompt": "Số PR cần theo dõi?", "required": True, "max_len": 10,
                          "pattern": r"[0-9]+", "hint": "chỉ con số (vd '45')"},
            "note": {"prompt": "Ghi chú thêm (tuỳ chọn)?", "required": False, "max_len": 200},
        },
        "run": _run_watch_pr,
        "preview": _preview_watch_pr,
    },
    "report_task": {
        "description": "Giao việc chạy một báo cáo định kỳ (vd daily/headcount) mỗi ngày",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Giao cho agent nào?", "required": True,
                         "max_len": 40, "lower": True},
            "kind": {"prompt": "Loại báo cáo (vd daily, weekly, headcount)?",
                     "required": True, "max_len": 30, "lower": True,
                     "hint": "một mã báo cáo viết thường"},
        },
        "run": _run_report_task,
        "preview": _preview_report_task,
    },
    "qa_task": {
        "description": "Giao việc trả lời một câu hỏi định kỳ mỗi ngày",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Giao cho agent nào?", "required": True,
                         "max_len": 40, "lower": True},
            "question": {"prompt": "Câu hỏi cần trả lời định kỳ?", "required": True,
                         "max_len": 300},
        },
        "run": _run_qa_task,
        "preview": _preview_qa_task,
    },
    "list_tasks": {
        "description": "Xem các việc ĐỊNH KỲ đang mở của MỘT agent (báo cáo/hỏi đáp/"
                       "theo dõi PR) — thẻ việc nhóm thì dùng list_team_tasks",
        "readonly": True,
        "slots": {
            "agent_id": {"prompt": "Xem việc của agent nào?", "required": True,
                         "max_len": 40, "lower": True},
        },
        "run": _run_list_tasks,
    },
    # v63: the team-task board in chat — "liệt kê các thẻ việc" lands here, with the
    # retro numbers (soát/sửa/chi phí) the review-policy calibration reads.
    "list_team_tasks": {
        "description": "Liệt kê các thẻ việc nhóm (việc giao cho cả đội) — tiến độ, "
                       "số lượt soát/sửa, chi phí, và thẻ nào đang chờ quyết định",
        "readonly": True,
        "slots": {},
        "run": run_list_team_tasks,
    },
    "cancel_task": {
        "description": "Huỷ một việc đã giao cho một agent trong đội (việc nền/định kỳ). "
                       "KHÔNG dùng cho nhắc hẹn giờ cá nhân — 'huỷ nhắc'/'xoá nhắc'/"
                       "'cancel reminder' không khớp lệnh nào ở đây",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Việc thuộc agent nào?", "required": True,
                         "max_len": 40, "lower": True},
            "task_id": {"prompt": "Mã việc cần huỷ (số)?", "required": True, "max_len": 10,
                        "pattern": r"[0-9]+", "hint": "chỉ con số"},
        },
        "run": _run_cancel_task,
        "preview": _preview_cancel_task,
    },
    "send_message": {
        "description": "Chủ động gửi một tin nhắn tới kênh/người nhận (Slack/Telegram/email) "
                       "— qua Action Gateway (guarded thì chờ duyệt)",
        "readonly": False,
        "slots": {
            "channel": {"prompt": "Gửi qua kênh nào? (slack / telegram / email)",
                        "required": True, "max_len": 12, "lower": True,
                        "choices": {
                            "slack": ("slack",),
                            "telegram": ("telegram", "tele"),
                            "email": ("email", "mail", "e-mail", "thư"),
                        },
                        "hint": "đúng MỘT: slack, telegram, hoặc email"},
            "to": {"prompt": "Gửi tới đâu? (id kênh Slack, chat id Telegram, hoặc địa chỉ email)",
                   "required": True, "max_len": 120},
            "text": {"prompt": "Nội dung tin nhắn?", "required": True, "max_len": 2000},
            "subject": {"prompt": "Tiêu đề (chỉ dùng cho email, bỏ qua nếu không)?",
                        "required": False, "max_len": 120},
        },
        "run": run_send_message,
        "preview": preview_send_message,
    },
    "create_calendar_event": {
        "description": "Tạo một sự kiện Google Calendar (qua Action Gateway; guarded thì "
                       "chờ duyệt)",
        "readonly": False,
        "slots": {
            "title": {"prompt": "Tiêu đề sự kiện?", "required": True, "max_len": 300},
            "start": {"prompt": "Bắt đầu (định dạng RFC3339, vd 2026-07-20T09:00:00+07:00)?",
                      "required": True, "max_len": 40},
            "end": {"prompt": "Kết thúc (RFC3339, bỏ qua nếu trùng giờ bắt đầu)?",
                    "required": False, "max_len": 40},
            "attendees": {"prompt": "Email người dự (cách nhau dấu phẩy, tuỳ chọn)?",
                          "required": False, "max_len": 400},
        },
        "run": run_create_calendar_event,
        "preview": preview_create_calendar_event,
    },
    "assign_team_task": {
        # Đây là lệnh BAO TRÙM mọi việc cần LÀM mà không có lệnh chuyên biệt hơn. Mô tả
        # phải nói rõ điều đó: bản v61 chỉ ghi "một việc lớn cho cả đội", nên bộ phân
        # loại đọc "khảo sát công cụ gửi tin Zalo OA" là hành động KHÔNG khớp lệnh nào
        # (unsupported 3/3 khi đo thật) — yêu cầu của CEO rơi xuống listing M12 và không
        # đẻ ra thẻ việc nào. Liệt kê thẳng các động từ việc thường tới và nói "không cần
        # to tát" thì nó mới khớp.
        "description": "Giao việc cho đội làm — tra cứu, khảo sát, nghiên cứu, thu thập "
                       "số liệu, so sánh, tổng hợp, lập bảng, viết báo cáo, phân tích. "
                       "Dùng cho MỌI việc cần làm mà không có lệnh chuyên biệt hơn, "
                       "không cần phải là việc to tát. Hệ thống tự chia thành các bước "
                       "và phân công cho từng người",
        "readonly": False,
        "slots": {
            "brief": {"prompt": "Mô tả việc cần giao cho đội (mình sẽ tự chia thành các "
                                "bước và phân công cho từng người)?",
                      "required": True, "max_len": 1000},
        },
        "run": run_assign_team_task,
        "preview": preview_assign_team_task,
        "on_cancel": cancel_assign_team_task,
    },
    "adjust_team_task": {
        "description": "Chỉnh lại kế hoạch một việc đội đang làm — chỉ đổi các bước "
                       "còn CHỜ, giữ nguyên các bước đã xong/đang chạy",
        "readonly": False,
        "slots": {
            "task_id": {"prompt": "Mã việc cần chỉnh kế hoạch?", "required": True,
                        "max_len": 20},
            "request": {"prompt": "Chỉnh kế hoạch như thế nào?", "required": True,
                        "max_len": 1000},
        },
        "run": run_adjust_team_task,
        "preview": preview_adjust_team_task,
        "on_cancel": cancel_adjust_team_task,
    },
    # v63 one-touch stall recovery — the three fast exits for a `stalled` team task
    # (the escalation message suggests them with the task id filled in).
    "accept_stalled_result": {
        "description": "Chấp nhận kết quả hiện có của một việc đội bị dừng (soát chéo "
                       "chưa đạt nhưng CEO duyệt nguyên trạng)",
        "readonly": False,
        "slots": {
            "task_id": {"prompt": "Mã việc đội bị dừng cần chấp nhận kết quả?",
                        "required": True, "max_len": 20},
        },
        "run": run_accept_stalled_result,
        "preview": preview_accept_stalled_result,
    },
    "retry_stalled_step": {
        "description": "Cho bước đang kẹt của một việc đội bị dừng thêm ĐÚNG MỘT lượt "
                       "thử lại (kèm ghi chú định hướng nếu có)",
        "readonly": False,
        "slots": {
            "task_id": {"prompt": "Mã việc đội bị dừng cần thử lại?", "required": True,
                        "max_len": 20},
            "note": {"prompt": "Ghi chú định hướng cho lần sửa này (bỏ qua nếu không)?",
                     "required": False, "max_len": 500},
        },
        "run": run_retry_stalled_step,
        "preview": preview_retry_stalled_step,
    },
    "drop_stalled_step": {
        "description": "Bỏ (các) bước chết của một việc đội bị dừng để phần còn lại "
                       "chạy tiếp",
        "readonly": False,
        "slots": {
            "task_id": {"prompt": "Mã việc đội bị dừng cần bỏ bước kẹt?", "required": True,
                        "max_len": 20},
        },
        "run": run_drop_stalled_step,
        "preview": preview_drop_stalled_step,
    },
    # v69 chat approval surface — the third surface on the Lớp B queue, beside the CLI
    # and the web banner. Admin-only: these reach into OTHER agents' approval stores, so
    # they are fleet authority, not orchestration (deliberately out of the personal subset).
    # v69 — what the coordinator learned from finished team tasks. Orchestration, not
    # fleet admin: it reads one namespace of the coordinator's own memory, and the CEO
    # asking "we keep getting stuck, what have we learned" is a delegation question.
    "list_lessons": {
        "description": "Xem các bài học rút ra từ những việc đã giao cho nhóm",
        "readonly": True,
        "slots": {},
        "run": run_list_lessons,
    },
    "team_metrics": {
        "description": "Xem số liệu hiệu suất đội (tỉ lệ xong, thời gian, chi phí, "
                       "can thiệp — kèm khoảng tin cậy, mẫu nhỏ gắn dấu *)",
        "readonly": True,
        "slots": {},
        "run": _run_team_metrics,
    },
    "list_approvals": {
        "description": "Xem mọi việc đang chờ CEO duyệt, của tất cả agent",
        "readonly": True,
        "slots": {},
        "run": run_list_approvals,
    },
    "approve_pending_action": {
        "description": "Duyệt một việc đang chờ (kèm tuỳ chọn từ nay tự duyệt việc "
                       "cùng loại cùng đích)",
        "readonly": False,
        "slots": {
            "approval_id": {"prompt": "Mã việc chờ duyệt (số) là bao nhiêu?",
                            "required": True, "max_len": 10},
            "agent_id": {"prompt": "Việc đó của agent nào?", "required": True,
                         "max_len": 40},
            "scope": {"prompt": "Chỉ duyệt lần này, hay từ nay tự duyệt? "
                                "(trả lời: một lần / luôn)",
                      "required": False, "max_len": 20},
        },
        "run": run_approve_pending_action,
        "preview": preview_approve_pending_action,
    },
    "reject_pending_action": {
        "description": "Từ chối một việc đang chờ (kèm tuỳ chọn từ nay chặn hẳn việc "
                       "cùng loại cùng đích)",
        "readonly": False,
        "slots": {
            "approval_id": {"prompt": "Mã việc chờ duyệt (số) là bao nhiêu?",
                            "required": True, "max_len": 10},
            "agent_id": {"prompt": "Việc đó của agent nào?", "required": True,
                         "max_len": 40},
            "scope": {"prompt": "Chỉ từ chối lần này, hay từ nay chặn hẳn? "
                                "(trả lời: một lần / chặn)",
                      "required": False, "max_len": 20},
        },
        "run": run_reject_pending_action,
        "preview": preview_reject_pending_action,
    },
    # v63 autopilot (CEO 2026-08-04): the secretary decides in the CEO's place.
    "set_autopilot": {
        "description": "Bật/tắt autopilot — thư ký thay CEO xác nhận kế hoạch, gỡ việc "
                       "dừng và duyệt bước gửi ra ngoài (có nhật ký + báo lại)",
        "readonly": False,
        "slots": {
            "mode": {"prompt": "Bật hay tắt autopilot? (on / off)", "required": True,
                     "max_len": 8, "lower": True,
                     "choices": {
                         "on": ("on", "bật", "bat", "mở", "mo"),
                         "off": ("off", "tắt", "tat", "đóng", "dong"),
                     },
                     "hint": "đúng MỘT: on hoặc off"},
        },
        "run": run_set_autopilot,
        "preview": preview_set_autopilot,
    },
    "get_autopilot": {
        "description": "Xem trạng thái autopilot hiện tại",
        "readonly": True,
        "slots": {},
        "run": run_get_autopilot,
    },
    # v68 heartbeat. Routing is pure LLM classification — there is no keyword table — so
    # the CEO's real phrasings live IN the description; that field IS the router.
    "add_heartbeat_watch": {
        "description": "Dặn thư ký để ý giùm một việc — vd 'để ý giùm vụ hợp đồng nhà "
                       "cung cấp', 'nhớ nhắc tôi vụ tuyển dụng'. Thư ký sẽ nhắc lại định "
                       "kỳ (KHÔNG tự dò trạng thái, chỉ nhắc)",
        "readonly": False,
        "slots": {
            "text": {"prompt": "Bạn muốn mình để ý giùm việc gì?", "required": True,
                     "max_len": 200},
            "agent_id": {"prompt": "Nhịp của agent nào? (bỏ qua nếu chỉ có một)",
                         "required": False, "max_len": 40, "lower": True},
        },
        "run": run_add_heartbeat_watch,
        "preview": preview_add_heartbeat_watch,
    },
    "stop_heartbeat_watch": {
        "description": "Bỏ một việc khỏi danh sách để ý — vd 'thôi khỏi để ý vụ hợp đồng', "
                       "'xong vụ tuyển dụng rồi, đừng nhắc nữa'",
        "readonly": False,
        "slots": {
            "text": {"prompt": "Bỏ việc nào khỏi danh sách để ý?", "required": True,
                     "max_len": 200},
            "agent_id": {"prompt": "Nhịp của agent nào? (bỏ qua nếu chỉ có một)",
                         "required": False, "max_len": 40, "lower": True},
        },
        "run": run_stop_heartbeat_watch,
        "preview": preview_stop_heartbeat_watch,
    },
    "enable_heartbeat": {
        "description": "Bật lại nhịp thư ký chủ động sau khi nó tự tắt vì gửi hụt nhiều "
                       "lần — vd 'bật lại nhịp thư ký', 'cho thư ký ngó việc lại đi'",
        "readonly": False,
        "slots": {
            "agent_id": {"prompt": "Nhịp của agent nào? (bỏ qua nếu chỉ có một)",
                         "required": False, "max_len": 40, "lower": True},
        },
        "run": run_enable_heartbeat,
        "preview": preview_enable_heartbeat,
    },
}


#: v61 (CEO 2026-08-04): the ops layer opens to the personal secretary with the
#: ORCHESTRATION subset only — multi-agent task dispatch and fleet observability, never
#: fleet ADMINISTRATION. Excluded on purpose: `create_agent`/`set_enabled` (change the
#: fleet itself — admin-only) and `create_calendar_event` (the secretary already has its
#: own M12 calendar commands; two surfaces for one intent confuse the classifier).
ORCHESTRATION_COMMAND_IDS = frozenset({
    "assign_team_task", "adjust_team_task", "list_tasks", "list_team_tasks", "cancel_task",
    "watch_pr", "report_task", "qa_task", "send_message",
    "get_status", "get_cost", "company_activity", "search_history",
    # v63 stall recovery — orchestration concern (unstick a team task), not fleet admin.
    "accept_stalled_result", "retry_stalled_step", "drop_stalled_step",
    # v63 autopilot — the secretary IS the surface this mode exists for.
    "set_autopilot", "get_autopilot",
    # v68 heartbeat — the pulse belongs to the secretary, so its controls do too. These
    # touch only that agent's own heartbeat store, never the fleet.
    "add_heartbeat_watch", "stop_heartbeat_watch", "enable_heartbeat",
    # v69 lessons — reads the coordinator's own reflection memory; a delegation question,
    # not fleet authority (unlike the approval commands, which reach into other agents).
    "list_lessons",
    # v76 metrics — read-only aggregates over telemetry; same delegation-question class
    # as list_lessons (how is my team doing), no fleet authority involved.
    "team_metrics",
})


def catalog_for_domain(domain: str) -> dict[str, dict]:
    """The ops catalog an agent of `domain` may serve its operator. Admin keeps the
    FULL catalog (byte-identical pre-v61); any other ops-enabled domain (personal)
    gets the orchestration subset. Insertion order follows OPS_COMMANDS."""
    if domain == "admin":
        return OPS_COMMANDS
    return {cid: spec for cid, spec in OPS_COMMANDS.items()
            if cid in ORCHESTRATION_COMMAND_IDS}


def command_listing(catalog: dict[str, dict] | None = None) -> str:
    """One-line catalog for the CEO when a request is unsupported."""
    commands = OPS_COMMANDS if catalog is None else catalog
    return "; ".join(f"`{cid}` — {spec['description']}" for cid, spec in commands.items())


def get_command(command_id: str, catalog: dict[str, dict] | None = None) -> dict | None:
    commands = OPS_COMMANDS if catalog is None else catalog
    return commands.get(command_id)
