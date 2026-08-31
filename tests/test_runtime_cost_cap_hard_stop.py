"""Per-step spend ceiling: the thin loop stops BEFORE the round it cannot afford.

The guard's whole value is that it saves the *next* call, so every test here counts
provider calls rather than inspecting text alone — a version that noticed the ceiling
only after paying for one more round would still produce a plausible-looking answer.

Wired end to end as well: `RuntimeCaps.cost_cap_usd` has to survive the trip from the
profile block through `ToolCallingRuntime` into the loop, which is the seam that made
this cap decorative for as long as it existed.
"""

from __future__ import annotations

import pytest

from my_crew.llm.client import LlmResult, ToolExchange
from my_crew.runtime_backends.loop_cost_guard import over_cost_cap, with_cost_cap_gap_note
from my_crew.runtime_backends.thin_tool_loop import run_thin_loop


def _lr(content: str = "", cost: float | None = 0.001) -> LlmResult:
    return LlmResult(
        content=content, model="x/y", prompt_tokens=100, completion_tokens=20,
        cost_usd=cost,
    )


def _tc(name: str, arguments: str, call_id: str = "t1") -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def _tool_turn(*calls: dict, content: str = "", cost: float | None = 0.001) -> ToolExchange:
    """A round where the model wants tools. `content` lets a case leave prose behind so
    the capped exit has something to recover."""
    msg: dict = {"role": "assistant", "content": content or None, "tool_calls": list(calls)}
    return ToolExchange(message=msg, finish_reason="tool_calls", result=_lr("", cost))


def _text_turn(text: str, cost: float | None = 0.002) -> ToolExchange:
    return ToolExchange(
        message={"role": "assistant", "content": text},
        finish_reason="stop", result=_lr(text, cost),
    )


class _FakeLlm:
    """Counts both call paths: `complete_with_tools` (loop rounds) and `complete` (the
    salvage synthesis). The cap must suppress the second as well as the first."""

    def __init__(self, exchanges: list[ToolExchange]):
        self._ex = list(exchanges)
        self.rounds = 0
        self.synthesis_calls = 0

    def complete_with_tools(self, messages, tools, **kw):
        self.rounds += 1
        if not self._ex:
            raise AssertionError("loop asked for a round past the scripted exchanges")
        return self._ex.pop(0)

    def complete(self, messages, **kw):
        self.synthesis_calls += 1
        return _lr("tổng hợp cuối", 0.005)


class _Ctx:
    persona = "persona"
    project = "project"
    memory = ""
    capability = ""


def _settings():
    from my_crew.config.config_builders import build_settings_from_dict

    return build_settings_from_dict({"openrouter_api_key": "k", "openrouter_model": "x/y"})


def _run(llm, tools_map, *, max_steps: int = 6, cost_cap_usd: float | None = None):
    return run_thin_loop(
        title="Tìm giá", handoff="", context=_Ctx(), settings=_settings(),
        tools_map=tools_map, max_steps=max_steps, llm=llm, cost_cap_usd=cost_cap_usd,
    )


def _search(args):
    return "kết quả: 65.000đ"


# --- over_cost_cap: the predicate itself ------------------------------------------------


def test_no_cap_never_trips():
    assert over_cost_cap([1.0, 2.0, 3.0], None) is False


def test_cap_trips_at_exactly_the_cap():
    # `>=` not `>`: the allowance is spent, and the question asked is "can I afford
    # another round", not "have I already overshot".
    assert over_cost_cap([0.01], 0.01) is True
    assert over_cost_cap([0.009], 0.01) is False


def test_gap_note_separates_only_when_there_is_partial_work():
    with_work = with_cost_cap_gap_note("đã tra được A", [0.02], 0.01, 1)
    assert with_work.startswith("đã tra được A\n\n---\n[Kết quả CHƯA hoàn chỉnh")

    # No prose recovered ⇒ no rule separating nothing.
    alone = with_cost_cap_gap_note("", [0.02], 0.01, 1)
    assert alone.startswith("[Kết quả CHƯA hoàn chỉnh")
    assert "---" not in alone


# --- the loop --------------------------------------------------------------------------


def test_loop_stops_before_the_round_it_cannot_afford():
    # Three rounds scripted at $0.004 each; cap $0.010. After round 3 the spend is
    # $0.012 >= cap, so round 4 must never be requested.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), content="đã tra vòng 1", cost=0.004),
        _tool_turn(_tc("web_search", '{"query": "b"}'), content="đã tra vòng 2", cost=0.004),
        _tool_turn(_tc("web_search", '{"query": "c"}'), content="đã tra vòng 3", cost=0.004),
    ])
    text, cost = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.010)

    assert llm.rounds == 3  # the 4th round was never paid for
    assert cost == pytest.approx(0.012)
    assert "đã tra vòng 3" in text  # partial work kept, not discarded
    assert "CHƯA hoàn chỉnh" in text  # and labelled as partial


def test_capped_exit_does_not_pay_for_a_synthesis_turn():
    # Spending one more call to explain that spending stopped would defeat the guard.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), content="một phần", cost=0.02),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.01)

    assert llm.synthesis_calls == 0
    assert "tổng hợp cuối" not in text


def test_gap_note_reports_the_cap_the_spend_and_the_rounds():
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), content="một phần", cost=0.0250),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.0200)

    assert "$0.0200" in text  # the ceiling
    assert "$0.0250" in text  # what was actually spent
    assert "1 vòng" in text   # how far it got


