"""`plan` role probes: the three places a wrong plan-role answer is most expensive.

Intent: the CEO's chat message either becomes a team task or silently does not (the
production outage `test_ops_intent_delegation_live` documents). Decompose: the DAG the
whole task runs on; a one-step plan for a three-part brief hands the coordinator's job
to one worker. Intake: `sprint_intake` fails OPEN to a verbatim plan, so a miss here is
invisible to every test and only this kind of replay can see it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from my_crew.bench.role_bench_probe_kit import Probe, ProbeOutcome

#: (id, message, expected). `expected=None` means "anything but assign_team_task" — the
#: over-capture guard: a write command wrongly chosen burns a confirm round-trip and
#: then real money. Phrasings mirror the live delegation test so the two agree.
INTENT_CASES: tuple[tuple[str, str, str | None], ...] = (
    ("outage-verbatim",
     "Nghiên cứu giúp anh thị trường xe máy điện Việt Nam 2026. Cần biết: 3 hãng dẫn "
     "đầu thị phần, giá bán lẻ từng dòng chủ lực, và chính sách trợ giá/thuế của nhà "
     "nước năm nay. Tổng hợp thành bảng so sánh, ghi rõ nguồn cho từng số liệu.",
     "assign_team_task"),
    ("khao-sat-cong-cu",
     "Khảo sát các công cụ cho phép gửi tin nhắn Zalo OA tự động qua API: so sánh giá "
     "và giới hạn tin/tháng, gợi ý nên dùng cái nào", "assign_team_task"),
    ("ngan-menh-lenh", "tìm giúp anh 5 nhà cung cấp bao bì giấy ở HCM, kèm báo giá",
     "assign_team_task"),
    ("hoi-nhung-la-viec", "em xem giúp anh đối thủ của mình đang bán giá bao nhiêu nhé",
     "assign_team_task"),
    ("gia-thi-truong", "Giá bán lẻ hiện tại của iPhone 17 Pro và Galaxy S26 Ultra ở VN?",
     "assign_team_task"),
    ("chuyen-vat", "hôm nay thứ mấy vậy em", None),
    ("liet-ke-viec-nhom", "liệt kê các việc nhóm đang chạy", "list_team_tasks"),
    ("thong-ke-dinh-tuyen", "thống kê định tuyến việc", "route_stats"),
)

DECOMPOSE_STAFF: list[tuple[str, str]] = [
    ("researcher", "Tra cứu thị trường, nguồn công khai"),
    ("analyst", "Phân tích số liệu, dựng bảng so sánh"),
    ("writer", "Viết báo cáo, tài liệu gửi đối tác"),
]

#: (id, brief, min_steps). The three-part brief names three distinct jobs for three
#: distinct skills; one step means the planner declined to plan.
DECOMPOSE_BRIEFS: tuple[tuple[str, str, int], ...] = (
    ("ba-phan",
     "Nghiên cứu thị trường xe máy điện Việt Nam 2026: (1) tra cứu 3 hãng dẫn đầu và "
     "giá bán lẻ dòng chủ lực, ghi nguồn; (2) từ số liệu đó dựng bảng so sánh thị "
     "phần/giá/chính sách trợ giá; (3) viết bản tóm tắt 1 trang cho CEO kèm khuyến "
     "nghị nên nhập dòng nào.", 2),
    ("mot-viec", "Soạn giúp anh email mời đối tác dự lễ ra mắt sản phẩm ngày 20/10, "
     "giọng trang trọng, dưới 150 chữ.", 1),
)


def _intent_probe(case_id: str, message: str, expected: str | None) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.agent.ops_catalog import catalog_for_domain
        from my_crew.agent.ops_chat import classify_ops_intent

        result = classify_ops_intent(client, message, catalog_for_domain("personal"))
        is_command = result.get("intent") == "command"
        got = result.get("command_id") if is_command else result.get("intent")
        got = str(got or "")
        if expected is None:
            ok = got != "assign_team_task"
        else:
            ok = got == expected
        detail = f"got={got} expected={expected or 'not assign_team_task'}"
        return ProbeOutcome.passed(detail) if ok else ProbeOutcome.failed("wrong", detail)

    return Probe("plan", f"intent/{case_id}", run)


def _decompose_probe(case_id: str, brief: str, min_steps: int) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.agent.task_decomposition import (
            DecompositionError,
            parse_decomposed_task,
            repair_terminal_assignee,
            validate_decomposition,
        )
        from my_crew.bench.role_bench_probe_kit import complete_text
        from my_crew.llm.team_task_prompt import build_team_decompose_messages

        messages = build_team_decompose_messages(brief=brief, staff=DECOMPOSE_STAFF)
        text, cost, early = complete_text(client, messages, "plan")
        if early:
            return early
        try:
            task = parse_decomposed_task(text)
            # Same path as `ops_assign_team_task`: the terminal step is handed back
            # to the PIC before validation, so a plan the product would accept is
            # not scored as a failure here.
            staff_ids = {s for s, _ in DECOMPOSE_STAFF}
            task = repair_terminal_assignee(task, staff_ids)
            validate_decomposition(task, staff_ids=staff_ids)
        except DecompositionError as exc:
            return ProbeOutcome.failed("parse", str(exc), cost)
        who = ",".join(s.assigned_to for s in task.steps)
        detail = f"steps={len(task.steps)} to={who}"
        if len(task.steps) < min_steps:
            return ProbeOutcome.failed("wrong", f"{detail} < min {min_steps}", cost)
        return ProbeOutcome.passed(detail, cost)

    return Probe("plan", f"decompose/{case_id}", run)


def _intake_probe(case_name: str, intake: Callable | None = None) -> Probe:
    """`sprint_intake` builds its own client from the environment (its fail-open path
    wraps that construction too), so this probe drives the real function end to end
    and ignores the injected `client` — the same measurement `reliability` mode makes.
    `intake` is the offline seam, exactly as in `reliability_bench.bench_case`."""

    def run(client: Any) -> ProbeOutcome:
        from my_crew.bench.brief_suite import ALL_CASES
        from my_crew.bench.reliability_bench import BENCH_STAFF, _is_fallback

        if intake is None:
            from my_crew.agent.sprint_intake import sprint_intake as run_intake
        else:
            run_intake = intake
        case = next(c for c in ALL_CASES if c.name == case_name)
        plan, cost = run_intake(case.goal, BENCH_STAFF)
        if _is_fallback(plan, case.goal):
            return ProbeOutcome.failed("empty", "fell open to the verbatim plan", cost)
        return ProbeOutcome.passed(f"to={plan.assigned_to} web={plan.needs_web}", cost)

    return Probe("plan", f"intake/{case_name}", run)


def plan_probes(intake: Callable | None = None) -> list[Probe]:
    probes = [_intent_probe(*c) for c in INTENT_CASES]
    probes += [_decompose_probe(*c) for c in DECOMPOSE_BRIEFS]
    probes += [_intake_probe(n, intake) for n in ("streaming_services", "note_taking")]
    return probes
