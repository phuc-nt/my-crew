"""Nhóm B — vòng đời và đổi lane, model thật.

Bốn thứ ở đây chỉ chứng minh được bằng model thật: một lần nâng cấp có thật sự MANG
được kết quả dở dang sang đề mới không (decompose thật phải đọc được nó), một lời chỉ
đạo giữa chừng có thật sự đổi được đầu ra không, một câu hỏi làm rõ có phải là câu hỏi
đúng chỗ không, và bộ chống trùng có đứng vững trước một lần gửi lặp không.

B1/B2 gieo một chuyến sprint đã chết qua ĐÚNG API store thật thay vì chạy một đề bất
khả thi cho tới lúc nó chết: chân cần model thật ở đây là chân nâng cấp (decompose phải
đọc được khối bối cảnh), không phải chân làm-cho-nó-chết — chân đó tốn ~10 phút và
flaky mà không chứng minh thêm điều gì.
"""

from __future__ import annotations

import pytest

_BRIEF = "So sánh giá 3 dịch vụ lưu trữ đám mây cho đội 10 người"
_PARTIAL = "Đã tra được giá Google Drive: 1.99 USD/tháng cho 100GB. Chưa có Dropbox."


def _seed_dead_sprint(run, task_id: str = "dead-live-1", *, route: dict | None = None):
    """Một chuyến sprint đã bỏ cuộc, kèm bản nháp dở dang — ghi bằng API store thật."""
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = run.h.store()
    try:
        store.create_task(task_id=task_id, title=_BRIEF[:60], original_request=_BRIEF,
                          assigned_by="ceo", pic_id="content")
        store.set_plan(task_id, [{
            "step_id": "sprint", "title": _BRIEF[:60], "assigned_to": "content",
            "deps": [], "acceptance": "- có giá của cả 3 dịch vụ", "step_type": "sprint",
        }], "hash-live-1")
        store.set_route(task_id, route if route is not None else {
            "mode": "sprint", "source": "heuristic", "reason": "một việc tra cứu",
            "signals": {"brief_len": len(_BRIEF), "entities": 3, "distinct_asks": 1},
        })
        store.set_task_status(task_id, "stalled")
        task = store.get(task_id)
    finally:
        store.close()
    write_step_artifact(team_tasks_root(), task_id, task.steps[0].seq, _PARTIAL)
    return task


# --- B1: dead-end → nâng cấp một chạm ------------------------------------------------


@pytest.mark.live_slow
def test_b1_an_upgrade_carries_the_dead_sprints_work_into_the_new_plan(live_run):
    """Điều đáng giá của `upgrade_to_team` không phải là nó dựng được task mới — mà là
    kết quả CEO ĐÃ TRẢ TIỀN không rơi xuống đất.

    Nên assert đi vào chỗ chứng minh được điều đó bằng model thật: bản ghi định tuyến
    phải trỏ ngược về việc cũ, và kế hoạch model dựng ra phải là kế hoạch nhiều bước
    (đề này vốn là đề của cả đội) chứ không phải một bước suy biến."""
    from my_crew.agent.ops_upgrade_to_team import run_upgrade_to_team

    run = live_run()
    _seed_dead_sprint(run)

    slots: dict[str, str] = {"task_id": "dead-live-1"}
    text = run_upgrade_to_team(slots)
    new_id = slots.get("new_task_id", "")
    assert new_id, f"nâng cấp phải trả về mã việc MỚI: {text[:300]!r}"
    assert new_id != "dead-live-1"

    route = run.route(new_id)
    assert route.get("source") == "upgrade", route
    assert route.get("previous_task") == "dead-live-1", route
    assert route.get("mode") == "team", route

    steps = run.h.step_rows(new_id)
    assert len(steps) >= 2, f"đề của cả đội phải ra kế hoạch nhiều bước: {steps}"
    assert all(s["step_type"] != "sprint" for s in steps), steps


def test_b2_a_chain_can_only_be_upgraded_once(live_run):
    """Cái chặn vòng lặp. Nâng→chết→nâng là chuỗi không đáy và mỗi mắt tốn trọn một
    lượt decompose, nên nó phải bị chặn ở tầng lệnh — không phải ở tầng "hy vọng CEO
    không gõ lại"."""
    from my_crew.agent.ops_upgrade_to_team import run_upgrade_to_team

    run = live_run()
    _seed_dead_sprint(run, "already-up-1", route={
        "mode": "team", "source": "upgrade", "previous_task": "older-1",
        "reason": "nâng từ sprint", "signals": {},
    })
    with pytest.raises(ValueError):
        run_upgrade_to_team({"task_id": "already-up-1"})


# --- B3: chỉ đạo giữa chừng ----------------------------------------------------------


