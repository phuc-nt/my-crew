"""v78 effort tier: intake chấm độ khó, sprint chạy rẻ hơn cho đề dễ.

Ba mảnh ghép, mỗi mảnh một nhóm test dưới đây:
  1. intake trả thêm `effort`, và MỌI hỏng hóc rơi về "medium" — vì medium chính là
     hành vi cũ, nên một trường mới trả sai không được phép làm đổi gì cả.
  2. bậc đi theo bản ghi định tuyến (`route_json`), không phải cột mới trong
     `team_steps`: không nâng cấp lược đồ, và bậc nằm cạnh kết cục để đếm được.
  3. chỉ "low" đổi hành vi runner (model role + budget). medium/high chạy y hệt trước.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as ops_mod
import my_crew.agent.sprint_intake as intake_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.sprint_runner as runner_mod
from my_crew.agent.sprint_intake import EFFORT_TIERS, SprintPlan

_STAFF = [("agent-a", "content"), ("agent-b", "research")]


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _stub_llm(monkeypatch, payload: str) -> None:
    monkeypatch.setattr(
        ops_mod, "_build_llm",
        lambda: (SimpleNamespace(
            complete=lambda m, **_kw: SimpleNamespace(content=payload, cost_usd=0.0)
        ), None),
    )


# --- 1. intake chấm bậc --------------------------------------------------------------


def test_the_intake_prompt_asks_for_effort_and_breaks_ties_downward():
    """Quy tắc omp: phân vân thì chọn bậc thấp. Không có câu đó thì model nhẹ có xu
    hướng chấm cao cho mọi thứ trông dài, và bậc mất hết giá trị phân loại."""
    system = intake_mod._INTAKE_SYSTEM
    assert '"effort"' in system
    assert "PHÂN VÂN GIỮA HAI BẬC THÌ CHỌN BẬC THẤP HƠN" in system


def test_there_are_exactly_three_tiers():
    """Ba chứ không phải bốn — xem chú thích của `EFFORT_TIERS`. Test này tồn tại để
    việc thêm bậc thứ tư là một quyết định có ý thức chứ không phải một dòng lọt qua."""
    assert EFFORT_TIERS == ("low", "medium", "high")


@pytest.mark.parametrize("value", ["low", "medium", "high"])
def test_intake_carries_every_valid_tier_through(monkeypatch, value):
    _stub_llm(monkeypatch,
              '{"goal":"g","acceptance":"- a","assigned_to":"agent-a",'
              f'"needs_web":false,"effort":"{value}"}}')
    plan, _cost = intake_mod.sprint_intake("viết một đoạn giới thiệu", _STAFF)
    assert plan.effort == value


@pytest.mark.parametrize(
    "raw",
    [
        '"effort":"LOW"',          # hoa/thường
        '"effort":" low "',        # thừa khoảng trắng
    ],
)
def test_intake_normalises_a_sloppy_tier(monkeypatch, raw):
    _stub_llm(monkeypatch,
              '{"goal":"g","acceptance":"","assigned_to":"agent-a",' + raw + "}")
    plan, _ = intake_mod.sprint_intake("viết một đoạn", _STAFF)
    assert plan.effort == "low"


@pytest.mark.parametrize(
    "raw",
    [
        '"effort":"trung bình"',   # model trả tiếng Việt
        '"effort":"very hard"',    # ngoài thang
        '"effort":null',
        '"effort":3',              # sai kiểu
        '"needs_web":true',        # thiếu hẳn trường
    ],
)
def test_a_bad_or_missing_tier_reads_as_medium(monkeypatch, raw):
    """Fail-open về medium ở mọi nhánh: medium là hành vi cũ nguyên vẹn, nên đường
    xấu nhất của trường mới này là "không có gì thay đổi"."""
    _stub_llm(monkeypatch,
              '{"goal":"g","acceptance":"","assigned_to":"agent-a",' + raw + "}")
    plan, _ = intake_mod.sprint_intake("viết một đoạn", _STAFF)
    assert plan.effort == "medium"


def test_a_dead_intake_still_reads_as_medium(monkeypatch):
    """Nhánh fail-open sẵn có (model chết) không được kéo theo bậc rác."""
    def _boom():
        raise RuntimeError("provider down")

    monkeypatch.setattr(ops_mod, "_build_llm", _boom)
    plan, _ = intake_mod.sprint_intake("tổng hợp tin tức", _STAFF)
    assert plan.effort == "medium"


def test_a_team_plan_downgraded_to_sprint_reads_as_medium():
    """`downgrade_to_sprint` không gọi intake nên không có ai chấm bậc — nó phải nhận
    medium, tức là chạy y như trước khi có tính năng này."""
    steps = (SimpleNamespace(step_id="s1", title="t", assigned_to="agent-a", deps=(),
                             acceptance="- x", needs_shell=False, needs_web=True,
                             external_write=False),)
    plan = intake_mod.downgrade_to_sprint("viết một đoạn giới thiệu",
                                          SimpleNamespace(steps=steps))
    assert plan is not None
    assert plan.effort == "medium"


# --- 2. bậc đi theo bản ghi định tuyến ------------------------------------------------


def _wire_preview(monkeypatch, effort: str):
    monkeypatch.setattr(ops_mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(ops_mod, "_staff_roster", lambda: _STAFF)
    monkeypatch.setattr(
        company_mod, "load_company",
        lambda path=None: SimpleNamespace(name="", coordinator_id="coord-1",
                                          team_task_cap_usd=2.0,
                                          team_task_auto_confirm=False, autopilot=False),
    )
    monkeypatch.setattr(
        intake_mod, "sprint_intake",
        lambda brief, staff, pic="": (
            SprintPlan(goal="g", acceptance="- a", assigned_to="agent-a",
                       needs_web=False, effort=effort), 0.0),
    )


def _route_of(task_id: str) -> dict:
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        return store.get_route(task_id) or {}
    finally:
        store.close()


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_the_route_record_keeps_the_tier(monkeypatch, effort):
    _wire_preview(monkeypatch, effort)
    slots = {"brief": "viết một đoạn giới thiệu"}
    ops_mod.preview_assign_team_task(slots)
    assert _route_of(slots["task_id"])["effort"] == effort


def test_only_high_raises_the_measurement_flag(monkeypatch):
    """`effort_high` là cờ ĐỂ ĐO, không phải để rẽ lane ở vòng này. Nó tồn tại riêng
    bên cạnh `effort` để `route_stats` đếm mà không phải hiểu thang bậc."""
    for effort, expected in (("low", False), ("medium", False), ("high", True)):
        _wire_preview(monkeypatch, effort)
        slots = {"brief": "viết một đoạn giới thiệu"}
        ops_mod.preview_assign_team_task(slots)
        assert bool(_route_of(slots["task_id"]).get("effort_high")) is expected


def test_the_tier_survives_the_dead_end_stamp(monkeypatch):
    """Dấu bế tắc ghi đè `source` nhưng phải giữ `effort` — nếu không thì con số duy
    nhất tính năng này cần ("bậc nào hay bế tắc") vĩnh viễn bằng 0."""
    import my_crew.runtime.team_tick_collaborators as tick_mod

    _wire_preview(monkeypatch, "high")
    slots = {"brief": "viết một đoạn giới thiệu"}
    ops_mod.preview_assign_team_task(slots)
    tick_mod._mark_route_dead_end(slots["task_id"])

    route = _route_of(slots["task_id"])
    assert route["source"] == "dead_end"
    assert route["effort"] == "high"


def test_effort_of_task_reads_the_record(monkeypatch):
    _wire_preview(monkeypatch, "low")
    slots = {"brief": "viết một đoạn giới thiệu"}
    ops_mod.preview_assign_team_task(slots)
    assert runner_mod.effort_of_task(slots["task_id"]) == "low"


def test_effort_of_task_is_medium_for_anything_it_cannot_read():
    """Task không tồn tại — tức là mọi lỗi đọc sổ. Tham số này là tối ưu hoá: hạ sai
    bậc mất tiền, còn ném lỗi ở đây thì mất cả bước việc."""
    assert runner_mod.effort_of_task("khong-co-that") == "medium"


# --- 3. chỉ "low" đổi hành vi runner --------------------------------------------------


class _RoleRecordingLlm:
    """Như `_FakeLlm` của `test_sprint_runner` nhưng GIỮ LẠI `role` từng lượt gọi —
    đó chính là thứ bậc độ khó điều khiển."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.roles: list[str] = []

    def complete(self, messages, **kw):
        self.roles.append(kw.get("role", ""))
        reply = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(content=reply, cost_usd=0.0)