def test_capped_with_no_prose_yields_the_note_alone():
    # A loop that only ever called tools has no assistant prose to recover. The note must
    # still stand on its own rather than the step returning an empty string.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.02),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.01)

    assert text.startswith("[Kết quả CHƯA hoàn chỉnh")


def test_cap_none_leaves_the_loop_untouched():
    # The default on every tier. Same script as the capped case, but the loop runs to its
    # natural end and pays for the salvage synthesis.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.004),
        _tool_turn(_tc("web_search", '{"query": "b"}'), cost=0.004),
        _text_turn("Giá là 65.000đ", cost=0.004),
    ])
    text, cost = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=None)

    assert llm.rounds == 3
    assert text == "Giá là 65.000đ"
    assert cost == pytest.approx(0.012)
    assert "CHƯA hoàn chỉnh" not in text


def test_cap_above_total_spend_never_fires():
    # A cap set generously is indistinguishable from no cap — the positive control for
    # the two cases above, so neither can pass in a world where the loop always stops.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.004),
        _text_turn("Giá là 65.000đ", cost=0.004),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=10.0)

    assert llm.rounds == 2
    assert text == "Giá là 65.000đ"


def test_a_model_that_stops_on_its_own_over_budget_still_admits_the_overspend():
    """The model ends the loop itself, having already blown the ceiling.

    Every other case here scripts a model that keeps asking for tools, so the ceiling is
    always consulted at the top of a round that actually happens. This is the shape a paid
    live run produced instead: three tool rounds took the spend to ~3x the cap, then the
    model returned a final answer with no tool calls, and the loop took its natural exit —
    the branch that never consults `over_cost_cap` at all.

    The result was a step marked `done`, carrying no gap note, having spent 15x its cap.
    That is the failure the guard exists to prevent, and it read as complete work: nothing
    downstream — `self_check`, the reviewer, the CEO — had any way to see the step had blown
    its budget, because the one signal that says so was never attached.

    The cap cannot un-spend what the final turn cost. What it must still do is tell the
    truth about it, so the note is the assertion, not the round count.
    """
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.004),
        _text_turn("Đã tra được giá 65.000đ", cost=0.004),
    ])
    text, cost = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.005)

    assert llm.rounds == 2, "the model's own final turn should still be paid for"
    assert llm.synthesis_calls == 0, "a natural exit already has text; no salvage needed"
    assert "CHƯA hoàn chỉnh" in text, (
        "the loop ended over its ceiling but the result claims to be complete work. "
        f"spent={cost} cap=0.005 text={text!r}"
    )
    assert "Đã tra được giá 65.000đ" in text, "the work already paid for must be kept"


def test_a_model_stopping_on_its_own_within_budget_is_untouched():
    # The control for the case above: same natural exit, but the spend never reaches the
    # ceiling, so the text must come back exactly as the model wrote it. Without this a
    # fix that stamped the note on every natural exit would look correct.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.001),
        _text_turn("Giá là 65.000đ", cost=0.001),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=6, cost_cap_usd=0.05)

    assert text == "Giá là 65.000đ"
    assert "CHƯA hoàn chỉnh" not in text


def test_round_budget_exhaustion_still_synthesizes_when_uncapped():
    # The pre-existing salvage path must survive the new branch: rounds run out (not cost),
    # so the tool-free synthesis turn still happens.
    llm = _FakeLlm([
        _tool_turn(_tc("web_search", '{"query": "a"}'), cost=0.001),
        _tool_turn(_tc("web_search", '{"query": "b"}'), cost=0.001),
    ])
    text, _ = _run(llm, {"web.search": _search}, max_steps=2, cost_cap_usd=None)

    assert llm.synthesis_calls == 1
    assert text == "tổng hợp cuối"


# --- config → runtime wiring ------------------------------------------------------------


def test_caps_carry_the_configured_cost_cap():
    from my_crew.runtime_backends.config import parse_agent_runtime_config

    cfg = parse_agent_runtime_config({"kind": "create_agent", "cost_cap_usd": 0.25})
    assert cfg.caps().cost_cap_usd == 0.25


def test_runtime_threads_the_cap_from_profile_into_the_loop(monkeypatch):
    """The seam that was missing until now: profile → RuntimeCaps → run_thin_loop."""
    from my_crew.runtime_backends import tool_calling_runtime as tcr
    from my_crew.runtime_backends.config import parse_agent_runtime_config

    seen: dict = {}

    def _fake_run_thin_loop(**kwargs):
        seen.update(kwargs)
        return ("ok", 0.0)

    import my_crew.runtime_backends.thin_tool_loop as ttl

    monkeypatch.setattr(ttl, "run_thin_loop", _fake_run_thin_loop)
    monkeypatch.setattr(
        "my_crew.runtime_backends.read_only_toolset.build_read_toolset",
        lambda *a, **kw: {},
    )

    cfg = parse_agent_runtime_config({"kind": "create_agent", "cost_cap_usd": 0.33})
    runtime = tcr.ToolCallingRuntime()
    work = runtime._make_work_override(
        _settings(), _Ctx(), None, 16, None, False, False, False, "thin",
        cfg.caps().cost_cap_usd,
    )
    work("Tìm giá", "", None)

    assert seen["cost_cap_usd"] == 0.33