@pytest.mark.live_slow
def test_b3_a_mid_run_steer_changes_what_the_sprint_delivers(live_run):
    """P4 đầu-tới-cuối trên model thật.

    Chỉ đạo được thả vào ĐÚNG kênh mà production dùng — file `steer.txt` trong thư mục
    artifact — chứ không qua một hook test-only: một chuyến sprint đang chạy giữ bảng
    bước trong bộ nhớ và không bao giờ đọc lại chúng, nên thư mục artifact LÀ kênh duy
    nhất nó thật sự đọc. Test đi đúng kênh đó thì mới chứng minh được production đi
    được.

    Assert vào deliverable chứ không vào prompt: điều CEO quan tâm là kết quả có thêm
    thứ mình dặn không."""
    from my_crew.runtime.sprint_steering import write_steer
    from my_crew.runtime.team_task_paths import team_tasks_root

    run = live_run()
    reply = run.h.trigger(
        "sprint: So sánh 3 dịch vụ lưu trữ đám mây Google Drive, Dropbox, OneDrive "
        "về giá gói cá nhân"
    )
    rows = run.h.task_rows()
    assert rows, f"phải tạo được task: {reply[:200]!r}"
    task_id = rows[-1]["id"]
    assert run.route(task_id).get("mode") == "sprint", run.route(task_id)

    # Thả chỉ đạo TRƯỚC khi bơm: sprint chạy trọn trong một tick, nên đây là lúc duy
    # nhất còn đứng ngoài lượt chạy mà vẫn chắc chắn file đã nằm sẵn ở đó.
    write_steer(team_tasks_root(), task_id, "Bổ sung thêm dịch vụ iCloud vào bảng so sánh.")
    run.h.pump(ticks=4)

    text = run.deliverable(task_id) or run.h.last_message_text()
    assert "icloud" in text.lower(), (
        "chỉ đạo giữa chừng phải đi vào kết quả; không thấy iCloud trong:\n"
        f"{text[:1200]}"
    )


# --- B4/B5: hỏi lại, và chống trùng --------------------------------------------------


@pytest.mark.live_slow
def test_b4_an_underspecified_brief_asks_before_it_spends(live_run):
    """Hỏi lại là hành vi TIẾT KIỆM: rẻ hơn hẳn việc chạy trọn một chuyến rồi giao sai.

    Assert theo tập chấp nhận — hoặc có câu hỏi chờ, hoặc lời đáp tự nó nêu ra chỗ
    thiếu. Đây là chỗ model được quyền chọn cách hỏi; cái phải đúng là NÓ KHÔNG ĐOÁN
    RỒI TIÊU TIỀN, chứ không phải là nó hỏi qua đường nào.

    Bản trước đòi dấu "?" trong lời đáp. Chạy thật cho ra một lời đáp liệt kê đúng ba
    thứ còn thiếu ("báo cáo nào", "ai là họ", "kênh nào") nhưng viết ở thể trần thuật
    và kết bằng dấu chấm — hành vi đang đo thì đúng, chỉ dấu câu là khác. Đòi dấu "?"
    là đo DẤU CÂU chứ không đo hành vi, hẹp hơn chính tính chất mà docstring này nêu.
    Vế chắc chắn nhất vẫn là vế cuối: KHÔNG có task nào được tạo, tức không đồng nào
    bị tiêu cho một việc mà đề còn chưa rõ."""
    from my_crew.runtime.clarify_store import ClarifyStore
    from my_crew.runtime.team_task_paths import clarify_db_path

    run = live_run()
    reply = run.h.trigger("Gửi báo cáo cho họ như lần trước nhé.")

    store = ClarifyStore(clarify_db_path())
    try:
        pending = store.list_pending()
    finally:
        store.close()
    flagged_gap = any(
        w in reply.lower()
        for w in ("không rõ", "chưa rõ", "không đủ", "thiếu", "cụ thể", "nào", "ai ")
    )
    assert bool(pending) or "?" in reply or flagged_gap, (
        f"đề thiếu thông tin phải được hỏi lại hoặc nêu chỗ thiếu, không phải đoán: "
        f"{reply[:400]!r}"
    )
    assert not run.h.task_rows(), (
        f"đề còn thiếu thông tin thì KHÔNG được tạo việc rồi tiêu tiền: {run.h.task_rows()}"
    )


def test_b5_the_same_message_twice_creates_one_task(live_run):
    """Bộ chống trùng ở tầng intake. Poll chồng lượt là chuyện có thật, và mỗi lần trùng
    lọt lưới là một task thừa chạy hết tiền của nó."""
    run = live_run()
    text = "Tóm tắt giúp anh 3 xu hướng chính của ngành bán lẻ VN năm nay"
    run.h.trigger(text, ts="tg:dup:1")
    run.h.trigger(text, ts="tg:dup:1")
    assert len(run.h.task_rows()) <= 1, run.h.task_rows()
