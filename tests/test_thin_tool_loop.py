"""Thin tool loop — wire behavior (W1-W6), guards, synthesis, accounting.

Everything is scripted through a fake LlmClient: these tests pin the EXACT message
shapes sent back to the provider, because the wire rules (content "" never null,
reasoning passback on tool-call turns, `(no output)` placeholder) are the point.
"""

from __future__ import annotations

from my_crew.llm.client import LlmResult, ToolExchange
from my_crew.runtime_backends.thin_tool_loop import run_thin_loop


def _lr(content: str = "", cost: float | None = 0.001) -> LlmResult:
    return LlmResult(
        content=content, model="x/y", prompt_tokens=100, completion_tokens=20,
        cost_usd=cost,
    )


def _tc(name: str, arguments: str, call_id: str = "t1") -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def _tool_turn(*calls: dict, reasoning: str | None = None,
               finish: str = "tool_calls", cost: float | None = 0.001) -> ToolExchange:
    msg: dict = {"role": "assistant", "content": None, "tool_calls": list(calls)}
    if reasoning is not None:
        msg["reasoning"] = reasoning
        msg["reasoning_details"] = [{"type": "reasoning.text", "text": reasoning}]
    return ToolExchange(message=msg, finish_reason=finish, result=_lr("", cost))


def _text_turn(text: str, finish: str = "stop", cost: float | None = 0.002) -> ToolExchange:
    return ToolExchange(
        message={"role": "assistant", "content": text},
        finish_reason=finish, result=_lr(text, cost),
    )


class _FakeLlm:
    def __init__(self, exchanges: list[ToolExchange], final_text: str = "tổng hợp"):
        self._ex = list(exchanges)
        self.tool_calls: list[dict] = []
        self.complete_calls: list[dict] = []
        self._final_text = final_text

    def complete_with_tools(self, messages, tools, **kw):
        self.tool_calls.append({
            "messages": [dict(m) for m in messages], "tools": tools,
        })
        return self._ex.pop(0)

    def complete(self, messages, **kw):
        self.complete_calls.append({"messages": [dict(m) for m in messages]})
        return _lr(self._final_text, 0.003)


class _Ctx:
    persona = "persona"
    project = "project"
    memory = ""
    capability = ""


def _settings():
    from my_crew.config.config_builders import build_settings_from_dict

    return build_settings_from_dict({"openrouter_api_key": "k", "openrouter_model": "x/y"})


def _run(llm, tools_map, max_steps: int = 4, telemetry=None):
    return run_thin_loop(
        title="Tìm giá", handoff="", context=_Ctx(), settings=_settings(),
        tools_map=tools_map, max_steps=max_steps, telemetry=telemetry, llm=llm,
    )


def test_happy_path_two_rounds():
    seen = []

    def _search(args):
        seen.append(args)
        return "kết quả: 65.000đ (spotify.com)"

    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "giá spotify vn"}'), reasoning="need facts"),
        _text_turn("Giá là 65.000đ/tháng (spotify.com)"),
    ])
    text, cost = _run(llm, {"web.search": _search})
    assert text == "Giá là 65.000đ/tháng (spotify.com)"
    assert seen == [{"query": "giá spotify vn"}]
    assert cost == 0.001 + 0.002

    # wire shapes of round 2's request (W1/W2/W3):
    msgs = llm.tool_calls[1]["messages"]
    assistant = next(m for m in msgs if m["role"] == "assistant")
    assert assistant["content"] == ""  # W1: "" never null
    assert assistant["reasoning"] == "need facts"  # W2: passback on tool-call turn
    assert assistant["tool_calls"][0]["function"]["name"] == "web_search"
    tool_msg = next(m for m in msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "t1"
    assert "65.000" in tool_msg["content"]


def test_empty_tool_result_becomes_no_output_placeholder():
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "x"}')),
        _text_turn("xong"),
    ])
    _run(llm, {"web.search": lambda args: ""})
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert tool_msg["content"] == "(no output)"  # W3


def test_length_finish_fails_batch_without_executing():
    executed = []
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), finish="length"),
        _text_turn("done"),
    ])
    text, _ = _run(llm, {"web.search": lambda args: executed.append(args) or "r"})
    assert text == "done"
    assert executed == []  # batch NOT executed
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert "bị cắt" in tool_msg["content"] or "truncated" in tool_msg["content"]


