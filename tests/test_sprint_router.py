"""v77 sprint router: which briefs become a 1-step sprint task, and what that task
looks like once persisted.

The router defaults to sprint and only diverts to team on a safety refusal or a
STRUCTURAL signal (too long, too many entities, several separate asks). Both wrong
directions have a net — `downgrade_to_sprint` pulls a degenerate team plan back, and
`sprint_dead_end` pushes an over-sized sprint out — so the tests below check the
signals, not the router's omniscience.
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
    "brief",
    [
        # Không đề nào dưới đây khớp một từ nào trong `_SPRINT_SHAPE_HINTS`. Bản router
        # đầu tiên đẩy hết sang team chỉ vì không nhận ra chữ — đúng loại sai đắt tiền
        # mà không ai thấy, vì task vẫn xong, chỉ là tốn gấp mấy lần.
        "cho tôi biết giá Netflix, Spotify và YouTube Premium hiện nay",
        "chuẩn bị demo cho khách",
        "xem giúp đối thủ đang bán gói nào",
        "gợi ý 5 tiêu đề cho bài blog tháng này",
    ],
)
def test_classify_defaults_to_sprint_for_natural_phrasing(brief):
    is_sprint, reason = classify_brief(brief)
    assert is_sprint is True, reason


@pytest.mark.parametrize(
    ("brief", "why"),
    [
        ("khảo sát 5 dịch vụ rồi gửi email cho khách", "ghi ra ngoài"),
        ("tổng hợp log rồi chạy script dọn dẹp", "shell"),
        ("nghiên cứu thị trường, chia việc cho mỗi người một mảng", "nhiều người"),
        ("khảo sát đối thủ theo lộ trình từng giai đoạn", "giai đoạn"),
        # Hai brief lọt lưới trong nghiệm thu live: "chạy BỘ test"/"clone repo" không
        # khớp needle "chạy test"; "cả TEAM" không khớp "cả đội"/"team làm".
        ("clone repo my-crew về rồi chạy bộ test, báo kết quả", "shell"),
        ("phân tích 3 đối thủ chính, việc này cần cả team cùng làm", "nhiều người"),
        ("", "rỗng"),
    ],
)
def test_classify_refuses_team_shaped_briefs(brief, why):
    is_sprint, reason = classify_brief(brief)
    assert is_sprint is False
    assert reason, why


# --- material_transform: tín hiệu đo, chưa đổi lane ----------------------------------


@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        # Hai dạng đề team từng thắng judge mù (lanes11/12): chất liệu cấp sẵn +
        # phân tích + sản phẩm.
        ("Phân tích số liệu bán hàng dưới đây và đề xuất hành động — không cần "
         "tra cứu web. Sản phẩm A: 120tr...", 1),
        ("Dưới đây là bản nháp email. Nêu rõ 3 điểm yếu rồi viết lại bản "
         "hoàn chỉnh.", 1),
        # Thiếu một trong ba chân thì không bắt: research thường (không chất liệu),
        # sáng tạo thuần (không tầng phân tích).
        ("Tóm tắt xu hướng thanh toán không tiền mặt và đề xuất hướng đi", 0),
        ("Soạn bộ tài liệu ra mắt tính năng mới theo dàn ý sau đây: email, "
         "post, FAQ", 0),
    ],
)
def test_material_transform_signal_detects_only_the_full_triplet(brief, expected):
    signals = intake_mod.route_signals(brief)
    assert signals["material_transform"] == expected


def test_material_transform_signal_does_not_change_the_lane():
    """Vòng này tín hiệu CHỈ ĐỂ ĐO (lộ trình effort_high): một đề khớp cả ba chân
    vẫn phải route như cũ — sprint theo mặc định — cho tới khi đủ số đo trao quyền."""
    brief = ("Phân tích số liệu bán hàng dưới đây và đề xuất hành động: "
             "A 120tr, B 95tr, C 30tr")
    assert intake_mod.route_signals(brief)["material_transform"] == 1
    is_sprint, _reason = classify_brief(brief)
    assert is_sprint is True


def test_classify_refuses_a_very_long_brief():
    long_brief = "khảo sát thị trường. " * 100
    assert len(long_brief) > 1200
    is_sprint, reason = classify_brief(long_brief)
    assert is_sprint is False
    assert "quá dài" in reason


def test_classify_refuses_a_brief_listing_more_entities_than_one_person_can_hold():
    names = ", ".join(f"dịch vụ {i}" for i in range(1, 13))
    is_sprint, reason = classify_brief(f"so sánh giá các bên ({names})")
    assert is_sprint is False
    assert "thực thể" in reason


def test_classify_refuses_a_brief_that_lists_three_separate_asks():
    brief = "\n".join([
        "làm giúp mấy việc này:",
        "- tổng hợp giá đối thủ",
        "- dựng slide cho buổi họp",
        "- soạn kịch bản demo",
    ])
    is_sprint, reason = classify_brief(brief)
    assert is_sprint is False
    assert "đầu việc" in reason


def test_the_same_three_asks_route_the_same_written_inline_or_on_lines():
    """Xuống dòng hay không KHÔNG được đổi quyết định định tuyến.

    Đo thật trên live A2: ba đầu việc viết liền một câu ("(1)... (2)... (3)...") ra
    sprint, cũng ba việc đó xuống dòng thì ra team. Khi đó thứ quyết định lane là CEO
    có bấm Enter hay không — không phải tính chất công việc. Bài này chốt cả hai cách
    viết cho ra cùng một con số.
    """
    from my_crew.agent.sprint_intake import _distinct_asks

    inline = ("Làm giúp anh 3 việc: (1) khảo sát 5 đối thủ chính, "
              "(2) viết bản tóm tắt định vị sản phẩm, "
              "(3) dựng kế hoạch truyền thông 2 tuần tới.")
    lined = "\n".join([
        "Làm giúp anh 3 việc:",
        "1. khảo sát 5 đối thủ chính",
        "2. viết bản tóm tắt định vị sản phẩm",
        "3. dựng kế hoạch truyền thông 2 tuần tới",
    ])

    assert _distinct_asks(inline) == _distinct_asks(lined) == 3
    assert classify_brief(inline)[0] is False
    assert classify_brief(lined)[0] is False
    assert "đầu việc" in classify_brief(inline)[1]


@pytest.mark.parametrize("brief", [
    "Anh cần (1) báo giá thôi",
    "Xem mục (2) trong hợp đồng giúp anh",
    "Điều 3. và điều 7. trong hợp đồng nói gì?",
])
def test_a_lone_number_in_a_sentence_is_not_a_list_of_asks(brief):
    """Một chỉ số ĐỨNG LẺ là lời nói thường hoặc lời trỏ ngược, không phải liệt kê.

    Đây là cái giá phải trả cho việc đếm đánh số giữa câu, nên bằng chứng đặt ở DÃY
    LIÊN TIẾP từ 1 chứ không ở sự hiện diện của chỉ số. Không có hàng rào này thì mọi
    câu nhắc "mục (2)" đều bị đẩy sang team.
    """
    from my_crew.agent.sprint_intake import _distinct_asks

    assert _distinct_asks(brief) == 1
    assert classify_brief(brief)[0] is True


@pytest.mark.parametrize(
    "brief",
    [
        "Rà soát Điều 1. Điều 2. Điều 3. của hợp đồng NDA giúp anh",
        "Đọc hợp đồng rồi tóm tắt Chương 1. Phạm vi Chương 2. Giá Chương 3. Phạt",
        "Ngày 1. 8 họp, ngày 2. 9 nghỉ lễ, ngày 3. 10 báo cáo",
        "Kiểm tra bảng giá: gói 1. 200k, gói 2. 500k, gói 3. 900k xem gói nào lời nhất",
    ],
)
def test_a_run_of_numbered_nouns_is_not_a_list_of_asks(brief):
    """Dãy liên tiếp từ 1 CHƯA đủ: dạng đánh dấu cũng phải là dạng liệt kê.

    Tiếng Việt viện dẫn danh từ có đánh số bằng đúng dạng "1." trần — Điều, Chương,
    gói, ngày — nên một đề chỉ đọc hợp đồng lại trông y hệt một đề ba đầu việc. Bốn
    câu này đều là MỘT việc; trước khi siết `_ASK_INLINE_RE` cả bốn đều bị đẩy sang
    lane team, tốn tiền và thời gian cho thứ một agent làm xong trong một lượt.

    Hướng sai ở đây là tốn kém chứ không hỏng (team vẫn ra kết quả đúng), nên hàng rào
    đặt ở dạng ký hiệu — "(1)", "[1]", "1)" mở một mục, "1." trần thì không — chứ không
    ở việc đoán nghĩa của danh từ đứng trước.
    """
    from my_crew.agent.sprint_intake import _distinct_asks

    assert _distinct_asks(brief) == 1, brief
    assert classify_brief(brief)[0] is True, classify_brief(brief)


def test_a_stray_number_before_the_list_does_not_hide_it():
    """Dãy được dò ở bất kỳ đâu, không bắt buộc bắt đầu ở chỉ số ĐẦU TIÊN tìm thấy.

    Một con số lạ đứng trước phần liệt kê ("Ngân sách 5. 000 rồi ...") từng làm dãy
    1-2-3 phía sau tắt hẳn, vì vòng dò khi đó neo vào phần tử đầu danh sách. Đây đúng
    là kiểu trượt âm thầm mà `_distinct_asks` tồn tại để chặn: đề ba đầu việc rơi về
    sprint chỉ vì trong câu có sẵn một con số khác.
    """
    from my_crew.agent.sprint_intake import _inline_asks

    brief = "Ngân sách 5. 000 rồi 1) khảo sát 2) so sánh 3) đề xuất"
    assert _inline_asks(brief) == 3, brief
    assert classify_brief(brief)[0] is False, classify_brief(brief)


def test_two_inline_asks_stay_under_the_cap():
    """Ngưỡng là "nhiều hơn 2", và đếm inline không được lặng lẽ siết nó lại."""
    from my_crew.agent.sprint_intake import _distinct_asks

    brief = "Anh cần (1) báo giá của 3 bên và (2) bản so sánh ngắn"
    assert _distinct_asks(brief) == 2
    assert classify_brief(brief)[0] is True


def test_attributes_after_a_colon_are_criteria_not_separate_asks():
    """Một việc kèm ba tiêu chí vẫn là MỘT việc.

    Cùng bài học ngoặc-vs-hai-chấm đã ép `listed_entities` phải ưu tiên ngoặc: dấu hai
    chấm giới thiệu THUỘC TÍNH, không phải đầu việc. Đếm nhầm ở đây sẽ đẩy đúng những
    đề gọn gàng nhất sang team.
    """
    from my_crew.agent.sprint_intake import _distinct_asks

    brief = "So sánh 5 dịch vụ (A, B, C, D, E): giá, chứng chỉ, chính sách hoàn tiền"
    assert _distinct_asks(brief) == 1
    assert classify_brief(brief)[0] is True


def test_the_measured_benchmark_brief_still_routes_to_sprint():
    """Đề đã đo thật (benchmark C): sprint thắng team cả ba trục — giữ nguyên hướng."""
    brief = (
        "Khảo sát 5 dịch vụ streaming nhạc (Spotify, YouTube Music, Apple Music, "
        "Zing MP3, Nhaccuatui): giá gói cá nhân, kho nhạc Việt, chất lượng âm thanh"
    )
    assert classify_brief(brief)[0] is True


# --- sprint_intake fail-open ---------------------------------------------------------


_STAFF = [("agent-a", "content"), ("agent-b", "research")]


def test_intake_prompt_demands_a_data_freshness_criterion_for_web_briefs():
    """Live UAT: 7/2024 figures passed review for a 2026 question — no criterion asked
    about recency. Same snippet-compatible shape as the decompose rule: a note when the
    source dates its own data, never access-date metadata, never rejecting old figures
    that have no newer source."""
    assert "ĐỘ TƯƠI" in intake_mod._INTAKE_SYSTEM
    assert "KHÔNG loại số liệu chỉ vì cũ" in intake_mod._INTAKE_SYSTEM


def test_intake_uses_the_models_plan_when_it_is_well_formed(monkeypatch):
    payload = (
        '{"goal":"So sánh 5 dịch vụ streaming","acceptance":"- Đủ 5 tên\\n- Có giá",'
        '"assigned_to":"agent-b","needs_web":true}'
    )
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m, **_kw: SimpleNamespace(content=payload,
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
        lambda: (SimpleNamespace(complete=lambda m, **_kw: SimpleNamespace(content=content,
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
        lambda: (SimpleNamespace(complete=lambda m, **_kw: SimpleNamespace(content=payload,
                                                                    cost_usd=0.0)), None),
    )
    plan, _ = intake_mod.sprint_intake("khảo sát", _STAFF)
    assert plan.assigned_to in {"agent-a", "agent-b"}


def test_intake_cannot_override_a_ceo_named_pic(monkeypatch):
    payload = '{"goal":"g","acceptance":"","assigned_to":"agent-b"}'
    monkeypatch.setattr(
        mod, "_build_llm",
        lambda: (SimpleNamespace(complete=lambda m, **_kw: SimpleNamespace(content=payload,
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
    assert steps[0].needs_review is True  # sprint luôn mang cờ review — không zero-eyes
    assert steps[0].needs_web is True
    assert steps[0].external_write is False


_TEAM_SHAPED_BRIEF = "\n".join([
    "làm giúp mấy việc này:",
    "- dựng slide cho buổi họp",
    "- soạn kịch bản demo",
    "- chuẩn bị bản dùng thử cho khách",
])


def test_team_shaped_brief_still_goes_through_decompose(monkeypatch):
    calls = _wire(monkeypatch)
    slots = {"brief": _TEAM_SHAPED_BRIEF}

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
    slots = {"brief": f"sprint: {_TEAM_SHAPED_BRIEF}"}

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


# --- downgrade_to_sprint: a team plan that turned out to be one person's work --------


def _plan(*steps, pic="agent-a"):
    from my_crew.agent.task_decomposition import DecomposedTask

    return DecomposedTask(steps=tuple(steps), pic_id=pic)


def _step(step_id, assignee, **kw):
    from my_crew.agent.task_decomposition import TeamStepPlan

    return TeamStepPlan(step_id=step_id, title=f"bước {step_id}", assigned_to=assignee, **kw)


_DOWNGRADE_BRIEF = "khảo sát 5 dịch vụ streaming và so sánh giá"


def test_downgrade_folds_a_linear_one_person_plan_into_a_sprint():
    task = _plan(
        _step("s1", "agent-b", acceptance="- Đủ 5 tên", needs_web=True),
        _step("s2", "agent-b", deps=("s1",), acceptance="- Có giá từng gói"),
    )

    plan = intake_mod.downgrade_to_sprint(_DOWNGRADE_BRIEF, task)

    assert plan is not None
    assert plan.assigned_to == "agent-b"
    assert plan.goal == _DOWNGRADE_BRIEF  # đề của CEO, không phải title bước
    assert plan.acceptance.splitlines() == ["- Đủ 5 tên", "- Có giá từng gói"]
    assert plan.needs_web is True  # any() — một bước cần web là cả việc cần web


def test_downgrade_folds_the_three_step_one_person_chain_seen_in_lanes8():
    """The measured motivation for the 3-step ceiling: lanes8's music_streaming brief
    decomposed into three analyst steps in single file — no cross-review, no
    coordination, just orchestration cost — and then stalled. That shape is one
    person's work wearing a team plan."""
    task = _plan(
        _step("s1", "agent-b", acceptance="- Đủ 5 nền tảng", needs_web=True),
        _step("s2", "agent-b", deps=("s1",), acceptance="- Có giá từng gói"),
        _step("s3", "agent-b", deps=("s2",), acceptance="- Bảng so sánh cuối"),
    )

    plan = intake_mod.downgrade_to_sprint(_DOWNGRADE_BRIEF, task)

    assert plan is not None
    assert plan.assigned_to == "agent-b"
    assert plan.acceptance.splitlines() == [
        "- Đủ 5 nền tảng", "- Có giá từng gói", "- Bảng so sánh cuối",
    ]
    assert plan.needs_web is True


