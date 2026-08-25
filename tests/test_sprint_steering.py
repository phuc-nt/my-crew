"""v93 P4 — chỉ đạo giữa chừng cho chuyến sprint đang chạy.

Bốn nhóm, theo đúng bốn thứ có thể hỏng:
  1. file chỉ đạo: ghi/đọc/xoá, đọc đúng một lần, lời mới đè lời cũ, rác không nổ.
  2. runner: chỉ đạo tới được model, ở đúng ranh giới stage, và KHÔNG bị nuốt khi bản
     nháp đã kín dữ liệu (ca dễ mất nhất — đã đọc là đã xoá).
  3. ops: rẽ nhánh theo trạng thái task, và luồng amend cũ không đổi hành vi.
  4. best-effort: mọi hỏng hóc để chuyến sprint chạy tiếp, không làm hỏng việc.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_adjust_team_task as ops_mod
import my_crew.runtime.sprint_runner as runner_mod
from my_crew.runtime.sprint_steering import (
    MAX_STEER_CHARS,
    STEER_LABEL,
    merge_steer,
    steer_path,
    take_steer,
    write_steer,
)

_TASK = "task-abc123"


@pytest.fixture(autouse=True)
def _isolated_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


# --- 1. file chỉ đạo ------------------------------------------------------------------


def test_a_steer_is_read_back_verbatim(tmp_path):
    write_steer(tmp_path, _TASK, "bỏ phần dự báo, chỉ giữ số liệu quý này")
    assert take_steer(tmp_path, _TASK) == "bỏ phần dự báo, chỉ giữ số liệu quý này"


def test_reading_a_steer_consumes_it(tmp_path):
    """Đọc-rồi-xoá: mỗi lời dặn áp đúng MỘT lần. Không xoá thì mọi ranh giới còn lại
    của chuyến sprint đều dán lại cùng một lời, model đọc n lần một câu."""
    write_steer(tmp_path, _TASK, "thêm phần rủi ro")
    assert take_steer(tmp_path, _TASK) == "thêm phần rủi ro"
    assert take_steer(tmp_path, _TASK) == ""
    assert not steer_path(tmp_path, _TASK).exists()


def test_nothing_to_read_is_not_an_error(tmp_path):
    assert take_steer(tmp_path, _TASK) == ""


def test_a_second_steer_replaces_the_first(tmp_path):
    """CEO gõ lại lần hai là ĐỔI Ý, không phải muốn cộng dồn hai lời — giữ cả hai sẽ
    đưa vào prompt một cặp yêu cầu có thể mâu thuẫn nhau."""
    write_steer(tmp_path, _TASK, "lời cũ")
    write_steer(tmp_path, _TASK, "lời mới")
    assert take_steer(tmp_path, _TASK) == "lời mới"


def test_an_empty_steer_is_refused_at_the_door(tmp_path):
    with pytest.raises(ValueError):
        write_steer(tmp_path, _TASK, "   ")


def test_a_steer_is_capped(tmp_path):
    """Chỉ đạo đi vào prompt của vòng sửa cùng bản nháp: dán nhầm cả bản báo cáo vào
    đây sẽ đẩy chính bản nháp đang sửa ra khỏi cửa sổ ngữ cảnh."""
    write_steer(tmp_path, _TASK, "x" * (MAX_STEER_CHARS * 3))
    assert len(take_steer(tmp_path, _TASK)) == MAX_STEER_CHARS


def test_a_task_id_that_escapes_the_root_is_refused(tmp_path):
    with pytest.raises(ValueError):
        write_steer(tmp_path, "../../etc", "thoát ra ngoài")


def test_undecodable_bytes_do_not_raise(tmp_path):
    """Best-effort: file rác đọc ra được gì dùng nấy, không bao giờ ném vào chuyến chạy."""
    path = steer_path(tmp_path, _TASK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not-utf8")
    take_steer(tmp_path, _TASK)  # không được ném
    assert not path.exists(), "file không dùng được vẫn phải bị dọn"


def test_a_broken_read_is_swallowed_and_logged(monkeypatch, tmp_path, caplog):
    write_steer(tmp_path, _TASK, "lời dặn")
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("đĩa hỏng")),
    )
    assert take_steer(tmp_path, _TASK) == ""


def test_merge_labels_the_steer_as_the_ceos_own_words():
    """Nhãn nói hai điều model cần biết: đây là lời CEO (cùng cấp đề bài, không phải
    dữ liệu tra cứu), và nó tới SAU nên thắng đề ban đầu khi mâu thuẫn."""
    merged = merge_steer("- tiêu chí cũ", "đổi sang bảng")
    assert STEER_LABEL in merged
    assert "- tiêu chí cũ" in merged
    assert "đổi sang bảng" in merged


def test_merge_without_a_steer_changes_nothing():
    assert merge_steer("- tiêu chí cũ", "") == "- tiêu chí cũ"


# --- 2. runner đọc tại ranh giới stage -------------------------------------------------


class _RecordingLlm:
    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, messages, **_kw):
        self.prompts.append("\n".join(str(m.get("content", "")) for m in messages))
        reply = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(content=reply, cost_usd=0.0)


@pytest.fixture
def llm(monkeypatch):
    def _install(replies: list[str]) -> _RecordingLlm:
        fake = _RecordingLlm(replies)
        monkeypatch.setattr(runner_mod, "LlmClient", lambda _s: fake, raising=False)
        import my_crew.llm.client as client_mod

        monkeypatch.setattr(client_mod, "LlmClient", lambda _s: fake)
        return fake

    return _install


def _run(*, goal: str, task_id: str = _TASK, replies: list[str], acceptance: str = "- có số liệu",
         on_prefetch=None):
    rounds = {"n": 0}

    def _prefetch(_loaded, _settings, queries):
        rounds["n"] += 1
        if on_prefetch is not None:
            on_prefetch(rounds["n"])
        return "\n".join(f"- kết quả cho {q}" for q in queries)

    work = runner_mod.build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance=acceptance,
        prefetch=_prefetch,
        task_id=task_id,
    )
    return work(goal, "", None)


_GAPPY_GOAL = "So sánh 3 sàn: Shopee, Lazada và Tiki"


def test_a_steer_reaches_the_revise_round(llm, tmp_path):
    """Cốt lõi của cả phase: lời dặn phải tới được MODEL. Chỉ cộng vào acceptance là
    chưa đủ — prompt nháp đã dựng xong từ trước và không dựng lại."""
    fake = llm(["nháp thiếu dữ liệu", "bản sửa theo chỉ đạo"])
    write_steer(tmp_path, _TASK, "chỉ giữ 2 sàn đầu")
    _run(goal=_GAPPY_GOAL, replies=[])
    assert any("chỉ giữ 2 sàn đầu" in p for p in fake.prompts), (
        "chỉ đạo phải nằm trong prompt của một lượt gọi model"
    )
    assert any(STEER_LABEL in p for p in fake.prompts)


def test_the_steer_file_is_consumed_by_the_run(llm, tmp_path):
    llm(["nháp thiếu dữ liệu", "bản sửa"])
    write_steer(tmp_path, _TASK, "đổi sang bảng")
    _run(goal=_GAPPY_GOAL, replies=[])
    assert not steer_path(tmp_path, _TASK).exists()


def test_a_clean_draft_still_gets_the_steer(llm, tmp_path):
    """Ca dễ mất nhất. Bản nháp không còn khoảng trống ⇒ vòng soát thoát ngay ở
    `not gaps` và không còn lượt sửa nào — nhưng chỉ đạo thì ĐÃ đọc, tức đã xoá. Bỏ
    qua ở đây là nuốt mất lời CEO sau khi vừa hứa "áp từ vòng kế"."""
    fake = llm(["bản nháp đã đủ", "bản nháp đã chỉnh theo chỉ đạo"])
    write_steer(tmp_path, _TASK, "viết ngắn lại còn một đoạn")
    text, _cost = _run(goal="viết đoạn giới thiệu ngắn", replies=[], acceptance="")
    assert any("viết ngắn lại còn một đoạn" in p for p in fake.prompts), (
        "bản nháp kín dữ liệu vẫn phải có một lượt sửa riêng cho chỉ đạo"
    )
    assert "bản nháp đã chỉnh theo chỉ đạo" in text


def test_a_clean_draft_without_a_steer_costs_no_extra_call(llm):
    """Mặt kia của test trên: không có chỉ đạo thì KHÔNG được sinh thêm lượt gọi nào.
    Tính năng này phải vô hình với mọi chuyến sprint không ai dặn gì."""
    fake = llm(["bản nháp đã đủ", "KHÔNG ĐƯỢC GỌI"])
    _run(goal="viết đoạn giới thiệu ngắn", replies=[], acceptance="")
    assert len(fake.prompts) == 1


def test_a_run_without_a_task_id_never_looks_for_a_steer(llm, tmp_path):
    """Benchmark/replay gọi thẳng pipeline, không có task thật. Không có id thì không
    có file để đọc, và tuyệt đối không được đọc nhầm file của task khác."""
    fake = llm(["nháp thiếu dữ liệu", "bản sửa"])
    write_steer(tmp_path, _TASK, "lời dặn của task khác")
    _run(goal=_GAPPY_GOAL, task_id="", replies=[])
    assert not any("lời dặn của task khác" in p for p in fake.prompts)
    assert steer_path(tmp_path, _TASK).exists(), "chỉ đạo của task khác phải còn nguyên"


def test_a_steer_landing_inside_a_round_rides_that_same_round(llm, tmp_path):
    """Ranh giới 2, và lý do nó phải đọc TRƯỚC khi dựng `messages`.

    Chỉ đạo tới sau ranh giới 1 (bản nháp đã xong, vòng sửa đã bắt đầu tìm thêm dữ
    liệu) vẫn còn kịp đi cùng chính vòng đó. Đọc sau khi dựng messages thì lời dặn
    phải chờ vòng SAU — mà vòng này thường là vòng cuối (doom-guard dừng ngay khi một
    vòng không lấp được khoảng trống nào), và chỉ đạo đã đọc là đã xoá: hoãn một vòng
    trong ca đó là mất hẳn lời CEO."""
    fake = llm(["nháp thiếu dữ liệu", "bản sửa"])

    def _on_prefetch(round_index: int) -> None:
        if round_index == 2:  # lượt tìm bổ sung của vòng sửa 1, sau ranh giới 1
            write_steer(tmp_path, _TASK, "dặn ngay trong vòng này")

    _run(goal=_GAPPY_GOAL, replies=[], on_prefetch=_on_prefetch)
    assert any("dặn ngay trong vòng này" in p for p in fake.prompts), (
        "chỉ đạo tới giữa một vòng sửa phải đi cùng chính vòng đó, không hoãn sang vòng sau"
    )


def test_a_steer_never_repeats_across_rounds(llm, tmp_path):
    """Vòng trước đã mang lời đi rồi; gửi lại là bắt model đọc hai lần một lời và làm
    prompt phình theo số vòng."""
    fake = llm(["nháp trống", "vẫn trống", "bản cuối"])
    write_steer(tmp_path, _TASK, "một lời duy nhất")
    _run(goal=_GAPPY_GOAL, replies=[])
    hits = sum(p.count("một lời duy nhất") for p in fake.prompts)
    assert hits <= len(fake.prompts), "mỗi prompt tích luỹ, nhưng không được dán lại lời cũ"
    last = fake.prompts[-1]
    assert last.count("một lời duy nhất") <= 1


def test_an_unreadable_steer_does_not_break_the_run(llm, tmp_path, monkeypatch):
    """Best-effort đầu runner: mất một lời dặn thì tiếc, hỏng cả việc thì tệ hơn nhiều."""
    fake = llm(["nháp thiếu dữ liệu", "bản sửa"])
    write_steer(tmp_path, _TASK, "lời dặn")
    monkeypatch.setattr(
        "my_crew.runtime.sprint_steering.take_steer",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("đĩa hỏng")),
    )
    text, _cost = _run(goal=_GAPPY_GOAL, replies=[])
    assert text.strip(), "chuyến sprint vẫn phải giao được kết quả"
    assert fake.prompts


# --- 3. ops rẽ nhánh -------------------------------------------------------------------


def _task(status: str, steps: list) -> SimpleNamespace:
    return SimpleNamespace(id=_TASK, status=status, steps=steps)


def _step(status: str, step_type: str = "work") -> SimpleNamespace:
    return SimpleNamespace(status=status, step_type=step_type, step_id="s1", title="t",
                           assigned_to="agent-a")


def test_a_running_sprint_takes_the_steer_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_mod, "append_office_event", lambda *_a, **_kw: None,
                        raising=False)
    monkeypatch.setattr("my_crew.runtime.office_room_append.append_office_event",
                        lambda *_a, **_kw: None)
    reply = ops_mod._steer_running_sprint(
        _task("running", [_step("running", "sprint")]), _TASK, "bỏ phần dự báo")
    assert reply is not None
    assert "vòng kế" in reply
    assert take_steer(tmp_path, _TASK) == "bỏ phần dự báo"


def test_a_normal_team_task_is_left_to_the_amend_flow():
    """None = "không phải ca của tôi". Amend đổi được KẾ HOẠCH, mạnh hơn hẳn một lời
    dặn — task đội còn bước chờ thì đừng cướp ca của nó."""
    assert ops_mod._steer_running_sprint(
        _task("running", [_step("running", "work"), _step("pending", "work")]),
        _TASK, "chỉnh") is None


def test_a_task_without_a_status_field_falls_through_to_amend():
    """Nhánh chỉ đạo chỉ ĐỨNG SANG BÊN cho luồng amend cũ — nó không được nổ trên một
    hình dạng task mà luồng kia vốn xử lý được. Đọc thẳng `task.status` từng làm hỏng
    hai test amend có sẵn: task ở đó dựng không có trường `status`."""
    bare = SimpleNamespace(id=_TASK, steps=[_step("running", "sprint")])
    assert ops_mod._steer_running_sprint(bare, _TASK, "chỉnh") is None
    assert ops_mod._steer_running_sprint(
        SimpleNamespace(id=_TASK, status="running"), _TASK, "chỉnh") is None


def test_a_finished_sprint_is_not_steerable():
    assert ops_mod._steer_running_sprint(
        _task("done", [_step("done", "sprint")]), _TASK, "chỉnh") is None


def test_a_sprint_not_yet_started_is_not_steerable():
    """Bước còn `pending` nghĩa là chưa có vòng nào chạy — đường đúng là amend/giao lại,
    không phải nhét một lời dặn vào chỗ chưa ai đọc."""
    assert ops_mod._steer_running_sprint(
        _task("running", [_step("pending", "sprint")]), _TASK, "chỉnh") is None
