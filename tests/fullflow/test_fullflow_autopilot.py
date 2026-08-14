"""Full-flow scenario: autopilot tự gỡ việc kẹt thay CEO.

Cùng một tình huống với `test_review_exhausted_stalls_and_escalates_once` (reviewer
trượt mọi vòng) nhưng công ty BẬT autopilot. Vision "tự chủ có kỷ luật": máy tự leo
thang (thử lại → chỉnh kế hoạch → chấp nhận kết quả) trong trần cho phép thay vì đẩy
hết sang CEO — nhưng vẫn có trần, vẫn ghi nhật ký quyết định.
"""

from __future__ import annotations

from . import scenario_rules as rules
from .test_fullflow_team_task import _dag_email_steps


def test_autopilot_resolves_review_stall_without_ceo(fullflow):
    h = fullflow(autopilot=True, rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_email_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp", "Nháp."),
        rules.step_work("Chốt email mời họp", "Email chốt còn lỗi."),
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

    # 1. Autopilot đã thực sự leo thang — không nằm im chờ CEO.
    assert final["autopilot_attempts"] > 0, f"autopilot phải vào cuộc: {final}"
    assert final["autopilot_attempts"] <= 3, f"phải tôn trọng trần leo thang: {final}"

    # 2. Không kẹt vĩnh viễn: hoặc về đích, hoặc dừng hẳn sau khi cạn trần.
    assert final["status"] in ("done", "stalled"), final

    # 3. Có trần thật: pump thêm cũng không đốt thêm lượt autopilot nào.
    attempts_before = final["autopilot_attempts"]
    sent_before = len(h.sent_texts())
    h.pump(6)
    after = h.task_rows()[0]
    assert after["autopilot_attempts"] == attempts_before, f"vượt trần: {after}"
    assert len(h.sent_texts()) == sent_before, "không flood sau khi autopilot cạn lượt"