def test_downgrade_folds_a_single_step_plan_too():
    plan = intake_mod.downgrade_to_sprint(
        _DOWNGRADE_BRIEF, _plan(_step("s1", "agent-a", acceptance="- Xong")))

    assert plan is not None and plan.assigned_to == "agent-a"


@pytest.mark.parametrize(
    ("task_factory", "why"),
    [
        (lambda: _plan(_step("s1", "agent-a"), _step("s2", "agent-b", deps=("s1",))),
         "hai người thật sự"),
        (lambda: _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",)),
                       _step("s3", "agent-a", deps=("s2",)),
                       _step("s4", "agent-a", deps=("s3",))),
         "bốn bước — quá trần degenerate"),
        (lambda: _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",)),
                       _step("s3", "agent-a", deps=("s1",))),
         "bước 3 nhảy cóc về bước 1 — không phải chuỗi tuyến tính"),
        (lambda: _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",)),
                       _step("s3", "agent-b", deps=("s2",))),
         "ba bước nhưng hai người — có bàn giao chéo thật"),
        (lambda: _plan(_step("s1", "agent-a", needs_shell=True),
                       _step("s2", "agent-a", deps=("s1",))),
         "cần shell → tier sandbox"),
        (lambda: _plan(_step("s1", "agent-a", external_write=True),
                       _step("s2", "agent-a", deps=("s1",))),
         "ghi ra ngoài → mất vòng review bắt buộc"),
        (lambda: _plan(_step("s1", "agent-a"), _step("s2", "agent-a")),
         "hai bước rời nhau, không tuyến tính"),
        # `DecomposedTask` cấm plan rỗng ở schema, nên hình dạng này chỉ tới được đây
        # qua một object khác — guard vẫn phải đứng, hàm không ràng buộc kiểu đầu vào.
        (lambda: SimpleNamespace(steps=()), "kế hoạch rỗng"),
    ],
)
def test_downgrade_declines_every_shape_it_cannot_prove_is_one_persons_work(
    task_factory, why,
):
    assert intake_mod.downgrade_to_sprint(_DOWNGRADE_BRIEF, task_factory()) is None, why


