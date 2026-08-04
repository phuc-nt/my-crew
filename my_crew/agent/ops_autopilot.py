"""Autopilot mode toggle + audit trail (v63).

CEO decision 2026-08-04 ("Toàn quyền thật"): with autopilot ON the secretary decides in
the CEO's place across the whole team-task pipeline — plan auto-confirm
(`ops_assign_team_task`), stalled-task auto-resolution (`runtime.autopilot_sweep`), and
pending Lớp B approval auto-approve (coordinator ticker). What autopilot can NEVER
touch: Lớp A hard-denies (`actions.hard_block`, structural, evaluated before any gate
this flag reaches) and the team-task cost cap. Per-task opt-out: a brief carrying a
"để anh duyệt"-style phrase pins that one task to the manual gates.

The flag lives in `company.yaml` (`Company.autopilot`) — the established runtime-config
store for exactly this kind of switch (`team_task_auto_confirm` precedent): persisted,
restart-surviving, re-read at each decision point so `set_autopilot off` takes effect on
the very next tick with no service restart.

Audit + notify-after ride the office room: every automatic decision appends a
`milestone: autopilot_decision` event with `also_office=True`, which the admin agent's
milestone mirror already DMs to the CEO — no new notification plumbing.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Opt-out phrases (normalized lowercase substring match on the assign brief): the CEO
#: says any of these while assigning ⇒ that ONE task keeps every manual gate.
OPT_OUT_PHRASES = (
    "để anh duyệt", "de anh duyet",
    "anh duyệt tay", "anh duyet tay",
    "cần ceo duyệt", "can ceo duyet",
    "cần duyệt tay", "can duyet tay",
)


def autopilot_enabled() -> bool:
    """Read the CURRENT flag — callers re-check per decision, never cache."""
    from my_crew.runtime.company import load_company

    return bool(getattr(load_company(), "autopilot", False))


def brief_opts_out(brief: str) -> bool:
    """True iff the assign brief carries a per-task opt-out phrase."""
    lowered = brief.lower()
    return any(p in lowered for p in OPT_OUT_PHRASES)


def record_autopilot_decision(
    *, decision: str, task_id: str, task_title: str, detail: str,
) -> None:
    """Audit + notify-after in one append (see module docstring). Best-effort like
    every other office append — an audit-write failure is logged, never raised into
    the decision path it documents."""
    try:
        from my_crew.runtime.office_room_append import append_office_event, room_for_task

        append_office_event(
            room_for_task(task_id), author="secretary", kind="milestone",
            body={"task_id": task_id, "task_title": task_title,
                  "milestone": "autopilot_decision", "decision": decision,
                  "message": f"[Autopilot] {detail}"},
            also_office=True,
        )
    except Exception:  # noqa: BLE001 — audit must never break the decision it records
        logger.exception("autopilot: audit append failed for task %s", task_id)


def run_set_autopilot(slots: dict[str, str]) -> str:
    from my_crew.runtime.company import load_company, save_company

    mode = (slots.get("mode") or "").strip().lower()
    enable = mode == "on"
    company = load_company()
    if company.autopilot == enable:
        state = "BẬT" if enable else "TẮT"
        return f"Autopilot đang {state} sẵn rồi — không có gì thay đổi."
    save_company(
        company.name, company.coordinator_id, company.team_task_cap_usd,
        team_task_concurrency=company.team_task_concurrency,
        team_task_auto_confirm=company.team_task_auto_confirm,
        autopilot=enable,
    )
    if enable:
        return ("Đã BẬT autopilot: từ giờ mình tự xác nhận kế hoạch, tự gỡ việc bị dừng "
                "và tự duyệt các bước gửi ra ngoài — mọi quyết định đều báo lại anh và "
                "có nhật ký. Vụ nào muốn tự duyệt, anh nói kèm 'để anh duyệt' khi giao. "
                "Tắt bằng: `autopilot off`.")
    return "Đã TẮT autopilot: mọi kế hoạch, phê duyệt và việc bị dừng chờ anh quyết như cũ."


def preview_set_autopilot(slots: dict[str, str]) -> str:
    mode = (slots.get("mode") or "").strip().lower()
    if mode == "on":
        return ("Mình sẽ BẬT autopilot — mình thay anh xác nhận kế hoạch, gỡ việc dừng, "
                "duyệt cả bước gửi ra ngoài (email/lịch/PR). Lớp chặn an toàn cứng và "
                "trần chi phí vẫn giữ nguyên; mọi quyết định được ghi nhật ký + báo lại.\n"
                "Xác nhận? (trả lời: xác nhận / huỷ)")
    return ("Mình sẽ TẮT autopilot — mọi cổng duyệt quay về tay anh như cũ.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def run_get_autopilot(slots: dict[str, str]) -> str:
    if autopilot_enabled():
        return ("Autopilot đang BẬT — mình tự xác nhận kế hoạch, tự gỡ việc dừng và tự "
                "duyệt bước gửi ra ngoài (trừ vụ được đánh dấu 'để anh duyệt').")
    return "Autopilot đang TẮT — mọi cổng duyệt thuộc về anh."