@pytest.fixture
def role_llm(monkeypatch):
    def _install(replies: list[str]) -> _RoleRecordingLlm:
        fake = _RoleRecordingLlm(replies)
        monkeypatch.setattr(runner_mod, "LlmClient", lambda _s: fake, raising=False)
        import my_crew.llm.client as client_mod

        monkeypatch.setattr(client_mod, "LlmClient", lambda _s: fake)
        return fake

    return _install


def _run(effort: str, *, replies: list[str], goal: str, queries_box: list | None = None):
    def _prefetch(_loaded, _settings, queries):
        if queries_box is not None:
            queries_box.append(list(queries))
        return "\n".join(f"- kết quả cho {q}" for q in queries)

    work = runner_mod.build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance="- có số liệu",
        prefetch=_prefetch,
        effort=effort,
    )
    return work(goal, "", None)


@pytest.mark.parametrize(
    ("effort", "expected_role"),
    [("low", "sprint_low"), ("medium", "content"), ("high", "content")],
)
def test_the_tier_picks_the_model_role(role_llm, effort, expected_role):
    """`sprint_low` chỉ là TÊN vai: công ty không khai model cho nó thì resolver rơi
    về chuỗi model chung, nên bậc thấp suy biến thành "chỉ rút budget"."""
    fake = role_llm(["bản nháp đầy đủ"])
    _run(effort, replies=[], goal="viết đoạn giới thiệu ngắn")
    assert fake.roles
    assert set(fake.roles) == {expected_role}


