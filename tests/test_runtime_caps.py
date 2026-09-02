"""v20.5 Phase 1: per-runtime caps — runtime_loop_limit + sandbox validation + config→runtime."""

from __future__ import annotations

import pytest

from my_crew.runtime_backends.config import (
    MAX_LOOP_STEPS,
    AgentRuntimeConfig,
    parse_agent_runtime_config,
)


def test_default_loop_limit_per_kind():
    assert parse_agent_runtime_config("native").caps().runtime_loop_limit == 0
    assert parse_agent_runtime_config("create_agent").caps().runtime_loop_limit == MAX_LOOP_STEPS
    assert parse_agent_runtime_config("deep_agent").caps().runtime_loop_limit == 16


def test_the_tools_tier_cap_covers_a_real_research_step():
    """Hitting the cap is NOT a graceful stop: `invoke_capped` degrades to an empty result, so
    the step discards every search it already paid for and self-check sees nothing. Measured
    research steps (search → read → search again for the gaps) run 9-15 tool rounds, so a cap
    below that spread throws away good work at random. Pins the floor, not the exact number."""
    assert MAX_LOOP_STEPS >= 16


def test_override_loop_limit():
    c = parse_agent_runtime_config({"kind": "create_agent", "runtime_loop_limit": 3})
    assert c.caps().runtime_loop_limit == 3


def test_string_form_backcompat():
    # v20 string form still parses to kind-only with default caps.
    c = parse_agent_runtime_config("create_agent")
    assert c.kind == "create_agent"
    assert c.runtime_loop_limit is None  # unset → default at caps()


def test_negative_loop_limit_rejected():
    with pytest.raises(RuntimeError, match="runtime_loop_limit"):
        parse_agent_runtime_config({"kind": "create_agent", "runtime_loop_limit": -1})


def test_negative_cost_rejected():
    with pytest.raises(RuntimeError, match="cost_cap_usd"):
        parse_agent_runtime_config({"kind": "create_agent", "cost_cap_usd": -5})


def test_sandbox_only_on_deep():
    with pytest.raises(RuntimeError, match="chỉ dùng cho deep_agent"):
        parse_agent_runtime_config({"kind": "create_agent", "sandbox": {"provider": "fake"}})


def test_sandbox_provider_allowlist():
    # local / unknown providers rejected (red-team C3 positive allowlist, at parse time).
    with pytest.raises(RuntimeError, match="không hợp lệ"):
        parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "local"}})
    with pytest.raises(RuntimeError, match="không hợp lệ"):
        parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "modal"}})
    # docker (self-hosted) + fake (test) are the allowed providers.
    assert parse_agent_runtime_config(
        {"kind": "deep_agent", "sandbox": {"provider": "docker"}}
    ).sandbox == {"provider": "docker"}


def test_deep_sandbox_valid():
    c = parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "fake"}})
    assert c.caps().sandbox == {"provider": "fake"}


def test_cost_cap_is_on_by_default_for_the_tool_tiers_and_off_for_native():
    """Trần chi phí mỗi bước BẬT sẵn ở hai tier có vòng lặp công cụ, TẮT ở native.

    Trước context-crew mặc định là `None` ở cả ba tier (opt-in). Đổi vì vòng lặp công cụ
    là chỗ duy nhất một bước tiêu tiền không giới hạn (mỗi vòng = một cuộc gọi trả phí +
    một tool), nên lưới mặc định phải là một con số và profile nào cần hơn thì tự nâng.
    Native không có vòng lặp — không có gì để chặn — nên vẫn `None`.

    Ghim CẢ hai chiều: ai đặt native thành số sẽ "bật" trần cho tier không enforce nó;
    ai đặt tool tier về `None` sẽ tắt lưới cho toàn fleet mà không test nào đỏ.
    """
    from my_crew.runtime_backends.config import DEFAULT_STEP_COST_CAP_USD

    assert DEFAULT_STEP_COST_CAP_USD > 0
    assert parse_agent_runtime_config({"kind": "native"}).caps().cost_cap_usd is None
    for kind in ("create_agent", "deep_agent"):
        assert parse_agent_runtime_config({"kind": kind}).caps().cost_cap_usd == (
            DEFAULT_STEP_COST_CAP_USD
        ), f"tier {kind} mất trần chi phí mặc định — lưới per-step tắt cho toàn fleet"
    c = parse_agent_runtime_config({"kind": "deep_agent", "cost_cap_usd": 4.0})
    assert c.caps().cost_cap_usd == 4.0


