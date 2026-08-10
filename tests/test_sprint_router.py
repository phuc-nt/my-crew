"""v77 sprint router: which briefs become a 1-step sprint task, and what that task
looks like once persisted.

The router's whole value is that it REFUSES most things. A brief that reaches sprint
mode wrongly costs a dead-end round-trip before the CEO can re-assign it as a team
task, so the exclusion cases below carry as much weight as the happy path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as mod
import my_crew.agent.sprint_intake as intake_mod
import my_crew.runtime.company as company_mod
from my_crew.agent.sprint_intake import SprintPlan, classify_brief, strip_mode_prefix


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


# --- strip_mode_prefix ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sprint: khảo sát 5 dịch vụ", ("sprint", "khảo sát 5 dịch vụ")),
        ("team: khảo sát 5 dịch vụ", ("team", "khảo sát 5 dịch vụ")),
        ("SPRINT: viết bài", ("sprint", "viết bài")),
        ("sprint：viết bài", ("sprint", "viết bài")),  # full-width colon (VN IME)
        ("khảo sát 5 dịch vụ", ("", "khảo sát 5 dịch vụ")),
        ("sprint mà không có dấu hai chấm", ("", "sprint mà không có dấu hai chấm")),
    ],
)
def test_strip_mode_prefix(raw, expected):
    assert strip_mode_prefix(raw) == expected


# --- classify_brief ------------------------------------------------------------------


@pytest.mark.parametrize(
    "brief",
    [
        "khảo sát 5 dịch vụ streaming và so sánh giá",
        "tổng hợp tin tức AI tuần này",
        "nghiên cứu xem đối thủ đang làm gì",
        "viết một bài giới thiệu sản phẩm",
        "rà soát lại danh sách khách hàng cũ",
        "research the top 5 note-taking tools",
    ],
)
def test_classify_accepts_one_person_shapes(brief):
    is_sprint, reason = classify_brief(brief)
    assert is_sprint is True, reason


@pytest.mark.parametrize(
    ("brief", "why"),
    [
        ("khảo sát 5 dịch vụ rồi gửi email cho khách", "ghi ra ngoài"),
        ("tổng hợp log rồi chạy script dọn dẹp", "shell"),
        ("nghiên cứu thị trường, chia việc cho mỗi người một mảng", "nhiều người"),
        ("khảo sát đối thủ theo lộ trình từng giai đoạn", "giai đoạn"),
        ("chuẩn bị demo cho khách", "không nhận ra dạng"),
        ("", "rỗng"),
    ],
)
def test_classify_refuses_team_shaped_briefs(brief, why):
    is_sprint, reason = classify_brief(brief)
    assert is_sprint is False
    assert reason, why


def test_classify_refuses_a_very_long_brief():
    long_brief = "khảo sát thị trường. " * 100
    assert len(long_brief) > 1200
    is_sprint, reason = classify_brief(long_brief)
    assert is_sprint is False
    assert "quá dài" in reason


# --- sprint_intake fail-open ---------------------------------------------------------


_STAFF = [("agent-a", "content"), ("agent-b", "research")]


def test_intake_uses_the_models_plan_when_it_is_well_formed(monkeypatch):
    payload = (
        '{"goal":"So sánh 5 dịch vụ streaming","acceptance":"- Đủ 5 tên\\n- Có giá",'
        '"assigned_to":"agent-b","needs_web":true}'
    )
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m: SimpleNamespace(content=payload,
                                                                    cost_usd=0.001)), None),
    )
    plan, cost = intake_mod.sprint_intake("khảo sát 5 dịch vụ streaming", _STAFF)
    assert plan.goal == "So sánh 5 dịch vụ streaming"
    assert plan.assigned_to == "agent-b"
    assert plan.needs_web is True
    assert cost == pytest.approx(0.001)


@pytest.mark.parametrize(
    "content",
    ["", "xin lỗi tôi không hiểu", '{"goal": ', '["not", "an", "object"]'],
)
def test_intake_falls_open_to_the_ceos_own_words(monkeypatch, content):
    """A broken intake must never break the assign: the CEO's verbatim brief becomes
    the goal, and `needs_web` errs True (a wasted search costs seconds, a missing one
    costs an empty report)."""
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m: SimpleNamespace(content=content,
                                                                    cost_usd=0.002)), None),
    )
    plan, _cost = intake_mod.sprint_intake("khảo sát 5 dịch vụ", _STAFF)
    assert plan.goal == "khảo sát 5 dịch vụ"
    assert plan.assigned_to in {"agent-a", "agent-b"}
    assert plan.needs_web is True


def test_intake_falls_open_when_the_model_call_raises(monkeypatch):
    def _boom():
        raise RuntimeError("provider down")

    monkeypatch.setattr(mod, "_build_llm", _boom)
    plan, cost = intake_mod.sprint_intake("tổng hợp tin tức", _STAFF)
    assert plan.goal == "tổng hợp tin tức"
    assert cost == 0.0


def test_intake_never_invents_an_assignee(monkeypatch):
    payload = '{"goal":"g","acceptance":"","assigned_to":"nguoi-khong-co-that"}'
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m: SimpleNamespace(content=payload,
                                                                    cost_usd=0.0)), None),
    )
    plan, _ = intake_mod.sprint_intake("khảo sát", _STAFF)
    assert plan.assigned_to in {"agent-a", "agent-b"}


def test_intake_cannot_override_a_ceo_named_pic(monkeypatch):
    payload = '{"goal":"g","acceptance":"","assigned_to":"agent-b"}'
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m: SimpleNamespace(content=payload,
                                                                    cost_usd=0.0)), None),
    )
    plan, _ = intake_mod.sprint_intake("khảo sát", _STAFF, pic_requested="agent-a")
    assert plan.assigned_to == "agent-a"


# --- router wiring inside preview_assign_team_task -----------------------------------


def _wire(monkeypatch, *, plan: SprintPlan | None = None):
    """Full preview stack with BOTH branches stubbed, so a test can assert which one
    ran by looking at the resulting plan rather than at a mock's call log."""
    monkeypatch.setattr(mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(mod, "_staff_roster", lambda: [("agent-a", "content"),
                                                      ("agent-b", "research")])
    monkeypatch.setattr(
        company_mod, "load_company",
        lambda path=None: SimpleNamespace(name="", coordinator_id="coord-1",
                                          team_task_cap_usd=2.0,
                                          team_task_auto_confirm=False, autopilot=False),
    )
    calls: dict[str, int] = {"decompose": 0, "intake": 0}

    def _fake_decompose(brief, staff, pic=""):
        from my_crew.agent.task_decomposition import DecomposedTask, TeamStepPlan

        calls["decompose"] += 1
        return DecomposedTask(steps=(
            TeamStepPlan(step_id="s1", title="bước một", assigned_to="agent-a"),
            TeamStepPlan(step_id="s2", title="bước hai", assigned_to="agent-b",
                         deps=("s1",)),
        ), pic_id="agent-a"), 0.01

    def _fake_intake(brief, staff, pic=""):
        calls["intake"] += 1
        return (plan or SprintPlan(goal="So sánh 5 dịch vụ", acceptance="- Đủ 5 tên",
                                   assigned_to="agent-b", needs_web=True)), 0.001

    monkeypatch.setattr(mod, "_decompose_with_retries", _fake_decompose)
    monkeypatch.setattr(intake_mod, "sprint_intake", _fake_intake)
    return calls


def _steps_of(task_id):
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        return store.get(task_id).steps
    finally:
        store.close()


def test_sprint_shaped_brief_persists_exactly_one_sprint_step(monkeypatch):
    calls = _wire(monkeypatch)
    slots = {"brief": "khảo sát 5 dịch vụ streaming"}

    reply = mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 0, "intake": 1}
    assert "SPRINT" in reply
    steps = _steps_of(slots["task_id"])
    assert len(steps) == 1
    assert steps[0].step_type == "sprint"
    assert steps[0].assigned_to == "agent-b"
    assert steps[0].needs_review is False
    assert steps[0].needs_web is True
    assert steps[0].external_write is False


