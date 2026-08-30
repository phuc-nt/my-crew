"""Full-flow scenario: các nhánh FAIL của chế độ sprint — phần còn thiếu sau v81.

Hai test đầu chứng minh sprint thừa kế nguyên ladder soát chéo của team task
(quyết định v77 "sprint là team task suy biến"): trượt một vòng thì rework rồi
giao; trượt mãi thì stall + escalate ĐÚNG MỘT LẦN kèm gợi ý đổi chế độ `team:`
(reassign vô nghĩa vì mọi sprint chạy cùng một pipeline code).

Hai test sau chứng minh đường "trung thực khi thiếu dữ liệu" — chính pattern đã
giết baseline v0.10.0 ở brief C3 (brave 422 → stall 2 lần, $0.0915 mất trắng):
nguồn mỏng hay nguồn hỏng đều phải về đích với PHẦN THIẾU nói đúng lý do, không
bịa số và không stall.
"""

from __future__ import annotations

from dataclasses import replace

from my_crew.tools.search_result_formatter import SearchResult

from . import scenario_rules as rules
from .scripted_llm import LlmRule

GOAL = "Viết thông báo nghỉ lễ 2/9 cho toàn công ty"

# --- đề tra cứu cho 2 test THIẾU: 3 chủ thể, enumeration có "và" -------------------

TOOLS = ("Notion", "Obsidian", "Anki")
LOOKUP_BRIEF = (
    "Tìm giá gói cá nhân theo tháng của Notion, Obsidian và Anki; "
    "nêu công cụ nào có gói miễn phí."
)
LOOKUP_ACCEPTANCE = "Đủ 3 công cụ: giá theo tháng, gói miễn phí, mỗi mục có nguồn."


def _grant_web(h, agent_id: str) -> None:
    """Sprint prefetch đi qua launcher thật (gate quyền + khoá provider) — agent của
    scenario tra cứu phải được cấp cả hai, như test prose-lookup đã làm."""
    agent = h.cast[agent_id]
    h.cast[agent_id] = replace(
        agent, web_search=True,
        settings=replace(agent.settings, brave_api_key="scripted-brave"),
    )


def _web_with_data_for(covered: tuple[str, ...], *, broken: tuple[str, ...] = (),
                       seen_queries: list[str] | None = None):
    """Web giả cùng luật với release bench: query nêu ĐÚNG MỘT chủ thể trong
    `covered` mới có dòng số liệu; chủ thể trong `broken` trả provider_error
    (nguồn hỏng kiểu brave 422); còn lại là bài tổng quan mỏng không có số."""

    def _outcome(query: str, **_kw):
        if seen_queries is not None:
            seen_queries.append(query)
        named = [t for t in TOOLS if t.lower() in query.lower()]
        if len(named) == 1 and named[0] in broken:
            return [], "provider_error"
        if len(named) == 1 and named[0] in covered:
            tool = named[0]
            return (
                [SearchResult(
                    title=f"Bảng giá {tool}",
                    snippet=f"DỮ LIỆU {tool}: giá tháng 5 USD, có gói miễn phí",
                    source="example.com",
                )],
                "ok",
            )
        return (
            [SearchResult(
                title="Tổng quan công cụ ghi chú",
                snippet="Bài tổng quan chung, không có số liệu giá.",
                source="example.com",
            )],
            "ok",
        )

    return _outcome


def _faithful_lookup_draft(prompt: str) -> str:
    """Model kỷ luật: chỉ chủ thể có `DỮ LIỆU <tên>` trong context mới được một dòng
    số liệu — đúng ràng buộc self-check thật (không số thiếu nguồn)."""
    covered = [t for t in TOOLS if f"DỮ LIỆU {t}" in prompt]
    if not covered:
        return "Chưa thu thập được số liệu nào từ nguồn tìm kiếm."
    return "| Công cụ | Giá tháng | Miễn phí | Nguồn |\n" + "\n".join(
        f"| {t} | 5 USD | có | https://example.com/{i} |"
        for i, t in enumerate(covered)
    )