def test_zero_cost_cap_rejected():
    """Trần 0 = mọi bước chết ở vòng 0, nên chặn ngay ở parse thay vì để fleet im lặng rỗng.

    `over_cost_cap` hỏi "còn tiền cho vòng nữa không" TRƯỚC cuộc gọi đầu, mà `sum([]) >= 0`
    đúng ⇒ vòng lặp break ở round 0, không gọi provider lần nào, bước chỉ còn lại ghi chú
    "chưa hoàn chỉnh". Người viết `cost_cap_usd: 0` gần như chắc chắn định nói "không giới
    hạn" — mà cách nói đó là bỏ trống key (None), đã ghi trong docstring của guard.
    """
    with pytest.raises(RuntimeError, match="cost_cap_usd"):
        parse_agent_runtime_config({"kind": "create_agent", "cost_cap_usd": 0})


def test_loop_engine_defaults_to_thin():
    assert parse_agent_runtime_config("create_agent").loop_engine == "thin"
    assert parse_agent_runtime_config({"kind": "create_agent"}).loop_engine == "thin"


def test_loop_engine_langchain_selectable():
    c = parse_agent_runtime_config({"kind": "create_agent", "loop_engine": "langchain"})
    assert c.loop_engine == "langchain"


def test_loop_engine_unknown_rejected():
    with pytest.raises(RuntimeError, match="loop_engine"):
        parse_agent_runtime_config({"kind": "create_agent", "loop_engine": "magic"})


def test_loop_engine_only_on_create_agent():
    with pytest.raises(RuntimeError, match="loop_engine"):
        parse_agent_runtime_config({"kind": "deep_agent", "loop_engine": "thin"})


def test_loop_engine_dispatches_to_the_selected_loop(monkeypatch):
    # The work override runs the thin loop by default and the LangChain react loop
    # when the profile pins `loop_engine: langchain` (the A/B baseline).
    import my_crew.runtime_backends.react_loop as react_loop
    import my_crew.runtime_backends.read_only_toolset as toolset
    import my_crew.runtime_backends.thin_tool_loop as thin_tool_loop
    from my_crew.runtime_backends.tool_calling_runtime import ToolCallingRuntime

    monkeypatch.setattr(toolset, "build_read_toolset", lambda *a, **k: {})
    monkeypatch.setattr(toolset, "assert_read_only", lambda names: None)
    called: list[str] = []
    monkeypatch.setattr(
        react_loop, "run_react_work",
        lambda **k: called.append("langchain") or ("t", None),
    )
    monkeypatch.setattr(
        thin_tool_loop, "run_thin_loop",
        lambda **k: called.append("thin") or ("t", None),
    )

    rt = ToolCallingRuntime()
    for engine in ("thin", "langchain"):
        work = rt._make_work_override(None, None, None, 4, loop_engine=engine)
        assert work("t", "", None) == ("t", None)
    assert called == ["thin", "langchain"]


def test_tool_calling_uses_config_loop_limit():
    # ToolCallingRuntime.build_task threads runtime_config → caps().runtime_loop_limit.
    from my_crew.runtime_backends.tool_calling_runtime import ToolCallingRuntime

    captured = {}
    rt = ToolCallingRuntime()

    def _fake_build(**kw):
        return "graph"

    import my_crew.agent.team_task_graph as ttg

    orig = ttg.build_team_task_graph
    ttg.build_team_task_graph = lambda **kw: (captured.update(kw) or "graph")
    try:
        cfg = AgentRuntimeConfig(kind="create_agent", runtime_loop_limit=5)
        rt.build_task(settings=None, context=None, runtime_config=cfg, reporting_config=None)
    finally:
        ttg.build_team_task_graph = orig
    # work_override captured; the loop_limit is closed over — assert it ran without runtime_config
    # leaking into build_team_task_graph (popped).
    assert "runtime_config" not in captured
    assert "reporting_config" not in captured
    assert "work_override" in captured
