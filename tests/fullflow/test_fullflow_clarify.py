"""Full-flow scenario: nhân sự hỏi CEO giữa chừng (clarify) rồi việc vẫn chạy tiếp.

Vision "tự chủ có kỷ luật": hỏi CEO KHÔNG chặn bước — bước làm tiếp theo phương án an
toàn nhất, câu trả lời của CEO vào bước sau. Scenario chứng minh cả hai nửa: câu hỏi
thật sự tới điện thoại CEO (kèm nút bấm), và việc vẫn về đích sau khi CEO trả lời.
"""

from __future__ import annotations

from . import scenario_rules as rules
from .test_fullflow_team_task import _dag_email_steps


def _clarify_rules() -> list:
    return [
        rules.intent_assign_team_task(),
        # Bước đầu tiên hỏi CEO một lần; các bước sau tự quyết.
        rules.propose_ask_ceo("Họp sáng hay chiều?", ["Sáng", "Chiều"], once=True),
        rules.propose_no_consult(),
        rules.decompose(_dag_email_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp", "Nháp: chờ CEO chốt buổi."),
        rules.step_work("Chốt email mời họp", "Email chốt theo giờ CEO đã chọn."),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ]


def test_step_asks_ceo_without_blocking_then_task_completes(fullflow):
    h = fullflow(rules=_clarify_rules())

    h.trigger("Nhờ đội soạn email mời họp review quý 3 nhé")
    h.trigger("ok")
    h.pump(4)

    # 1. Câu hỏi tới đúng điện thoại CEO, kèm 2 nút bấm.
    asks = [e for e in h.outbox
            if e["method"] == "sendMessage" and "hỏi:" in str(e["payload"].get("text", ""))]
    assert len(asks) == 1, f"đúng 1 câu hỏi tới CEO: {h.sent_texts()}"
    assert "Họp sáng hay chiều?" in asks[0]["payload"]["text"]
    markup = str(asks[0]["payload"].get("reply_markup", ""))
    assert "Sáng" in markup and "Chiều" in markup, f"phải có nút bấm: {asks[0]['payload']}"

    # 2. Hỏi KHÔNG chặn: bước vẫn chạy tiếp, không stall.
    assert h.task_rows()[0]["status"] != "stalled", h.task_rows()

    # 3. CEO bấm nút → việc về đích, giao đúng một lần.
    h.answer_clarify("Sáng")
    h.pump(8)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1
