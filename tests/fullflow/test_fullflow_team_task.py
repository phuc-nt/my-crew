"""Full-flow scenarios: a real CEO chat message drives the ENTIRE pipeline.

Nothing here calls internal functions to move a task along — every advance is
either a chat trigger (the seam Telegram/Slack sit on) or a pump of the
daemon's own tick cadence. Assertions read what a real CEO observes: the
Telegram outbox and the task's terminal state.
"""

from __future__ import annotations

from . import scenario_rules as rules


def _dag_email_steps() -> list[dict]:
    """A 2-step DAG whose terminal step is an external write (sending an email
    leaves the company) — that defeats the small-task waiver, so the ticker
    MUST mint a peer review for the terminal step."""
    return [
        {"step_id": "draft", "title": "Soạn nháp email mời họp",
         "assigned_to": "secretary", "deps": [],
         "acceptance": "nêu đủ 3 mục: thời gian, địa điểm, agenda", "needs_review": False},
        {"step_id": "finalize", "title": "Chốt email mời họp",
         "assigned_to": "writer", "deps": ["draft"],
         "acceptance": "email hoàn chỉnh dưới 200 từ, tự dừng chờ CEO duyệt",
         "needs_review": True, "external_write": True},
    ]


def _final_email(headline: str) -> str:
    """A terminal artifact long enough to clear the final-deliverable floor: the CEO
    reads this text directly, so the artifact contract rejects a one-line stub and
    would send the step into rework."""
    return (
        f"{headline}\n\nKính gửi cả đội,\n\nMời mọi người họp review quý 3.\n"
        "- Thời gian: 10h thứ Sáu.\n- Địa điểm: phòng A.\n"
        "- Agenda: (1) số liệu quý 3, (2) việc trễ, (3) kế hoạch quý 4.\n\n"
        "Vui lòng xác nhận tham dự trước thứ Năm.\n\nTrân trọng,\nThư ký"
    )


def _happy_rules() -> list:
    return [
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_email_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp",
                        "Nháp: thời gian 10h thứ Sáu, địa điểm phòng A, agenda 3 mục."),
        rules.step_work("Chốt email mời họp", _final_email("Email chốt: 10h thứ Sáu, phòng A.")),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ]


def test_team_dag_happy_path_delivers_once(fullflow):
    h = fullflow(rules=_happy_rules())

    # 1. CEO gives the task in natural chat → real intent routing → plan preview.
    preview = h.trigger("Nhờ đội soạn email mời họp review quý 3 gồm thời gian, "
                        "địa điểm và agenda 3 mục nhé")
    assert preview, "CEO phải nhận được preview kế hoạch"

    # 2. CEO confirms like a real user — plain "ok" in the same chat.
    confirmed = h.trigger("ok")
    assert confirmed, "CEO phải nhận được xác nhận đã giao việc"

    tasks = h.task_rows()
    assert len(tasks) == 1, f"đúng 1 task được tạo, thấy: {tasks}"
    task_id = tasks[0]["id"]

    # 3. Daemon cadence: steps + review + delivery all happen inside pumps.
    h.pump(8)

    final = h.task_rows()[0]
    assert final["status"] == "done", f"task phải done, thấy: {final}"
    assert final["delivery_status"] == "delivered", f"phải delivered: {final}"
    assert final["reopen_count"] == 0 and final["autopilot_attempts"] == 0

    steps = h.step_rows(task_id)
    kinds = {s["step_type"] for s in steps}
    assert "review" in kinds, f"bước cuối external phải có soát chéo: {steps}"
    assert all(s["status"] == "done" for s in steps), steps

    # 4. What the CEO's phone saw: exactly one completion notice, silence after.
    texts = h.sent_texts()
    done_idx = [i for i, t in enumerate(texts) if "HOÀN THÀNH" in t]
    assert len(done_idx) == 1, f"đúng 1 tin hoàn thành, thấy: {texts}"

    h.pump(3)  # thêm 3 phút daemon — không được có tin mới nào
    assert h.sent_texts() == texts, "không tin nào sau HOÀN THÀNH"


def _internal_steps() -> list[dict]:
    """Same 2-step DAG but fully internal — nothing leaves the company, so the
    small-task waiver (≤3 all-internal steps) applies and NO peer review may be
    minted."""
    steps = _dag_email_steps()
    for s in steps:
        s.pop("external_write", None)
    return steps