def _sprint_artifact_text(h, task_id: str) -> str:
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = h.store()
    try:
        row = store._conn.execute(
            "SELECT seq FROM team_steps WHERE task_id = ? AND step_type = 'sprint'",
            (task_id,),
        ).fetchone()
    finally:
        store.close()
    artifact = read_step_artifact(team_tasks_root(), task_id, int(row[0]))
    assert artifact is not None and artifact["status"] == "done", artifact
    return artifact["result_text"]


def test_sprint_review_fail_then_rework_then_pass(fullflow):
    """Soát chéo lần 1 trượt → mint rework → soát lại đạt → giao đúng 1 lần.
    Cùng khung với test team-mode tương ứng — chứng minh ladder là MỘT, không phải
    bản sao riêng cho sprint."""
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake(GOAL, assigned_to="writer"),
        rules.step_work("thông báo nghỉ lễ", "Thông báo: công ty nghỉ lễ 2/9."),
        rules.self_check_pass(),
        rules.peer_review(False, ["Thiếu ngày quay lại làm việc"], once=True),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content("Thông báo đã bổ sung ngày quay lại làm việc."),
    ])

    preview = h.trigger(GOAL)
    assert "SPRINT" in preview, f"đề một người phải đi đường sprint: {preview!r}"
    h.trigger("ok")
    h.pump(12)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    kinds = [s["step_type"] for s in h.step_rows(final["id"])]
    assert kinds.count("sprint") == 1, kinds
    assert kinds.count("rework") == 1, f"trượt 1 vòng phải mint đúng 1 rework: {kinds}"
    assert kinds.count("review") == 2, f"soát trượt + soát lại đạt: {kinds}"
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1


def test_sprint_dead_end_escalates_once_with_team_upgrade_hint(fullflow):
    """Đường bế tắc thật của sprint: self-check trượt mọi vòng → hết budget rework →
    needs_decision → thẩm phán kẹt phán give_up → stalled + escalate `gave_up` mang
    gợi ý `team:` (đổi chế độ là thuốc duy nhất — reassign chạy lại pipeline y hệt),
    route_json ghi dấu dead_end cho bộ đếm định tuyến, và không flood sau đó."""
    import json

    self_check_fail = json.dumps(
        {"passed": False, "failures": ["Sai ngày nghỉ"], "confidence": 0.2, "criteria": []},
        ensure_ascii=False,
    )
    give_up = json.dumps(
        {"decision": "give_up", "guidance": "", "assign_to": "",
         "reason": "không có dữ liệu ngày nghỉ chính thức để viết đúng"},
        ensure_ascii=False,
    )
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake(GOAL, assigned_to="writer"),
        rules.step_work("thông báo nghỉ lễ", "Thông báo còn lỗi."),
        LlmRule(role="review", marker='"confidence"', respond=self_check_fail),
        # Prompt thẩm phán kẹt là lời gọi review duy nhất chứa danh sách roster.
        LlmRule(role="review", marker="DANH SÁCH NGƯỜI CÓ THỂ NHẬN", respond=give_up),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])

    h.trigger(GOAL)
    h.trigger("ok")
    h.pump(14)

    final = h.task_rows()[0]
    assert final["status"] == "stalled", f"give_up phải stall task: {final}"

    # Gợi ý đổi chế độ giờ là lệnh một chạm mang theo kết quả dở dang, không còn là
    # lời nhắc CEO tự gõ lại đề sau tiền tố `team:`.
    hint_msgs = [t for t in h.sent_texts() if f"upgrade_to_team {final['id']}" in t]
    assert len(hint_msgs) == 1, (
        f"đúng 1 tin escalate mang gợi ý đổi chế độ: {h.sent_texts()}"
    )
    assert "KHÔNG LÀM ĐƯỢC" in hint_msgs[0], hint_msgs[0]
    assert not any("HOÀN THÀNH" in t for t in h.sent_texts())

    # Bộ định tuyến được báo là đã đoán sai về phía sprint — quyết định gốc giữ
    # trong `previous` để còn đếm được "đường nào dẫn tới bế tắc".
    store = h.store()
    try:
        route = store.get_route(final["id"])
    finally:
        store.close()
    assert route is not None and route.get("dead_end") is True, route
    assert route.get("previous"), route

    before = h.sent_texts()
    h.pump(4)
    assert h.sent_texts() == before, "không flood sau escalate"


