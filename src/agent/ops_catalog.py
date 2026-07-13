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

from src.agent.ops_adjust_team_task import (
    cancel_adjust_team_task,
    preview_adjust_team_task,
    run_adjust_team_task,
)
from src.agent.ops_assign_team_task import (
    cancel_assign_team_task,
    preview_assign_team_task,
    run_assign_team_task,
)
from src.agent.ops_calendar_event import (
    preview_create_calendar_event,
    run_create_calendar_event,
)
from src.agent.ops_company_activity import run_company_activity
from src.agent.ops_send_message import preview_send_message, run_send_message

#: An agent whose work comes only from `assign_team_task` (e.g. office roles) has no
#: report kind of its own — the CEO says this instead of a report-kind list.
_NO_REPORTS_WORDS = frozenset({"không", "khong", "none", "no", "-", ""})


def _parse_reports(raw: str) -> list[str]:
    if raw.strip().lower() in _NO_REPORTS_WORDS:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _run_create_agent(slots: dict[str, str]) -> str:
    """Create an agent via the SAME primitive the web wizard uses (agent_create)."""
    from src.server import agent_create

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
    from src.runtime.registry_edit import UnknownRegistryAgentError, set_registry_enabled

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
    from src.runtime.agent_state_reader import read_all_agent_states

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
    from src.runtime.agent_state_reader import read_all_agent_states, team_alerts

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
    return "\n".join(lines)


def _run_search_history(slots: dict[str, str]) -> str:
    """v33 P5: read-only search over the team's past work (steps + audit) with cited
    sources — the CEO's "tuần trước team làm/quyết gì?" answer path."""
    from src.runtime.history_search_index import HistorySearchIndex

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
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.task_scheduling import _store_path
    from src.runtime.task_store import TaskStore

    try:
        load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        # Wrap, don't interpolate: a FileNotFoundError carries the full profile PATH, which
        # should not leak into a chat reply (M2). The id alone is enough for the operator.
        raise ValueError(f"không tìm thấy agent '{agent_id}'") from None
    return TaskStore(_store_path(agent_data_dir(agent_id)))


def _run_watch_pr(slots: dict[str, str]) -> str:
    """Assign a watch-task: agent tracks a PR until it merges/closes, reminding on cadence."""
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

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
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    agent_id = slots["agent_id"]
    kind = slots["kind"]
    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise ValueError(f"không tìm thấy agent '{agent_id}'") from None
    from src.packs.registry import PackRegistry

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
                                 "admin = giám sát đội, office = nhân viên văn phòng)",
                       "required": True, "max_len": 20,
                       "choices": {
                           "pm": ("quản lý dự án", "quan ly du an", "project", "dự án", "du an"),
                           "hr": ("nhân sự", "nhan su", "human resources", "tuyển dụng"),
                           "admin": ("giám sát", "giam sat", "vận hành", "van hanh", "quản trị"),
                           "office": ("văn phòng", "van phong", "nhân viên văn phòng",
                                      "nhan vien van phong", "office"),
                       },
                       "hint": "đúng MỘT mã: pm, hr, admin, hoặc office"},
            "reports": {"prompt": "Loại báo cáo agent sẽ làm (vd 'daily' cho pm, "
                                  "'headcount' cho hr; nếu agent chỉ nhận việc qua giao "
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
        "description": "Xem các việc đang mở của một agent",
        "readonly": True,
        "slots": {
            "agent_id": {"prompt": "Xem việc của agent nào?", "required": True,
                         "max_len": 40, "lower": True},
        },
        "run": _run_list_tasks,
    },
    "cancel_task": {
        "description": "Huỷ một việc đã giao",
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
        "description": "Giao một việc lớn cho cả đội — hệ thống tự chia thành các bước "
                       "và phân công",
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
            "yêu cầu": {"prompt": "Chỉnh kế hoạch như thế nào?", "required": True,
                        "max_len": 1000},
        },
        "run": run_adjust_team_task,
        "preview": preview_adjust_team_task,
        "on_cancel": cancel_adjust_team_task,
    },
}


def command_listing() -> str:
    """One-line catalog for the CEO when a request is unsupported."""
    return "; ".join(f"`{cid}` — {spec['description']}" for cid, spec in OPS_COMMANDS.items())


def get_command(command_id: str) -> dict | None:
    return OPS_COMMANDS.get(command_id)