def test_a_low_effort_revise_stays_on_the_cheap_model(role_llm):
    """Đổi model giữa mạch hội thoại tích luỹ nghĩa là bản sửa do một model chưa từng
    viết bản nháp nó đang sửa — cả hai lượt phải cùng vai."""
    fake = role_llm(["nháp thiếu dữ liệu", "bản sửa"])
    _run("low", replies=[], goal="So sánh 3 sàn: Shopee, Lazada và Tiki")
    assert fake.roles
    assert set(fake.roles) == {"sprint_low"}


def test_low_effort_runs_at_most_one_revise_round(role_llm):
    """Đề intake chấm dễ mà trượt kiểm phủ hai lần thì không phải đề dễ — đường đúng
    là bế tắc → giao lại cho đội, không phải vòng lặp thứ ba của cùng pipeline."""
    low = role_llm(["nháp trống", "vẫn trống", "vẫn trống", "vẫn trống"])
    _run("low", replies=[], goal="So sánh 3 sàn: Shopee, Lazada và Tiki")
    low_calls = len(low.roles)

    medium = role_llm(["nháp trống", "vẫn trống", "vẫn trống", "vẫn trống"])
    _run("medium", replies=[], goal="So sánh 3 sàn: Shopee, Lazada và Tiki")

    assert low_calls < len(medium.roles), (
        "bậc thấp phải cắt bớt vòng sửa so với bậc vừa"
    )
    assert low_calls <= 1 + runner_mod.LOW_EFFORT_REVISE_ROUNDS


def test_low_effort_trims_the_search_budget(role_llm):
    role_llm(["bản nháp"])
    box: list[list[str]] = []
    _run("low", replies=[], goal="So sánh 6 sàn: Shopee, Lazada, Tiki, Sendo, Chợ Tốt và Vỏ Sò",
         queries_box=box)
    assert box
    assert len(box[0]) <= runner_mod.LOW_EFFORT_PREFETCH_CAP


def test_medium_keeps_the_full_search_budget(role_llm):
    """Bậc vừa là hành vi cũ: nếu test này đổ thì tính năng đã làm chậm/rẻ đi những
    việc chưa từng ai yêu cầu đổi."""
    role_llm(["bản nháp"])
    box: list[list[str]] = []
    _run("medium", replies=[],
         goal="So sánh 6 sàn: Shopee, Lazada, Tiki, Sendo, Chợ Tốt và Vỏ Sò",
         queries_box=box)
    assert box
    assert len(box[0]) > runner_mod.LOW_EFFORT_PREFETCH_CAP


def test_an_unknown_tier_runs_exactly_like_medium(role_llm):
    """Đường phòng thủ cuối: giá trị lạ lọt tới runner (sổ hỏng, bản ghi cũ) phải
    không đổi gì cả."""
    strange = role_llm(["bản nháp"])
    box_strange: list[list[str]] = []
    _run("kho-lam", replies=[], goal="So sánh 6 sàn: Shopee, Lazada, Tiki, Sendo, "
         "Chợ Tốt và Vỏ Sò", queries_box=box_strange)

    medium = role_llm(["bản nháp"])
    box_medium: list[list[str]] = []
    _run("medium", replies=[], goal="So sánh 6 sàn: Shopee, Lazada, Tiki, Sendo, "
         "Chợ Tốt và Vỏ Sò", queries_box=box_medium)

    assert strange.roles == medium.roles
    assert box_strange == box_medium


# --- 4. đếm được qua route_stats ------------------------------------------------------


def _seed_route(task_id: str, route: dict) -> None:
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.create_task(task_id=task_id, title="việc thử", pic_id="agent-a")
        store.set_route(task_id, route)
    finally:
        store.close()


def test_route_stats_counts_by_tier_and_names_the_stuck_ones():
    from my_crew.agent.ops_route_stats import run_route_stats

    _seed_route("t-low", {"mode": "sprint", "source": "heuristic", "effort": "low"})
    _seed_route("t-high", {"mode": "sprint", "source": "dead_end", "effort": "high"})
    _seed_route("t-team", {"mode": "team", "source": "heuristic"})

    text = run_route_stats({})

    assert "Độ khó" in text
    assert "dễ: 1" in text
    assert "khó: 1, 1 bế tắc" in text


def test_route_stats_omits_the_tier_table_when_nothing_carries_one():
    """Việc giao trước v78 không có bậc — bảng phải VẮNG hẳn thay vì hiện toàn số 0
    hoặc gộp nhầm việc chạy đội vào "vừa"."""
    from my_crew.agent.ops_route_stats import run_route_stats

    _seed_route("t-old", {"mode": "team", "source": "heuristic"})

    assert "Độ khó" not in run_route_stats({})
