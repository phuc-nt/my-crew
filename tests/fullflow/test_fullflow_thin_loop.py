"""Full-flow: bước needs_web trên tier tools chạy THIN LOOP end-to-end (v86).

Kịch bản đi trọn pipeline thật (chat → decompose → worker → review → delivery)
với một bước tra cứu web giao cho agent `agent_runtime: create_agent` (engine
mặc định `thin`). Web hai mặt: các query prefetch (do code tự suy từ title) trả
provider_error nên launcher fail-open → bước GIỮ tier tools; chỉ query do model
"tự gõ" trong vòng lặp mới có dữ liệu. Vì vậy con số trong bản nộp chỉ có thể
đến từ vòng lặp thin: model gọi `web_search` → đọc kết quả → trả lời.

Soi trên cùng dữ liệu:
  * transcript per-attempt có llm_request (kèm tên tool trên wire) →
    tool_call/tool_result → llm_response per-exchange;
  * artifact của bước mang đúng số liệu từ kết quả tool;
  * task done + delivered — các hop còn lại (native writer, review) không đổi.
"""

from __future__ import annotations

import json
from dataclasses import replace

from my_crew.runtime_backends.config import AgentRuntimeConfig
from my_crew.tools.search_result_formatter import SearchResult

from . import scenario_rules as rules
from .scripted_llm import LlmRule, tool_call

LOOKUP_TITLE = "Tra giá Spotify Premium Việt Nam"
FINAL_TITLE = "Chốt bản tin giá Spotify"
#: Query mà model "tự gõ" trong vòng lặp — mặt duy nhất của web double có dữ liệu.
LOOP_QUERY = "giá spotify premium việt nam"
#: Sentinel chỉ tồn tại trong KẾT QUẢ tool (không lọt vào artifact/handoff) — dùng
#: làm marker định tuyến lượt thin-loop thứ hai.
DATA_MARK = "DỮ LIỆU SPOTIFY"
LOOKUP_RESULT = ("Giá Spotify Premium Việt Nam: 59.000đ/tháng "
                 "(nguồn: https://www.spotify.com/vn-vi/premium/).")

#: Terminal artifact long enough for the final-deliverable floor — a one-liner would
#: be sent to rework and never reach the CEO as-is.
FINAL_BULLETIN = (
    "Bản tin: Spotify Premium 59.000đ/tháng.\n\nGói Premium cá nhân tại Việt Nam hiện có "
    "giá 59.000đ/tháng theo bảng giá chính thức (nguồn: https://www.spotify.com/vn-vi/premium/). "
    "Mức giá này chưa đổi so với đầu năm; gói gia đình và sinh viên có giá riêng, không nằm "
    "trong phạm vi bản tin này."
)


def _dag_steps() -> list[dict]:
    return [
        {"step_id": "lookup", "title": LOOKUP_TITLE, "assigned_to": "analyst",
         "deps": [], "acceptance": "có giá tháng kèm nguồn", "needs_review": False,
         "needs_web": True},
        {"step_id": "finalize", "title": FINAL_TITLE, "assigned_to": "writer",
         "deps": ["lookup"], "acceptance": "bản tin ngắn có giá và nguồn",
         "needs_review": False},
    ]


def _two_sided_web(seen_queries: list[str]):
    """Chỉ query nhắm đúng của vòng lặp mới có dữ liệu; mọi query khác (prefetch
    suy từ title) trả provider_error → launcher fail-open, bước giữ tier tools."""

    def _outcome(query: str, **_kw):
        seen_queries.append(query)
        if query.strip().lower() == LOOP_QUERY:
            return (
                [SearchResult(
                    title="Bảng giá Spotify Premium",
                    snippet=f"{DATA_MARK}: gói Premium cá nhân 59.000đ/tháng",
                    source="spotify.com",
                )],
                "ok",
            )
        return [], "provider_error"

    return _outcome