@pytest.mark.parametrize("brief", [
    "khảo sát bảng giá rồi gửi email cho khách",
    "tổng hợp log rồi chạy script dọn dẹp",
])
def test_downgrade_still_obeys_the_hard_refusals(brief):
    """A degenerate SHAPE never lifts a safety exclusion: the sprint step hardcodes
    external_write/needs_shell=False, so folding one of these in would drop the review
    `review_insert` keeps mandatory for that step kind at every band."""
    task = _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",)))

    assert intake_mod.downgrade_to_sprint(brief, task) is None


def test_a_degenerate_team_plan_is_persisted_as_a_sprint_step(monkeypatch):
    """End-to-end through preview: the heuristic sent this brief to team, decompose came
    back with one person's work, and the draft plan is a sprint row.

    The brief is deliberately one the STRUCTURAL heuristic diverts (three separate asks
    on their own lines) — that is the only way the downgrade net is reachable now that
    the router defaults to sprint.
    """
    calls = _wire(monkeypatch)

    def _one_person(brief, staff, pic=""):
        calls["decompose"] += 1
        return _plan(_step("s1", "agent-a", acceptance="- Xong", needs_web=True),
                     _step("s2", "agent-a", deps=("s1",))), 0.01

    monkeypatch.setattr(mod, "_decompose_with_retries", _one_person)
    slots = {"brief": _TEAM_SHAPED_BRIEF}

    reply = mod.preview_assign_team_task(slots)

    assert calls == {"decompose": 1, "intake": 0}  # hạ chế độ KHÔNG tốn lượt gọi model
    assert "SPRINT" in reply
    steps = _steps_of(slots["task_id"])
    assert [s.step_type for s in steps] == ["sprint"]
    assert steps[0].assigned_to == "agent-a"


