"""Per-dep handoff cap: a fan-in step's prompt stays bounded as the fanout widens.

A gather step's deps are its N sub-steps, so the uncapped join grew with both the fanout
width and the widest branch — the parent paid for every sub's full text while being asked
to synthesize, not to re-read.

The cap is opt-in per caller, and that is the load-bearing part: the same reader also
feeds the replay work-order and the reviewer's context, neither of which is a prompt.
Those must keep seeing the full text, so the tests below pin the default OFF as firmly as
they pin the capped path.
"""

from __future__ import annotations

from my_crew.agent.team_task_artifact import write_step_artifact
from my_crew.agent.team_task_graph import HANDOFF_DEP_CHAR_CAP, _read_deps_handoff
from my_crew.runtime.team_task_store import TeamTaskStore


def _seed_store(tmp_path, steps: list[dict]) -> None:
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="task-1", title="t", original_request="r", assigned_by="ceo")
    store.set_plan("task-1", steps, plan_hash="irrelevant-for-this-test")
    store.close()


def _seed_one_dep(tmp_path, text: str) -> None:
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "sub 1", "assigned_to": "agent-a", "deps": []},
        {"step_id": "gather", "title": "tổng hợp", "assigned_to": "agent-b", "deps": ["a"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": text})


def test_a_result_under_the_cap_is_passed_through_verbatim(tmp_path):
    text = "x" * (HANDOFF_DEP_CHAR_CAP - 1)
    _seed_one_dep(tmp_path, text)

    assert _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True) == text


def test_a_result_exactly_at_the_cap_is_not_truncated(tmp_path):
    text = "x" * HANDOFF_DEP_CHAR_CAP
    _seed_one_dep(tmp_path, text)

    assert _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True) == text


def test_an_oversized_result_is_cut_and_points_at_the_full_artifact(tmp_path):
    text = "y" * (HANDOFF_DEP_CHAR_CAP + 500)
    _seed_one_dep(tmp_path, text)

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True)

    assert len(handoff) < len(text)
    assert handoff.startswith("y" * 100)
    assert "đã cắt 500 ký tự" in handoff
    # The pointer has to name a file that actually exists, or it is worse than no pointer.
    assert "step-1.json" in handoff
    assert (tmp_path / "artifacts" / "team-tasks" / "task-1" / "step-1.json").exists()


def test_the_full_text_survives_untouched_in_the_artifact(tmp_path):
    """Cutting the PROMPT copy must never cut the stored one — the pointer would then
    lead to a truncated file and the detail would be gone for good."""
    from my_crew.agent.team_task_artifact import read_step_artifact

    text = "z" * (HANDOFF_DEP_CHAR_CAP + 1000)
    _seed_one_dep(tmp_path, text)
    _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True)

    stored = read_step_artifact(tmp_path, "task-1", 1)
    assert stored is not None
    assert stored["result_text"] == text


def test_the_cap_is_off_by_default(tmp_path):
    """The replay work-order and the reviewer context share this reader. A truncated
    work-order would no longer reproduce the run it records, and a reviewer shown cut
    evidence would fail a step for missing what it was never given."""
    text = "w" * (HANDOFF_DEP_CHAR_CAP + 500)
    _seed_one_dep(tmp_path, text)

    assert _read_deps_handoff(tmp_path, "task-1", ("a",)) == text


def test_each_dep_is_capped_independently_so_width_still_costs_something(tmp_path):
    """Per-dep, not per-join: one enormous sub must not starve its siblings out of the
    prompt entirely, which a single whole-handoff budget would do."""
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "sub 1", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b", "title": "sub 2", "assigned_to": "agent-b", "deps": []},
        {"step_id": "gather", "title": "tổng hợp", "assigned_to": "agent-c",
         "deps": ["a", "b"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1,
                        {"status": "done", "result_text": "a" * (HANDOFF_DEP_CHAR_CAP + 300)})
    write_step_artifact(tmp_path, "task-1", 2,
                        {"status": "done", "result_text": "KẾT QUẢ NHỎ CỦA SUB 2"})

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a", "b"), cap_dep_chars=True)

    assert "KẾT QUẢ NHỎ CỦA SUB 2" in handoff  # the small sibling survives intact
    assert "đã cắt 300 ký tự" in handoff
    assert "step-1.json" in handoff


def test_the_cut_never_leaves_an_unclosed_search_result_block(tmp_path):
    """A step's result_text can carry wrapped search blocks. A plain slice landing inside
    one leaves a dangling opener, and everything after it in the prompt is swallowed into
    a block that never closes — the exact failure the delimiter-aware truncator exists to
    prevent, so the cap must route through it rather than slicing.

    The block here straddles the cap boundary, so a naive `text[:cap]` really would land
    inside it. What survives must balance its delimiters."""
    prose = "phần mở đầu\n\n" + ("p" * (HANDOFF_DEP_CHAR_CAP - 500))
    text = prose + "\n===SEARCH_RESULT===\n" + ("q" * 4000) + "\n===END===\n"
    assert len(text) > HANDOFF_DEP_CHAR_CAP  # the cut has to actually fire
    _seed_one_dep(tmp_path, text)

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True)

    assert handoff.count("===SEARCH_RESULT===") == handoff.count("===END===")