def test_team_shaped_brief_still_goes_through_decompose(monkeypatch):
    calls = _wire(monkeypatch)
    slots = {"brief": "chuẩn bị demo cho khách hàng lớn"}

    reply = mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 1, "intake": 0}
    assert "Kế hoạch phân rã" in reply
    assert [s.step_type for s in _steps_of(slots["task_id"])] == ["work", "work"]


def test_team_prefix_overrides_a_sprint_shaped_brief(monkeypatch):
    calls = _wire(monkeypatch)
    slots = {"brief": "team: khảo sát 5 dịch vụ streaming"}

    mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 1, "intake": 0}


def test_sprint_prefix_overrides_the_heuristics_refusal(monkeypatch):
    calls = _wire(monkeypatch)
    slots = {"brief": "sprint: chuẩn bị demo cho khách hàng lớn"}

    mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 0, "intake": 1}
    assert [s.step_type for s in _steps_of(slots["task_id"])] == ["sprint"]


@pytest.mark.parametrize("brief", [
    "sprint: gửi email cho khách về bảng giá mới",
    "sprint: chạy script dọn dữ liệu rồi tổng hợp lại",
    "sprint: chia việc cho cả đội khảo sát thị trường",
    "sprint: khảo sát thị trường theo lộ trình từng giai đoạn",
])
def test_the_sprint_prefix_cannot_override_a_hard_refusal(monkeypatch, brief):
    """The prefix picks a MODE, it does not lift a safety exclusion. A sprint step
    hardcodes external_write/needs_shell=False, so an external-write brief routed here
    would lose the review `review_insert` keeps mandatory for exactly that step kind."""
    calls = _wire(monkeypatch)
    slots = {"brief": brief}

    mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 1, "intake": 0}
    assert all(s.step_type == "work" for s in _steps_of(slots["task_id"]))


def test_mode_prefix_strips_before_the_pic_prefix(monkeypatch):
    """"sprint: @agent-a ..." — the mode wraps the whole brief, the PIC sits inside it."""
    calls = _wire(monkeypatch, plan=SprintPlan(goal="g", acceptance="",
                                               assigned_to="agent-a", needs_web=False))
    slots = {"brief": "sprint: @agent-a khảo sát 5 dịch vụ"}

    mod.preview_assign_team_task(slots)

    assert calls["intake"] == 1
    assert slots["pic_id"] == "agent-a"


def test_an_unknown_pic_is_still_rejected_under_a_sprint_prefix(monkeypatch):
    _wire(monkeypatch)
    with pytest.raises(ValueError, match="không có trong danh sách"):
        mod.preview_assign_team_task({"brief": "sprint: @nguoi-la khảo sát 5 dịch vụ"})


def test_sprint_task_keeps_the_ceos_verbatim_brief_as_original_request(monkeypatch):
    """The intake's summary is for reading; the worker must still receive what the CEO
    actually wrote, mode prefix and all — that is the only lossless copy."""
    _wire(monkeypatch)
    slots = {"brief": "sprint: khảo sát 5 dịch vụ streaming"}

    mod.preview_assign_team_task(slots)

    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        assert store.get(slots["task_id"]).original_request == slots["brief"]
    finally:
        store.close()
