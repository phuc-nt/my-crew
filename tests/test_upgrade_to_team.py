"""v78 `upgrade_to_team`: chiều sprint→team giữ lại bối cảnh thay vì vứt đi.

Trước lệnh này, một chuyến sprint bế tắc chỉ được gợi ý "CEO giao lại bằng `team:`" —
CEO gõ lại đề bằng tay, và mọi thứ chuyến sprint đã làm ra rơi xuống đất dù tiền cho
vòng tìm hiểu đó đã trả rồi.

Ba nhóm test dưới đây ghim: điều kiện tiên quyết (không nâng nhầm việc), bối cảnh thật
sự đi vào đề mới (và đi vào dưới dạng nội dung không tin cậy), và hệ quả sau khi nâng.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as assign_mod
import my_crew.agent.ops_upgrade_to_team as mod
import my_crew.profile.loader as loader_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.registry as registry_mod
from my_crew.runtime.registry import RegistryEntry


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


def _wire(monkeypatch, seen: dict | None = None):
    """Đường giao việc thật, chỉ thay tầng model bằng bản đóng hộp.

    Vá `_build_llm` chứ không vá `_decompose_with_retries`: nâng cấp phải đi qua đúng
    đường mà CEO đi, kể cả khâu bóc tiền tố ép chế độ và khâu dựng prompt.
    """
    monkeypatch.setattr(
        company_mod, "load_company",
        lambda *a, **k: SimpleNamespace(name="", coordinator_id="coord-1",
                                        team_task_cap_usd=2.0, team_task_concurrency=2,
                                        team_task_auto_confirm=False, autopilot=False),
    )
    telegram = SimpleNamespace(bot_token_env="X", chat_ids=("op",), poll_minutes=5,
                               ops_operator_id="op")

    def _load_profile(agent_id, *, data_dir):
        domain = {"coord-1": "pm", "content": "office", "researcher": "office"}[agent_id]
        # Two DISTINCT roles: the researcher has web access, the writer does not. With
        # identical tools + model the planner folds them into one step by design.
        return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=telegram),
                               soul="", project="", memory="",
                               web_search=(agent_id == "researcher"))

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    monkeypatch.setattr(
        registry_mod, "load_registry",
        lambda: (RegistryEntry(id="coord-1", enabled=True),
                 RegistryEntry(id="content", enabled=True),
                 RegistryEntry(id="researcher", enabled=True)),
    )

    def _canned_llm():
        class _Result:
            cost_usd = 0.001
            content = json.dumps({
                "steps": [
                    {"step_id": "s1", "title": "thu thập", "assigned_to": "researcher",
                     "deps": [], "acceptance": "kèm 3 link nguồn"},
                    {"step_id": "s2", "title": "tổng hợp", "assigned_to": "content",
                     "deps": ["s1"], "acceptance": "bản nộp có bảng so sánh"},
                ],
                "pic_id": "content",
                "requires_approval": True,
            })

        class _Llm:
            def complete(self, messages, **_kw):
                if seen is not None:
                    seen["prompt"] = "\n".join(
                        str(m.get("content", "")) if isinstance(m, dict)
                        else str(getattr(m, "content", "")) for m in messages
                    )
                return _Result()

        return _Llm(), None

    monkeypatch.setattr(assign_mod, "_build_llm", _canned_llm)


def _seed_sprint(task_id="dead-1", *, status="stalled", step_type="sprint", route=None,
                 brief="so sánh giá 3 dịch vụ lưu trữ", final_summary=None):
    store = _store()
    try:
        store.create_task(task_id=task_id, title=brief[:60], original_request=brief,
                          assigned_by="ceo", pic_id="content")
        store.set_plan(task_id, [{
            "step_id": "sprint", "title": brief[:60], "assigned_to": "content",
            "deps": [], "acceptance": "xong", "step_type": step_type,
        }], "hash-1")
        if route is not None:
            store.set_route(task_id, route)
        if final_summary:
            store.set_delivery(task_id, status="pending", summary=final_summary)
        store.set_task_status(task_id, status)
        return store.get(task_id)
    finally:
        store.close()


def _write_artifact(task, payload):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_step_artifact(team_tasks_root(), task.id, task.steps[0].seq, payload)


# --- điều kiện tiên quyết ------------------------------------------------------------


def test_refuses_a_task_that_never_ran_in_sprint_mode():
    _seed_sprint("team-1", step_type="work")
    with pytest.raises(ValueError, match="không chạy chế độ nhanh"):
        mod.run_upgrade_to_team({"task_id": "team-1"})


def test_refuses_a_sprint_that_is_still_running():
    """Không cắt ngang việc đang chạy: vừa bỏ phí lượt đang chạy, vừa tạo ra hai việc
    cùng làm một đề."""
    _seed_sprint("live-1", status="running")
    with pytest.raises(ValueError, match="chỉ nâng cấp được"):
        mod.run_upgrade_to_team({"task_id": "live-1"})


def test_refuses_an_unknown_task():
    with pytest.raises(ValueError, match="không tìm thấy"):
        mod.run_upgrade_to_team({"task_id": "khong-co"})


def test_refuses_an_empty_task_id():
    with pytest.raises(ValueError, match="cần mã việc"):
        mod.run_upgrade_to_team({"task_id": "  "})


def test_refuses_to_upgrade_something_that_is_already_an_upgrade():
    """Cái chặn vòng lặp: nâng→chết→nâng là chuỗi không đáy, mỗi mắt tốn trọn một lượt
    decompose cộng cả một chuyến chạy."""
    _seed_sprint("chain-2", route={"mode": "team", "source": "upgrade",
                                   "previous_task": "chain-1"})
    with pytest.raises(ValueError, match="vốn đã là bản nâng cấp"):
        mod.run_upgrade_to_team({"task_id": "chain-2"})


def test_a_failed_precondition_leaves_no_half_built_task(monkeypatch):
    """Cửa kiểm phải chặn TRƯỚC khi có gì được dựng — nếu không, một lần từ chối vẫn
    để lại một draft mồ côi."""
    _wire(monkeypatch)
    _seed_sprint("live-2", status="running")
    with pytest.raises(ValueError):
        mod.run_upgrade_to_team({"task_id": "live-2"})

    store = _store()
    try:
        assert [t.id for t in store.list_recent_tasks(include_planning=True)] == ["live-2"]
    finally:
        store.close()


# --- bối cảnh đi vào đề mới ----------------------------------------------------------


def test_the_new_brief_carries_the_original_request(monkeypatch):
    seen: dict = {}
    _wire(monkeypatch, seen)
    _seed_sprint("dead-1", brief="so sánh giá 3 dịch vụ lưu trữ")

    mod.run_upgrade_to_team({"task_id": "dead-1"})

    assert "so sánh giá 3 dịch vụ lưu trữ" in seen["prompt"]


def test_the_upgrade_goes_through_the_ceos_own_mode_prefix(monkeypatch):
    """`team:` là tiền tố ép chế độ có sẵn. Dùng lại nó thay vì mở đường vòng riêng —
    một đường vòng sẽ là chỗ duy nhất dựng được team task mà không qua `sprint_refusal`.
    Tiền tố bị BÓC trước khi tới decompose, nên dấu vết của nó là task mới có kế hoạch
    nhiều bước chứ không phải một đỉnh sprint."""
    _wire(monkeypatch)
    _seed_sprint("dead-2")

    mod.run_upgrade_to_team({"task_id": "dead-2"})

    store = _store()
    try:
        new = [t for t in store.list_recent_tasks(include_planning=True) if t.id != "dead-2"][0]
        assert len(new.steps) == 2
        assert [s.step_type for s in new.steps] != ["sprint"]
    finally:
        store.close()


def test_the_dead_sprints_draft_rides_along_as_context(monkeypatch):
    seen: dict = {}
    _wire(monkeypatch, seen)
    task = _seed_sprint("dead-3")
    _write_artifact(task, {"status": "needs_decision", "result_text": "Đã tra được giá A",
                           "self_check_failures": ["thiếu giá dịch vụ C"]})

    mod.run_upgrade_to_team({"task_id": "dead-3"})

    assert "Đã tra được giá A" in seen["prompt"]
    assert "thiếu giá dịch vụ C" in seen["prompt"]


def test_the_context_says_plainly_that_it_is_reference_not_a_plan(monkeypatch):
    """Không có câu này, decompose đọc bản nháp dở như thể đó là hướng đã duyệt và chép
    lại đúng sai lầm đã làm chuyến sprint chết."""
    seen: dict = {}
    _wire(monkeypatch, seen)
    task = _seed_sprint("dead-4")
    _write_artifact(task, {"result_text": "nháp"})

    mod.run_upgrade_to_team({"task_id": "dead-4"})

    assert "CHỈ ĐỂ THAM KHẢO" in seen["prompt"]
    assert "Đội tự quyết kế hoạch mới" in seen["prompt"]


def test_the_context_is_wrapped_as_untrusted_second_order_content(monkeypatch):
    """Kết quả dở dang do LLM sinh — cùng lớp rủi ro với verdict trong
    `_review_evidence_block`, nên phải được bọc y như vậy, không nối thẳng vào prompt."""
    seen: dict = {}
    _wire(monkeypatch, seen)
    task = _seed_sprint("dead-5")
    _write_artifact(task, {"result_text": "nội dung nháp"})

    mod.run_upgrade_to_team({"task_id": "dead-5"})

    assert "INTERNAL_STEP_RESULT" in seen["prompt"]


def test_a_huge_draft_is_truncated_before_it_is_wrapped(monkeypatch):
    """Thứ tự lấy từ `_review_evidence_block`: bọc rồi mới cắt sẽ xén mất dấu đóng và
    biến một khối được đánh dấu rõ ràng thành văn bản trôi nổi giữa prompt."""
    seen: dict = {}
    _wire(monkeypatch, seen)
    task = _seed_sprint("dead-6")
    _write_artifact(task, {"result_text": "x" * 9000})

    mod.run_upgrade_to_team({"task_id": "dead-6"})

    assert "===END===" in seen["prompt"]
    assert "x" * 3000 not in seen["prompt"]


def test_the_give_up_reason_rides_along(monkeypatch):
    seen: dict = {}
    _wire(monkeypatch, seen)
    _seed_sprint("dead-7", final_summary="KHÔNG LÀM ĐƯỢC: không tra được giá C.")

    mod.run_upgrade_to_team({"task_id": "dead-7"})

    assert "không tra được giá C" in seen["prompt"]


def test_a_missing_artifact_still_upgrades_on_the_bare_brief(monkeypatch):
    """Bối cảnh là garnish (tiền lệ `_review_evidence_block`): thiếu artifact thì nâng
    cấp vẫn phải chạy, chỉ là không có phần tham khảo."""
    seen: dict = {}
    _wire(monkeypatch, seen)
    _seed_sprint("dead-8", brief="đề gốc trần")

    text = mod.run_upgrade_to_team({"task_id": "dead-8"})

    assert "đề gốc trần" in seen["prompt"]
    assert "CHỈ ĐỂ THAM KHẢO" not in seen["prompt"]
    assert "dead-8" in text


def test_a_corrupt_artifact_never_blocks_the_upgrade(monkeypatch):
    seen: dict = {}
    _wire(monkeypatch, seen)
    task = _seed_sprint("dead-9")
    from my_crew.agent.team_task_artifact import step_artifact_path
    from my_crew.runtime.team_task_paths import team_tasks_root

    path = step_artifact_path(team_tasks_root(), task.id, task.steps[0].seq)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{không phải json", encoding="utf-8")

    mod.run_upgrade_to_team({"task_id": "dead-9"})

    assert seen["prompt"]  # vẫn giao được


# --- hệ quả sau khi nâng --------------------------------------------------------------


def test_the_old_task_is_left_exactly_as_it_was(monkeypatch):
    """Việc cũ là bằng chứng bộ định tuyến đoán chệch — sửa nó đi thì mất dữ liệu hồi
    cứu, mà nâng cấp cũng chẳng cần sửa gì ở đó."""
    _wire(monkeypatch)
    _seed_sprint("dead-10")

    mod.run_upgrade_to_team({"task_id": "dead-10"})

    store = _store()
    try:
        old = store.get("dead-10")
    finally:
        store.close()
    assert old.status == "stalled"
    assert [s.step_id for s in old.steps] == ["sprint"]


def test_the_new_task_records_the_chain_it_came_from(monkeypatch):
    _wire(monkeypatch)
    _seed_sprint("dead-11")

    mod.run_upgrade_to_team({"task_id": "dead-11"})

    store = _store()
    try:
        new_id = [t.id for t in store.list_recent_tasks(include_planning=True)
                  if t.id != "dead-11"][0]
        route = store.get_route(new_id)
    finally:
        store.close()
    assert route["source"] == "upgrade"
    assert route["previous_task"] == "dead-11"


def test_the_recorded_chain_is_what_blocks_the_next_upgrade(monkeypatch):
    """Ghim vòng khép kín: dấu mà `run_upgrade_to_team` đóng vào phải đúng là dấu mà
    `_already_upgraded` đọc. Hai nửa lệch nhau thì cái chặn vòng lặp thành vô hiệu."""
    _wire(monkeypatch)
    _seed_sprint("dead-12")
    mod.run_upgrade_to_team({"task_id": "dead-12"})

    store = _store()
    try:
        new_id = [t.id for t in store.list_recent_tasks(include_planning=True)
                  if t.id != "dead-12"][0]
        store.set_plan(new_id, [{"step_id": "sprint", "title": "t",
                                 "assigned_to": "content", "deps": [],
                                 "step_type": "sprint"}], "hash-2")
        store.set_task_status(new_id, "stalled")
    finally:
        store.close()

    with pytest.raises(ValueError, match="vốn đã là bản nâng cấp"):
        mod.run_upgrade_to_team({"task_id": new_id})


def test_the_new_plan_still_goes_through_the_ceos_confirm_gate(monkeypatch):
    """Nâng cấp không phải lý do để bỏ qua cửa duyệt kế hoạch."""
    _wire(monkeypatch)
    _seed_sprint("dead-13")

    text = mod.run_upgrade_to_team({"task_id": "dead-13"})

    assert "xác nhận" in text.lower()
    store = _store()
    try:
        new = [t for t in store.list_recent_tasks(include_planning=True)
               if t.id != "dead-13"][0]
        assert new.status == "planning"  # chưa chạy
    finally:
        store.close()


def test_preview_describes_the_change_without_creating_anything(monkeypatch):
    _wire(monkeypatch)
    _seed_sprint("dead-14")

    text = mod.preview_upgrade_to_team({"task_id": "dead-14"})

    assert "CẢ ĐỘI" in text
    store = _store()
    try:
        assert [t.id for t in store.list_recent_tasks(include_planning=True)] == ["dead-14"]
    finally:
        store.close()


def test_preview_refuses_the_same_things_run_refuses():
    """Preview chạy đúng bộ điều kiện của run — nếu không, CEO thấy 'sẽ làm X' rồi
    bấm xác nhận và mới ăn lỗi."""
    _seed_sprint("live-3", status="running")
    with pytest.raises(ValueError, match="chỉ nâng cấp được"):
        mod.preview_upgrade_to_team({"task_id": "live-3"})


def test_the_new_task_id_is_reported_back_to_the_caller(monkeypatch):
    """`preview_assign_team_task` ghi mã việc mới vào dict CỤC BỘ của lệnh này, nên
    lệnh phải chép nó ra `slots`. Không có bước chép, người gọi đọc lại `task_id` chỉ
    thấy mã CŨ và tưởng nâng cấp trượt — đúng cái mà đường autopilot đọc."""
    _wire(monkeypatch)
    _seed_sprint("dead-15")

    slots = {"task_id": "dead-15"}
    mod.run_upgrade_to_team(slots)

    assert slots["new_task_id"] and slots["new_task_id"] != "dead-15"
    store = _store()
    try:
        assert store.get(slots["new_task_id"]) is not None
    finally:
        store.close()


# --- đuôi cảnh báo: tự nâng hay mời CEO bấm -------------------------------------------


def _tail(task_id):
    from my_crew.runtime.team_tick_collaborators import _sprint_upgrade_tail

    store = _store()
    try:
        task = store.get(task_id)
    finally:
        store.close()
    return _sprint_upgrade_tail(task)


def _set_autopilot(monkeypatch, on):
    import my_crew.agent.ops_autopilot as ap

    monkeypatch.setattr(ap, "autopilot_enabled", lambda: on)


def test_autopilot_off_invites_the_ceo_to_press_the_button(monkeypatch):
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, False)
    _seed_sprint("tail-1")

    assert "upgrade_to_team tail-1" in _tail("tail-1")


def test_autopilot_on_upgrades_by_itself_and_names_the_new_task(monkeypatch):
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, True)
    _seed_sprint("tail-2")

    text = _tail("tail-2")

    store = _store()
    try:
        new_id = [t.id for t in store.list_recent_tasks(include_planning=True)
                  if t.id != "tail-2"][0]
    finally:
        store.close()
    assert new_id in text
    assert "upgrade_to_team tail-2" not in text  # đã làm rồi, không mời bấm nữa


def test_autopilot_records_the_decision_it_made(monkeypatch):
    """Autopilot quyết thay CEO thì phải để lại dấu vết CEO đọc được sau."""
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, True)
    _seed_sprint("tail-3")

    import my_crew.agent.ops_autopilot as ap

    seen: list[dict] = []
    monkeypatch.setattr(ap, "record_autopilot_decision", lambda **kw: seen.append(kw))

    _tail("tail-3")

    assert seen and seen[0]["decision"] == "upgrade_to_team"
    assert seen[0]["task_id"] == "tail-3"


def test_a_task_the_ceo_reserved_is_never_auto_upgraded(monkeypatch):
    """`require_ceo_approval` là CEO nói thẳng 'việc này tôi tự quyết' — autopilot
    không được đè lên."""
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, True)
    _seed_sprint("tail-4")
    store = _store()
    try:
        task = store.get("tail-4")
    finally:
        store.close()
    from my_crew.runtime.team_tick_collaborators import _sprint_upgrade_tail

    reserved = SimpleNamespace(id=task.id, title=task.title, require_ceo_approval=True)
    assert "upgrade_to_team tail-4" in _sprint_upgrade_tail(reserved)


def test_a_broken_upgrade_still_leaves_the_ceo_one_usable_fix(monkeypatch):
    """Cảnh báo phải tới CEO kèm MỘT cách chữa dùng được — nâng cấp hỏng thì hạ xuống
    lời mời thủ công, không bao giờ nổ giữa đường."""
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, True)
    _seed_sprint("tail-5")

    import my_crew.agent.ops_upgrade_to_team as up

    def _boom(_slots):
        raise RuntimeError("giả lập decompose hỏng")

    monkeypatch.setattr(up, "run_upgrade_to_team", _boom)

    assert "upgrade_to_team tail-5" in _tail("tail-5")


def test_autopilot_upgrades_a_chain_exactly_once(monkeypatch):
    """Mắt thứ hai bị chính `upgrade_to_team` từ chối, nên đuôi rơi về lời mời thủ công
    thay vì đẻ ra một chuỗi nâng→chết→nâng không đáy."""
    _wire(monkeypatch)
    _set_autopilot(monkeypatch, True)
    _seed_sprint("tail-6")
    _tail("tail-6")

    store = _store()
    try:
        new_id = [t.id for t in store.list_recent_tasks(include_planning=True)
                  if t.id != "tail-6"][0]
        store.set_plan(new_id, [{"step_id": "sprint", "title": "t",
                                 "assigned_to": "content", "deps": [],
                                 "step_type": "sprint"}], "hash-2")
        store.set_task_status(new_id, "stalled")
    finally:
        store.close()

    second = _tail(new_id)

    assert f"upgrade_to_team {new_id}" in second  # mời CEO, không tự nâng tiếp
    store = _store()
    try:
        # chỉ đúng 2 việc: gốc + một lần nâng
        assert len(store.list_recent_tasks(include_planning=True)) == 2
    finally:
        store.close()


# --- khối context không được rò ra ngoài phạm vi của nó -------------------------------
#
# Hai lỗi dưới đây cùng một gốc: khối context đi nhờ trường `brief`, mà mọi tầng phía
# sau coi `brief` là LỜI CEO tự viết — cắt 120 ký tự làm tiêu đề, cắt 2000 ký tự nhét
# vào prompt của mọi bước. Đề bài dùng ở đây LÀNH (không chứa cụm chèn lệnh): một chuỗi
# thù địch sẽ bị L2 cách ly thành placeholder ngắn, và chính cái ngắn đó giấu mất lỗi.


def _benign_draft(n: int) -> str:
    """Bản nháp dài, lành, không lặp một cụm nào đủ để bị L2 bắt."""
    return " ".join(f"đoạn {i} nói về giá thuê máy chủ theo tháng." for i in range(n))


def test_the_title_never_reaches_into_the_context_block(monkeypatch):
    """Tiêu đề task đi thẳng vào tin nhắn gửi CEO (`milestone_mirror_runner` nội suy
    nguyên văn). Đề gốc ngắn hơn 120 ký tự thì cửa sổ tiêu đề thò sang phần sau — tức
    là chữ do LLM viết ra tới thẳng CEO mà không qua lớp bọc nào."""
    _wire(monkeypatch)
    original = "so sánh giá 3 dịch vụ"  # ngắn hơn 120 ký tự — đó là điều kiện gây lỗi
    task = _seed_sprint("dead-40", brief=original)
    _write_artifact(task, {"result_text": _benign_draft(60)})

    slots = {"task_id": "dead-40"}
    mod.run_upgrade_to_team(slots)

    store = _store()
    try:
        title = store.get(slots["new_task_id"]).title
    finally:
        store.close()
    assert title == original
    assert "Bối cảnh" not in title
    assert "===" not in title


def test_every_step_prompt_gets_a_context_block_that_closes(monkeypatch):
    """`_read_handoff` cắt `original_request` ở 2000 ký tự và nhét vào prompt của MỌI
    bước. Đề mang khối đã bọc thì lát thẳng rơi vào giữa khối, để lại dấu mở lơ lửng —
    phần prompt còn lại nằm trong một khối không bao giờ đóng."""
    from my_crew.agent.team_task_graph import _team_task_db_path  # noqa: F401
    from my_crew.tools.search_result_formatter import _DELIM_END, _DELIM_START

    _wire(monkeypatch)
    task = _seed_sprint("dead-41", brief="so sánh giá 3 dịch vụ lưu trữ")
    _write_artifact(task, {"result_text": _benign_draft(60)})

    slots = {"task_id": "dead-41"}
    mod.run_upgrade_to_team(slots)

    store = _store()
    try:
        brief = store.get(slots["new_task_id"]).original_request
    finally:
        store.close()
    # Điều kiện gây lỗi phải thật sự có mặt: đề dài hơn cửa sổ cắt phía dưới.
    assert len(brief) > 2000, "đề phải vượt 2000 ký tự thì test này mới bắt được lỗi"

    from my_crew.tools.search_result_formatter import truncate_preserving_delimiters

    head = truncate_preserving_delimiters(brief, 2000)
    assert head.count(_DELIM_START) == head.count(_DELIM_END)


def test_truncation_drops_a_block_it_cannot_close():
    """Lùi về trước dấu mở chứ không cố giữ phần thân: thà mất cả khối còn hơn giữ một
    khối hở."""
    from my_crew.tools.search_result_formatter import (
        _DELIM_END,
        _DELIM_START,
        format_internal_content,
        truncate_preserving_delimiters,
    )

    text = "đề gốc\n\n" + format_internal_content("x" * 500, label="nháp")
    cut = truncate_preserving_delimiters(text, 100)

    assert cut == "đề gốc"
    assert _DELIM_START not in cut and _DELIM_END not in cut


def test_truncation_keeps_a_block_that_fits():
    """Khối đóng trọn vẹn trong lát thì giữ nguyên — không cắt thừa."""
    from my_crew.tools.search_result_formatter import (
        format_internal_content,
        truncate_preserving_delimiters,
    )

    block = format_internal_content("ngắn", label="nháp")
    text = block + "\n" + "z" * 500
    cut = truncate_preserving_delimiters(text, len(block) + 10)

    assert cut.startswith(block)


def test_truncation_leaves_plain_prose_alone():
    """Không có khối nào thì hành vi phải trùng khít lát thẳng — đây là đường mà gần như
    mọi đề CEO tự gõ đi qua."""
    from my_crew.tools.search_result_formatter import truncate_preserving_delimiters

    prose = "a" * 3000
    assert truncate_preserving_delimiters(prose, 2000) == prose[:2000]
    assert truncate_preserving_delimiters("ngắn", 2000) == "ngắn"


def test_a_route_that_says_upgraded_blocks_even_a_plan_that_says_otherwise():
    """Lớp chặn thứ hai, thử riêng: `_upgradable` đọc KẾ HOẠCH, `_already_upgraded` đọc
    LỊCH SỬ. Chuỗi thông thường chỉ chạm lớp đầu, nên lớp sau không có test riêng thì
    xoá đi cũng không ai biết — kể cả nhánh `previous_task`, thứ duy nhất bắt được một
    task đã nâng mà route lại không mang `source="upgrade"`.
    """
    cases = {
        "mixed-1": {"mode": "team", "source": "upgrade"},
        "mixed-2": {"mode": "team", "source": "heuristic", "previous_task": "cũ-1"},
        "mixed-3": {"mode": "team", "source": "heuristic",
                    "previous": {"source": "upgrade"}},
    }
    for task_id, route in cases.items():
        # Kế hoạch VẪN còn bước sprint ⇒ `_upgradable` cho qua, chỉ route chặn được.
        _seed_sprint(task_id, route=route)
        # `_load_upgradable` chứ không phải `run_upgrade_to_team`: gọi thẳng cửa kiểm
        # tra thì một hàng rào thủng làm test TRƯỢT ngay, thay vì rơi xuống một lần
        # nâng cấp thật rồi treo ở tầng model.
        with pytest.raises(ValueError, match="vốn đã là bản nâng cấp"):
            mod._load_upgradable(task_id)


def test_a_stray_marker_at_the_very_start_costs_the_marker_not_the_brief():
    """Bỏ cả khối hở là đúng, TRỪ khi khối hở nằm ngay đầu — lúc đó "bỏ cả khối" thành
    xoá sạch đề của CEO. Mà một dấu `===SEARCH_RESULT===` do CEO tự gõ luôn là dấu hở,
    nên đây không phải trường hợp hiếm như vẻ ngoài của nó."""
    from my_crew.tools.search_result_formatter import (
        _DELIM_END,
        _DELIM_START,
        truncate_preserving_delimiters,
    )

    brief = f"{_DELIM_START}\n" + "nội dung đề bài rất dài. " * 300
    cut = truncate_preserving_delimiters(brief, 2000)

    assert "nội dung đề bài" in cut, "đề bài không được biến mất"
    # Dấu vẫn phải mất hiệu lực cấu trúc, chỉ là không kéo theo cả đề bài.
    assert _DELIM_START not in cut and _DELIM_END not in cut