def test_small_internal_task_waives_peer_review(fullflow):
    """Vision "tự chủ có kỷ luật": việc nhỏ nội bộ không đốt tiền soát chéo —
    nhưng vẫn phải done + delivered đúng một lần."""
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_internal_steps(), title="Email nội bộ"),
        rules.step_work("Soạn nháp email mời họp",
                        "Nháp nội bộ: thời gian 10h thứ Sáu, địa điểm phòng A, agenda 3 mục."),
        rules.step_work("Chốt email mời họp", _final_email("Bản chốt nội bộ.")),
        rules.self_check_pass(),
        # NO peer_review rule: if the product minted one anyway, the review
        # call would hit ScriptedLlm unmatched and fail the scenario loudly.
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])

    h.trigger("team: Nhờ đội soạn email mời họp nội bộ nhé")
    h.trigger("ok")
    h.pump(8)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    steps = h.step_rows(final["id"])
    kinds = {s["step_type"] for s in steps}
    assert "review" not in kinds, f"việc nhỏ nội bộ không được mint soát chéo: {steps}"
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1


def test_review_fail_then_rework_then_pass(fullflow):
    """Soát chéo lần 1 trượt → mint bước rework → soát lại đạt → giao đúng 1 lần.
    Toàn bộ vòng lặp chạy bằng cadence daemon, không gọi tay hàm nội bộ nào."""
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_email_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp",
                        "Nháp: thời gian 10h thứ Sáu, địa điểm phòng A, agenda 3 mục."),
        rules.step_work("Chốt email mời họp", _final_email("Email chốt (thiếu agenda).")),
        rules.self_check_pass(),
        rules.peer_review(False, ["Thiếu agenda 3 mục"], once=True),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(_final_email("Email chốt đã bổ sung agenda 3 mục.")),
    ])

    h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé")
    h.trigger("ok")
    h.pump(12)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    steps = h.step_rows(final["id"])
    kinds = [s["step_type"] for s in steps]
    assert kinds.count("rework") == 1, f"đúng 1 bước rework được mint: {steps}"
    assert kinds.count("review") == 2, f"soát lần 1 trượt + soát lại đạt: {steps}"
    assert all(s["status"] == "done" for s in steps), steps
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1


def test_review_exhausted_delivers_with_reviewer_objections(fullflow):
    """Reviewer trượt mãi → hết ngân sách soát (MAX_REVIEW_ROUNDS) → task VẪN giao:
    nội dung đã xong hết, chuỗi soát kết thúc lặng lẽ và bản giao mang header
    "Soát chéo chưa đạt" nêu ý kiến reviewer còn bỏ ngỏ. Hành vi cũ (stall + escalate)
    để một reviewer dao động giữ con tin cả task đã xong 100% — đo được lanes9b 3/4
    case. Vẫn chống flood: đúng MỘT tin giao, pump thêm không bắn lại."""
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_email_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp",
                        "Nháp: thời gian 10h thứ Sáu, địa điểm phòng A, agenda 3 mục."),
        rules.step_work("Chốt email mời họp", _final_email("Email chốt còn lỗi.")),
        rules.self_check_pass(),
        rules.peer_review(False, ["Sai định dạng ngày"]),  # trượt MỌI vòng
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])

    h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé")
    h.trigger("ok")
    h.pump(14)

    final = h.task_rows()[0]
    assert final["status"] == "done", f"phải giao được dù soát trượt mọi vòng: {final}"

    done_msgs = [t for t in h.sent_texts() if "HOÀN THÀNH" in t]
    assert len(done_msgs) == 1, f"đúng 1 tin giao: {h.sent_texts()}"
    # Ý kiến reviewer còn bỏ ngỏ phải đi theo bản giao — header dựng trong code.
    assert "Soát chéo chưa đạt" in done_msgs[0]
    assert "Sai định dạng ngày" in done_msgs[0]
    assert not any("bị dừng" in t for t in h.sent_texts())

    before = h.sent_texts()
    h.pump(4)  # daemon chạy tiếp — không được bắn lại tin giao (dedup gateway thật)
    assert h.sent_texts() == before, "không flood sau khi giao"


def test_duplicate_trigger_same_ts_is_dropped(fullflow):
    """Poll chồng lấn phát lại CÙNG một tin nhắn (cùng ts) — intake claim thật
    phải nuốt bản sao: không reply thứ hai, không draft/task thứ hai."""
    h = fullflow(rules=_happy_rules())

    ts = f"tg:{'990001'}:777"
    first = h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé", ts=ts)
    assert first, "lần đầu phải có preview"

    sent_after_first = h.sent_texts()
    replay = h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé", ts=ts)
    assert replay == "", f"bản phát lại phải bị nuốt, thấy reply: {replay!r}"
    assert h.sent_texts() == sent_after_first, "outbox không đổi sau bản phát lại"

    h.trigger("ok")
    h.pump(8)
    tasks = h.task_rows()
    assert len(tasks) == 1, f"đúng 1 task dù trigger bị phát lại: {tasks}"
    assert tasks[0]["status"] == "done"
