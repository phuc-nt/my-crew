"""Full-flow scenario: chế độ SPRINT — một người làm trọn.

`classify_brief` MẶC ĐỊNH là sprint (thuần code, không gọi model): đề vừa sức không có
tín hiệu cần đội thì một người làm trọn trong một lượt — rẻ hơn và nhanh hơn phân rã.
Scenario chứng minh đường rẻ này về đích thật, và vẫn có đúng một lượt soát chéo (sprint
luôn mint review bất kể band tin cậy — quyết định v76 sau đo lường).
"""

from __future__ import annotations

from . import scenario_rules as rules


def test_simple_brief_runs_as_sprint_and_delivers_once(fullflow):
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake("Viết lời cảm ơn khách hàng thân thiết",
                            assigned_to="writer"),
        rules.step_work("", "Thư cảm ơn: kính gửi quý khách..."),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])

    # Đề vừa sức, không có tín hiệu cần đội → classify_brief chọn sprint.
    preview = h.trigger("Viết giúp tôi lời cảm ơn khách hàng thân thiết")
    assert "SPRINT" in preview, f"đề đơn giản phải đi đường sprint: {preview!r}"

    h.trigger("ok")
    h.pump(10)

    tasks = h.task_rows()
    assert len(tasks) == 1, f"đúng 1 task: {tasks}"
    final = tasks[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    steps = h.step_rows(final["id"])
    kinds = [s["step_type"] for s in steps]
    assert kinds.count("sprint") == 1, f"sprint chỉ một bước làm: {steps}"
    assert "review" in kinds, f"sprint vẫn phải có soát chéo: {steps}"
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1

    before = h.sent_texts()
    h.pump(3)
    assert h.sent_texts() == before, "không tin nào sau HOÀN THÀNH"