def test_needs_web_step_runs_the_thin_loop_end_to_end(fullflow, monkeypatch):
    h = fullflow(rules=[
        rules.intent_assign_team_task(),
        rules.propose_no_consult(),
        rules.decompose(_dag_steps(), title="Bản tin giá Spotify"),
        rules.step_work(FINAL_TITLE, FINAL_BULLETIN),
        rules.self_check_pass(),
        rules.peer_review(True),
        *rules.utility_rules(),
        # Thin loop (role=None — complete_with_tools không mang role): lượt 1 khớp
        # title bước → gọi web_search; lượt 2 khớp sentinel trong KẾT QUẢ tool →
        # trả lời cuối. Đặt SAU mọi rule có role để không hớt call của hop khác.
        LlmRule(marker=LOOKUP_TITLE, once=True,
                respond=[tool_call("web_search",
                                   json.dumps({"query": LOOP_QUERY},
                                              ensure_ascii=False))]),
        LlmRule(marker=DATA_MARK, respond=LOOKUP_RESULT),
        rules.catch_all_content(),
    ])

    # Analyst chạy tier tools (create_agent ⇒ engine mặc định thin) và có quyền
    # web thật: opt-in + provider key — đúng gate sản phẩm, không cửa sau.
    analyst = h.cast["analyst"]
    h.cast["analyst"] = replace(
        analyst, web_search=True,
        agent_runtime=AgentRuntimeConfig(kind="create_agent"),
        settings=replace(analyst.settings, brave_api_key="scripted-brave"),
    )

    seen_queries: list[str] = []
    import my_crew.tools.web_search_tool as web_search_tool

    monkeypatch.setattr(
        web_search_tool, "web_search_outcome", _two_sided_web(seen_queries)
    )

    # `team:` — quyết định của CEO thắng bộ đoán sprint, giữ nguyên đường DAG mà
    # kịch bản này cần (bước tools-tier chỉ tồn tại ở đường team).
    h.trigger("team: Nhờ đội tra giá Spotify Premium ở Việt Nam rồi soạn một "
              "bản tin ngắn có nguồn nhé")
    h.trigger("ok")
    h.pump(8)

    final = h.task_rows()[0]
    assert final["status"] == "done" and final["delivery_status"] == "delivered", final
    task_id = final["id"]

    # Vòng lặp thật sự đã tự tìm: query của model có mặt, và có ít nhất một query
    # prefetch khác đã thử trước (provider_error) — chứng minh đường fail-open.
    assert LOOP_QUERY in [q.strip().lower() for q in seen_queries], seen_queries

    # ---- transcript của bước lookup: đủ chuỗi wire per-exchange.
    from my_crew.runtime.step_recorder import transcripts_dir

    files = sorted(transcripts_dir(h.data_dir, task_id).glob("lookup-*.jsonl"))
    assert files, "bước lookup phải có transcript per-attempt"
    # Bước review chèn thêm cũng glob ra đây — chọn đúng attempt LÀM VIỆC: file
    # duy nhất có tool_call.
    per_file = [
        [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
        for f in files
    ]
    with_tools = [evs for evs in per_file if any(e["t"] == "tool_call" for e in evs)]
    assert len(with_tools) == 1, (
        f"đúng một attempt có tool_call: {[f.name for f in files]}"
    )
    events = with_tools[0]
    kinds = [e["t"] for e in events]
    assert kinds[0] == "meta" and kinds[-1] == "outcome", kinds

    requests = [e for e in events if e["t"] == "llm_request"]
    assert any("web_search" in (e.get("tools") or []) for e in requests), (
        f"llm_request phải mang tên tool trên wire: {requests}"
    )
    calls = [e for e in events if e["t"] == "tool_call"]
    assert [c["name"] for c in calls] == ["web_search"], calls
    assert LOOP_QUERY in calls[0]["args_head"].lower(), calls
    results = [e for e in events if e["t"] == "tool_result"]
    assert results and DATA_MARK in results[0]["content_head"], results
    responses = [e for e in events if e["t"] == "llm_response"]
    assert any(r.get("finish_reason") == "tool_calls" and r.get("tool_calls")
               for r in responses), responses
    assert any(r.get("finish_reason") == "stop" for r in responses), responses

    # ---- artifact của bước lookup mang số liệu từ kết quả tool.
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = h.store()
    try:
        row = store._conn.execute(
            "SELECT seq FROM team_steps WHERE task_id = ? AND step_id = 'lookup'",
            (task_id,),
        ).fetchone()
    finally:
        store.close()
    artifact = read_step_artifact(team_tasks_root(), task_id, int(row[0]))
    assert artifact is not None and artifact["status"] == "done", artifact
    assert "59.000" in artifact["result_text"], artifact["result_text"]
    assert DATA_MARK not in artifact["result_text"], (
        "sentinel của kết quả tool không được rò vào artifact"
    )
