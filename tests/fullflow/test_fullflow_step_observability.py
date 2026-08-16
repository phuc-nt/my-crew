"""Full-flow: trilogy quan sát v80 nhìn từ một task CEO giao thật.

Một kịch bản duy nhất chạy trọn pipeline (chat → decompose → step worker →
review → delivery → reflection) rồi soi cả bốn mặt quan sát trên CÙNG dữ liệu
đó — đúng như một CEO/操作 viên sẽ thấy sau một task thật:

  * P1: transcript JSONL per-attempt tồn tại, đủ meta/llm_request/llm_response/
    outcome, và llm_request giữ nguyên văn prompt (pi-style session).
  * P3: prompt peer-review nhận được bằng chứng quá trình từ transcript.
  * P4: office room của task có tín hiệu step_activity sống (phase "writing"),
    body đúng allowlist — không nội dung.
  * P5: reflection nhận behavior summary; bench đọc được usage per-step khớp
    transcript, không đụng cost trong ledger.
"""

from __future__ import annotations

import json

from my_crew.runtime.step_recorder import ACTIVITY_FIELDS, transcripts_dir

from . import scenario_rules as rules
from .scripted_llm import LlmRule


def _dag_steps() -> list[dict]:
    return [
        {"step_id": "draft", "title": "Soạn nháp email mời họp",
         "assigned_to": "secretary", "deps": [],
         "acceptance": "đủ thời gian, địa điểm, agenda", "needs_review": False},
        {"step_id": "finalize", "title": "Chốt email mời họp",
         "assigned_to": "writer", "deps": ["draft"],
         "acceptance": "email hoàn chỉnh, tự dừng chờ CEO duyệt",
         "needs_review": True, "external_write": True},
    ]


def test_v80_observability_rides_a_real_task(fullflow):
    review_prompts: list[str] = []
    reflect_prompts: list[str] = []

    def _capture_review(prompt: str) -> str:
        review_prompts.append(prompt)
        return json.dumps({"passed": True, "failures": [], "notes": []})

    def _capture_reflect(prompt: str) -> str:
        reflect_prompts.append(prompt)
        return "KHONG_CO_GI"

    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_steps(), title="Email mời họp quý 3"),
        rules.step_work("Soạn nháp email mời họp", "Nháp: 10h thứ Sáu, phòng A."),
        rules.step_work("Chốt email mời họp", "Email chốt: 10h thứ Sáu, phòng A."),
        rules.self_check_pass(),
        LlmRule(role="review", marker="", respond=_capture_review),
        LlmRule(role="util", marker="KHONG_CO_GI", respond=_capture_reflect),
        LlmRule(role="util", marker="", respond=""),
        rules.catch_all_content(),
    ])

    h.trigger("Nhờ đội soạn email mời họp review quý 3 gồm thời gian, "
              "địa điểm và agenda 3 mục nhé")
    h.trigger("ok")
    h.pump(8)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final
    task_id = final["id"]

    # ---- P1: transcript per-attempt — file thật, sự kiện thật, nguyên văn prompt.
    files = sorted(transcripts_dir(h.data_dir, task_id).glob("*.jsonl"))
    done_steps = [s for s in h.step_rows(task_id) if s["step_type"] != "review"]
    assert len(files) >= len(done_steps), (
        f"mỗi attempt content phải có transcript: {[f.name for f in files]}"
    )
    draft_file = next(f for f in files if f.name.startswith("draft-"))
    events = [json.loads(line) for line in
              draft_file.read_text(encoding="utf-8").splitlines()]
    kinds = [e["t"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "outcome", kinds
    assert "llm_request" in kinds and "llm_response" in kinds, kinds
    request = next(e for e in events if e["t"] == "llm_request")
    request_text = json.dumps(request["messages"], ensure_ascii=False)
    assert "Soạn nháp email mời họp" in request_text, (
        "llm_request phải giữ nguyên văn prompt của step"
    )
    outcome = next(e for e in events if e["t"] == "outcome")
    assert outcome["status"] == "done", outcome

    # ---- P3: peer review chấm bằng chứng quá trình, không chấm chay.
    assert review_prompts, "kịch bản phải có ít nhất một lần peer review"
    assert any("Tool & nguồn đã mở" in p for p in review_prompts), (
        "prompt review phải chứa evidence render từ transcript"
    )

    # ---- P4: office room thấy hoạt động sống trong lúc step chạy.
    from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = OfficeRoomStore(office_room_db_path(team_tasks_root()))
    try:
        activity = [m for m in store.list(task_id) if m.kind == "step_activity"]
    finally:
        store.close()
    assert activity, "phải có tín hiệu step_activity trong room của task"
    assert any(m.body.get("phase") == "writing" for m in activity), activity
    for m in activity:
        assert set(m.body) <= set(ACTIVITY_FIELDS), (
            f"body activity chỉ được chứa allowlist, thấy: {sorted(m.body)}"
        )

    # ---- P5a: reflection nhìn thấy hành vi quá trình (chỉ tên + số đếm).
    assert reflect_prompts, "reflection phải chạy sau khi task done"
    assert any("QUÁ TRÌNH LÀM" in p for p in reflect_prompts), (
        "prompt reflection phải có behavior summary khi transcript tồn tại"
    )
    assert not any("Nháp: 10h thứ Sáu" in p for p in reflect_prompts), (
        "behavior summary không được rò nội dung bản giao vào reflection"
    )

    # ---- P5b: bench phân rã usage per-step từ transcript, ledger giữ nguyên.
    from my_crew.bench.task_metrics import load_task_metric
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    metric = load_task_metric(team_tasks_db_path(), task_id, data_dir=h.data_dir)
    assert metric is not None
    content_steps = [s for s in metric.steps if s.step_type != "review"]
    assert content_steps and all(s.llm_calls >= 1 for s in content_steps), (
        f"mỗi step content phải có usage từ transcript: {metric.steps}"
    )
    plain = load_task_metric(team_tasks_db_path(), task_id)
    assert plain is not None
    assert [s.cost_usd for s in plain.steps] == [s.cost_usd for s in metric.steps], (
        "usage transcript không được làm đổi cost trong ledger"
    )