def test_repeat_identical_batch_not_executed_gets_reminder():
    executed = []
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}')),
        _tool_turn(_tc("web_search", '{"query": "a"}', call_id="t2")),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: executed.append(args) or "same result"})
    assert len(executed) == 1  # second identical batch skipped
    tool_msg = next(
        m for m in llm.tool_calls[2]["messages"]
        if m["role"] == "tool" and m["tool_call_id"] == "t2"
    )
    assert "same result" not in tool_msg["content"]  # reminder, not a re-run


def test_max_steps_triggers_synthesis_without_tools():
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}')),
    ], final_text="tổng hợp từ dữ liệu đã có")
    text, cost = _run(llm, {"web.search": lambda args: "data"}, max_steps=1)
    assert text == "tổng hợp từ dữ liệu đã có"
    assert len(llm.complete_calls) == 1
    joined = "\n".join(m["content"] for m in llm.complete_calls[0]["messages"])
    assert "DỪNG" in joined  # the synthesis instruction is present
    assert cost == 0.001 + 0.003  # tool round + synthesis turn


def test_missing_required_param_returns_error_without_executing():
    executed = []
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", "{}")),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: executed.append(args) or "r"})
    assert executed == []
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert "query" in tool_msg["content"]


def test_invented_fields_dropped_and_echoed():
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a", "max_results": 9}')),
        _text_turn("done"),
    ])
    seen = []
    _run(llm, {"web.search": lambda args: seen.append(args) or "r"})
    assert seen == [{"query": "a"}]
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert "max_results" in tool_msg["content"]  # W6: echo dropped fields


def test_unknown_tool_name_gets_error_result():
    llm = _FakeLlm([
        _tool_turn(_tc("bash", '{"command": "rm -rf /"}')),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: "r"})
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert "bash" in tool_msg["content"]


def test_raising_tool_degrades_to_error_result():
    def _boom(args):
        raise RuntimeError("provider down")

    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}')),
        _text_turn("done"),
    ])
    text, _ = _run(llm, {"web.search": _boom})
    assert text == "done"
    tool_msg = next(m for m in llm.tool_calls[1]["messages"] if m["role"] == "tool")
    assert "⚠️" in tool_msg["content"]


def test_telemetry_records_exact_cost_source():
    from my_crew.runtime.step_telemetry import StepTelemetry

    tel = StepTelemetry()
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}')),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: "r"}, telemetry=tel)
    assert tel.input_tokens == 200  # two exchanges × 100
    assert tel.output_tokens == 40
    assert tel.cost_source == "exact"


def test_no_reasoning_on_final_turn_passback_not_required():
    """Final text turn ends the loop — nothing is passed back after it, so the loop
    only ever passes reasoning back on tool-call turns (W2 by construction)."""
    llm = _FakeLlm([_text_turn("ngay lập tức")])
    text, cost = _run(llm, {"web.search": lambda args: "r"})
    assert text == "ngay lập tức"
    assert len(llm.tool_calls) == 1


def _capture_events(monkeypatch) -> list[dict]:
    """`record_event` is a no-op outside a step — capture at the source module (both
    `_execute_call` and `_batch_results` import it from there at call time)."""
    import my_crew.runtime.step_recorder as step_recorder

    recorded: list[dict] = []
    monkeypatch.setattr(step_recorder, "record_event", recorded.append)
    return recorded


def test_length_guard_round_records_transcript_events(monkeypatch):
    recorded = _capture_events(monkeypatch)
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), finish="length"),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: "r"})
    # The guarded (unexecuted) round is a tool-call error by definition — the exact
    # signal the A/B bench counts — so it must appear in the transcript like any round.
    calls = [e for e in recorded if e["t"] == "tool_call"]
    results = [e for e in recorded if e["t"] == "tool_result"]
    assert [c["name"] for c in calls] == ["web_search"]
    assert len(results) == 1 and "bị cắt giữa chừng" in results[0]["content_head"]


def test_repeat_guard_round_records_transcript_events(monkeypatch):
    recorded = _capture_events(monkeypatch)
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}')),
        _tool_turn(_tc("web_search", '{"query": "a"}', call_id="t2")),
        _text_turn("done"),
    ])
    _run(llm, {"web.search": lambda args: "same result"})
    results = [e for e in recorded if e["t"] == "tool_result"]
    assert len(results) == 2  # executed round + guarded round, both visible
    assert "same result" in results[0]["content_head"]
    assert "Y HỆT" in results[1]["content_head"]


def test_typed_specs_reach_the_wire():
    llm = _FakeLlm([_text_turn("ok")])
    _run(llm, {"web.search": lambda args: "r", "web.scrape": lambda args: "r"})
    names = [t["function"]["name"] for t in llm.tool_calls[0]["tools"]]
    assert names == ["web_search", "web_fetch"]
