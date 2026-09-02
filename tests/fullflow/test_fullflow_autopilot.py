"""Full-flow scenario: trần soát chéo không còn tạo việc cho autopilot.

Cùng một tình huống với `test_review_exhausted_delivers_with_reviewer_objections`
(reviewer trượt mọi vòng) nhưng công ty BẬT autopilot. Trước đây trần soát stall task
và autopilot phải leo thang gỡ hộ; giờ trần soát kết thúc chuỗi và task tự giao kèm
ý kiến reviewer — autopilot không có gì để gỡ và không được đốt lượt nào. Thang leo
của autopilot cho các nguồn stall còn lại vẫn được pin ở `test_autopilot.py`
(`test_sweep_rung1_retry_rung2_replan_rung3_accept_then_stops`).
"""

from __future__ import annotations

from . import scenario_rules as rules
from .test_fullflow_team_task import _dag_email_steps, _final_email


def test_review_cap_leaves_autopilot_nothing_to_resolve(fullflow):
    h = fullflow(autopilot=True, rules=[
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

    # Autopilot kéo theo tự-xác-nhận (`ops_assign_team_task`: autopilot_enabled()
    # ⇒ auto-confirm) — KHÔNG gõ "ok", nếu gõ thì tin đó bị hiểu là brief MỚI và
    # sinh thêm một task sprint thứ hai.
    h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé")
    h.pump(20)

    assert len(h.task_rows()) == 1, f"chỉ 1 task được tạo: {h.task_rows()}"

    final = h.task_rows()[0]

    # 1. Không còn stall để gỡ: trần soát tự kết thúc chuỗi và task giao được.
    assert final["status"] == "done", f"phải giao được, không kẹt: {final}"
    assert final["autopilot_attempts"] == 0, (
        f"trần soát không stall thì autopilot không được đốt lượt nào: {final}"
    )

    # 2. Ý kiến reviewer còn bỏ ngỏ vẫn đến tay CEO — qua chính bản giao.
    done_msgs = [t for t in h.sent_texts() if "HOÀN THÀNH" in t]
    assert len(done_msgs) == 1, f"đúng 1 tin giao: {h.sent_texts()}"
    assert "Soát chéo chưa đạt" in done_msgs[0]

    # 3. Ổn định: pump thêm không đốt lượt autopilot, không flood tin.
    sent_before = len(h.sent_texts())
    h.pump(6)
    after = h.task_rows()[0]
    assert after["autopilot_attempts"] == 0, f"autopilot vào cuộc vô cớ: {after}"
    assert len(h.sent_texts()) == sent_before, "không flood sau khi giao"
