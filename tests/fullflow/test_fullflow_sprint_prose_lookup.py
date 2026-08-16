"""Full-flow scenario: sprint tra cứu đề VĂN XUÔI — vết C3 của benchmark v78.

Đề liệt kê chủ thể trong câu chạy ("của Notion, Figma, ... và Google Workspace")
từng resolve ra 0 entity: pipeline gửi đúng MỘT query kitchen-sink, nguồn trả 422,
và bản nộp trượt self-check vì toàn số bịa (task sống 647ee49de19d). Scenario này
chạy chính đề đó qua sản phẩm THẬT với web hai mặt — query nhắm đúng một chủ thể
mới có số liệu, query chung chung chỉ nhắc tới Notion suông — và model kỷ luật:
chỉ viết số cho chủ thể nào có dữ liệu trong context (đúng luật self-check thật).
Phủ đủ 5 công cụ vì vậy chỉ có thể đến từ quyết định tìm kiếm của CODE.
"""

from __future__ import annotations

from dataclasses import replace

from my_crew.tools.search_result_formatter import SearchResult

from . import scenario_rules as rules
from .scripted_llm import LlmRule

TOOLS = ("Notion", "Figma", "Obsidian", "Canva", "Google Workspace")

BRIEF = (
    "Tìm giá gói cá nhân/nhóm nhỏ (hoặc giá cho 5 người) của Notion, Figma, "
    "Obsidian, Canva và Google Workspace theo tháng; xác định công cụ nào đang "
    "có khuyến mãi hoặc gói miễn phí đủ dùng cho nhóm 5 người."
)
ACCEPTANCE = "Đủ 5 công cụ: giá theo tháng, khuyến mãi/gói miễn phí, mỗi mục có nguồn."

#: 5 chủ thể mua ngân sách scale (6 prefetch, 11 tổng) — trần cứng của scenario.
QUERY_BUDGET = 11


def _double_sided_web(seen_queries: list[str]):
    """Web giả hai mặt, cùng luật với release bench: chỉ query nêu ĐÚNG MỘT chủ thể
    mới trả về dòng số liệu `DỮ LIỆU <tên>`; mọi query khác là bài tổng quan nghèo
    chỉ nhắc tới Notion — không có số nào để một model kỷ luật trích được."""

    def _outcome(query: str, **_kw):
        seen_queries.append(query)
        named = [t for t in TOOLS if t.lower() in query.lower()]
        if len(named) == 1:
            tool = named[0]
            return (
                [SearchResult(
                    title=f"Bảng giá {tool}",
                    snippet=f"DỮ LIỆU {tool}: giá tháng 5 USD, có gói miễn phí cho nhóm 5 người",
                    source="example.com",
                )],
                "ok",
            )
        return (
            [SearchResult(
                title="Tổng quan công cụ làm việc nhóm",
                snippet="Notion là công cụ phổ biến trong nhóm nhỏ.",
                source="example.com",
            )],
            "ok",
        )

    return _outcome


def _faithful_draft(prompt: str) -> str:
    """Bản nháp kỷ luật: chỉ các công cụ có `DỮ LIỆU <tên>` trong context mới được
    một dòng số liệu — mô phỏng đúng ràng buộc self-check thật (không số thiếu nguồn)."""
    covered = [t for t in TOOLS if f"DỮ LIỆU {t}" in prompt]
    if not covered:
        return "Chưa thu thập được số liệu nào từ nguồn tìm kiếm."
    return "| Công cụ | Giá tháng | Miễn phí | Nguồn |\n" + "\n".join(
        f"| {t} | 5 USD | có gói miễn phí | https://example.com/{i} |"
        for i, t in enumerate(covered)
    )


def test_prose_brief_closes_all_five_tools_within_budget(fullflow, monkeypatch):
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.sprint_intake(BRIEF, assigned_to="analyst",
                            acceptance=ACCEPTANCE, needs_web=True),
        # Nháp + revise của sprint đều là role="content" mang đề bài trong prompt;
        # respond động đọc context nên một rule phục vụ được mọi vòng.
        LlmRule(role="content", marker="Tìm giá gói cá nhân",
                respond=_faithful_draft),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        rules.catch_all_content(),
    ])

    # Agent nhận việc phải có quyền web thật sự — sprint prefetch đi qua đúng
    # launcher sản phẩm (gate quyền + khoá nhà cung cấp), không đi cửa sau.
    analyst = h.cast["analyst"]
    h.cast["analyst"] = replace(
        analyst, web_search=True,
        settings=replace(analyst.settings, brave_api_key="scripted-brave"),
    )

    seen_queries: list[str] = []
    import my_crew.tools.web_search_tool as web_search_tool

    monkeypatch.setattr(
        web_search_tool, "web_search_outcome", _double_sided_web(seen_queries)
    )

    preview = h.trigger(BRIEF)
    assert "SPRINT" in preview, f"đề tra cứu một người phải đi đường sprint: {preview!r}"

    h.trigger("ok")
    h.pump(10)

    tasks = h.task_rows()
    assert len(tasks) == 1, f"đúng 1 task: {tasks}"
    final = tasks[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final

    steps = h.step_rows(final["id"])
    kinds = [s["step_type"] for s in steps]
    assert kinds.count("sprint") == 1 and "review" in kinds, steps

    # Chi tiêu tìm kiếm: trong trần, không hỏi lại câu đã hỏi, và mỗi chủ thể có
    # đúng một query nhắm riêng nó — cái mà bản v0.10.0 không làm được với đề này.
    assert 0 < len(seen_queries) <= QUERY_BUDGET, seen_queries
    assert len(set(q.lower() for q in seen_queries)) == len(seen_queries), (
        f"query trùng nhau: {seen_queries}"
    )
    for tool in TOOLS:
        targeted = [q for q in seen_queries
                    if tool.lower() in q.lower()
                    and sum(t.lower() in q.lower() for t in TOOLS) == 1]
        assert targeted, f"thiếu query nhắm riêng {tool}: {seen_queries}"

    # Bản nộp cuối: đủ 5 công cụ, và KHÔNG có ghi chú THIẾU — nguồn có dữ liệu
    # thì không được đổ lỗi cho nguồn.
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = h.store()
    try:
        row = store._conn.execute(
            "SELECT seq FROM team_steps WHERE task_id = ? AND step_type = 'sprint'",
            (final["id"],),
        ).fetchone()
    finally:
        store.close()
    artifact = read_step_artifact(team_tasks_root(), final["id"], int(row[0]))
    assert artifact is not None and artifact["status"] == "done", artifact
    result = artifact["result_text"]
    for tool in TOOLS:
        assert tool in result, f"bản nộp thiếu {tool}: {result!r}"
    assert "PHẦN THIẾU" not in result, result

    assert sum("HOÀN THÀNH" in t for t in h.sent_texts()) == 1