def test_a_ceo_forced_team_plan_is_never_downgraded(monkeypatch):
    """"team:" is the assigning human's decision, not a guess — the shape heuristic does
    not get to overrule it."""
    calls = _wire(monkeypatch)

    def _one_person(brief, staff, pic=""):
        calls["decompose"] += 1
        return _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",))), 0.01

    monkeypatch.setattr(mod, "_decompose_with_retries", _one_person)
    slots = {"brief": "team: chuẩn bị demo cho khách hàng lớn"}

    mod.preview_assign_team_task(slots)

    assert [s.step_type for s in _steps_of(slots["task_id"])] == ["work", "work"]


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


# --- v78 routing log -----------------------------------------------------------------


def _route_of(task_id):
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        return store.get_route(task_id)
    finally:
        store.close()


@pytest.mark.parametrize(
    ("brief", "mode", "source"),
    [
        ("sprint: chuẩn bị demo", "sprint", "prefix"),
        ("team: khảo sát 5 dịch vụ streaming", "team", "prefix"),
        ("sprint: khảo sát rồi gửi email cho khách", "team", "refusal"),
        ("khảo sát 5 dịch vụ streaming và so sánh giá", "sprint", "heuristic"),
        ("nghiên cứu thị trường, chia việc cho mỗi người một mảng", "team", "refusal"),
        (_TEAM_SHAPED_BRIEF, "team", "heuristic"),
    ],
)
def test_every_router_branch_records_which_layer_decided(monkeypatch, brief, mode, source):
    """Mỗi lớp phễu để lại dấu riêng — không lớp nào đi qua mà không khai tên.

    Đây là điều kiện để sau này trả lời được "ngưỡng nào đang sai": nếu mọi task chỉ
    ghi mode mà không ghi lớp nào quyết, một tỉ lệ bế tắc cao không chỉ ra được nên
    chỉnh heuristic hay chỉnh rào an toàn.
    """
    _wire(monkeypatch)
    slots = {"brief": brief}

    mod.preview_assign_team_task(slots)

    route = _route_of(slots["task_id"])
    assert (route["mode"], route["source"]) == (mode, source)
    assert route["reason"]
    assert set(route["signals"]) == {"brief_len", "entities", "distinct_asks",
                                     "material_transform"}


def test_a_downgraded_plan_is_logged_as_a_downgrade_not_a_heuristic_win(monkeypatch):
    calls = _wire(monkeypatch)

    def _one_person(brief, staff, pic=""):
        calls["decompose"] += 1
        return _plan(_step("s1", "agent-a"), _step("s2", "agent-a", deps=("s1",))), 0.01

    monkeypatch.setattr(mod, "_decompose_with_retries", _one_person)
    slots = {"brief": _TEAM_SHAPED_BRIEF}

    mod.preview_assign_team_task(slots)

    route = _route_of(slots["task_id"])
    assert (route["mode"], route["source"]) == ("sprint", "downgrade")


def test_the_routing_record_carries_numbers_not_the_brief(monkeypatch):
    """Bản ghi nằm cạnh outcome trong DB — nó phải rẻ và không mang nội dung việc."""
    _wire(monkeypatch)
    secret = "khảo sát giá thương vụ Zenith trước khi ký"
    slots = {"brief": secret}

    mod.preview_assign_team_task(slots)

    import json

    assert "Zenith" not in json.dumps(_route_of(slots["task_id"]), ensure_ascii=False)