def test_sprint_thin_sources_deliver_with_honest_missing_note(fullflow, monkeypatch):
    """Nguồn hoạt động nhưng mỏng với 1/3 chủ thể → hết vòng revise vẫn còn gap →
    VẪN giao, kèm PHẦN THIẾU 'đã tìm nhưng không đủ' nêu đúng tên chủ thể thiếu —
    không bịa số, không stall."""
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake(LOOKUP_BRIEF, assigned_to="analyst",
                            acceptance=LOOKUP_ACCEPTANCE, needs_web=True),
        LlmRule(role="content", marker="Tìm giá gói cá nhân",
                respond=_faithful_lookup_draft),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])
    _grant_web(h, "analyst")

    import my_crew.tools.web_search_tool as web_search_tool

    monkeypatch.setattr(
        web_search_tool, "web_search_outcome",
        _web_with_data_for(("Notion", "Obsidian")),  # Anki: chỉ có tổng quan mỏng
    )

    h.trigger(LOOKUP_BRIEF)
    h.trigger("ok")
    h.pump(10)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    result = _sprint_artifact_text(h, final["id"])
    assert "Notion" in result and "Obsidian" in result, result
    assert "PHẦN THIẾU" in result, f"còn gap phải tự khai: {result!r}"
    assert "Anki" in result, f"ghi chú thiếu phải nêu tên chủ thể: {result!r}"
    assert "đã tìm nhưng không đủ" in result, result
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1


def test_sprint_broken_source_delivers_note_instead_of_stalling(fullflow, monkeypatch):
    """Nguồn trả provider_error cho 1/3 chủ thể (kiểu brave 422 đã giết baseline C3)
    → chủ thể đó KHÔNG bị coi là gap tìm-lại-được (không đốt budget re-query), bản
    nộp vẫn giao với PHẦN THIẾU 'nguồn lỗi, tra cứu lại sau' — thay vì stall."""
    seen_queries: list[str] = []
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake(LOOKUP_BRIEF, assigned_to="analyst",
                            acceptance=LOOKUP_ACCEPTANCE, needs_web=True),
        LlmRule(role="content", marker="Tìm giá gói cá nhân",
                respond=_faithful_lookup_draft),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])
    _grant_web(h, "analyst")

    import my_crew.tools.web_search_tool as web_search_tool

    monkeypatch.setattr(
        web_search_tool, "web_search_outcome",
        _web_with_data_for(("Notion", "Obsidian"), broken=("Anki",),
                           seen_queries=seen_queries),
    )

    h.trigger(LOOKUP_BRIEF)
    h.trigger("ok")
    h.pump(10)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", (
        f"nguồn hỏng phải về đích với ghi chú, không stall: {final}"
    )

    result = _sprint_artifact_text(h, final["id"])
    assert "Notion" in result and "Obsidian" in result, result
    assert "PHẦN THIẾU" in result, result
    assert "NGUỒN LỖI" in result, f"phải nói rõ lý do là nguồn hỏng: {result!r}"
    assert "tra cứu lại sau" in result, result

    # Nguồn hỏng không phải gap tìm-lại-được: đúng MỘT query nhắm riêng Anki, không
    # có vòng nào đốt budget hỏi lại để nhận cùng một sentinel.
    anki_targeted = [q for q in seen_queries
                     if "anki" in q.lower()
                     and sum(t.lower() in q.lower() for t in TOOLS) == 1]
    assert len(anki_targeted) == 1, f"không được re-query nguồn đã hỏng: {seen_queries}"
    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1