def test_a_straddling_block_is_dropped_rather_than_left_hanging(tmp_path):
    """Same boundary as above, stated as the choice the truncator makes: losing the whole
    block beats keeping a half of it, because a hanging opener costs the rest of the
    prompt, not just the block."""
    prose = "phần mở đầu\n\n" + ("p" * (HANDOFF_DEP_CHAR_CAP - 500))
    text = prose + "\n===SEARCH_RESULT===\n" + ("q" * 4000) + "\n===END===\n"
    _seed_one_dep(tmp_path, text)

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a",), cap_dep_chars=True)

    assert "===SEARCH_RESULT===" not in handoff
    assert handoff.startswith("phần mở đầu")
    assert "đã cắt" in handoff  # still points at the artifact holding the whole block


def test_a_dep_that_is_one_unclosed_block_stays_within_a_bounded_overshoot(tmp_path):
    """Nhánh vô hiệu hoá dấu mở là đường về DUY NHẤT mà không test nào của file này đi qua.

    Hai case delimiter ở trên đều mở đầu bằng văn xuôi, nên `head` luôn khác rỗng và hàm
    thoát ở `return head`. Muốn chạm nhánh cuối thì dấu mở phải nằm ngay đầu — đúng tình
    huống CEO dán nguyên một khối vào đề. Lúc đó hàm KHÔNG cắt về đúng `limit`: nó thay dấu
    mở bằng chuỗi vô hiệu hoá DÀI HƠN, nên kết quả vượt trần.

    Đo được: vượt đúng 39 ký tự = len(vô hiệu hoá) - len(dấu mở), và chỉ vượt một lần.
    Nhiều dấu mở KHÔNG cộng dồn — có dấu mở thứ hai nghĩa là dấu trước nó hoặc đã đóng
    trong lát (thoát ở `return cut`) hoặc để lại `head` khác rỗng (thoát ở `return head`),
    cả hai đều ngắn hơn trần. Ghim mốc này để nó là hằng số có chủ ý: đổi chuỗi vô hiệu hoá
    dài thêm sẽ nới trần theo mà không ai hay.
    """
    from my_crew.tools.search_result_formatter import (
        _DELIM_START,
        truncate_preserving_delimiters,
    )
    # 39 viết thẳng, KHÔNG tính từ len(_NEUTRALIZED_DELIM). Tính lại từ chính hằng số đó
    # thì hai vế của assert cùng trôi theo nhau: nới chuỗi vô hiệu hoá dài thêm vẫn xanh,
    # và test mất đúng cái nó sinh ra để canh. Số này đo được, đổi nó phải là hành vi có
    # chủ ý — sửa số ở đây là chỗ ghi nhận chủ ý ấy.
    MEASURED_OVERSHOOT = 39

    blob = _DELIM_START + "\n" + ("q" * (HANDOFF_DEP_CHAR_CAP * 2))
    out = truncate_preserving_delimiters(blob, HANDOFF_DEP_CHAR_CAP)

    assert _DELIM_START not in out, "dấu mở hở lọt qua — đúng thứ hàm này tồn tại để chặn"
    assert len(out) == HANDOFF_DEP_CHAR_CAP + MEASURED_OVERSHOOT, (
        f"vượt trần {len(out) - HANDOFF_DEP_CHAR_CAP} ký tự, không phải "
        f"{MEASURED_OVERSHOOT} — hoặc chuỗi vô hiệu hoá đã đổi độ dài, hoặc phần vượt "
        "đã cộng dồn theo số dấu mở"
    )
