"""The `work` node's pre-work consult loop (M33, `team_task_graph.py`).

Load-bearing:
- `deps.ask_colleague is None` (default) -> byte-identical pre-M33 behavior, no
  propose call, no consult fields touched (v12/P1 regression).
- happy path: `propose_consults` returns targets, `ask_colleague` answers each,
  `consult_count`/`consult_log` accumulate, consult cost folds into `cost_usd`.
- the ≤MAX_CONSULTS budget caps how many `ask_colleague` calls happen even if
  `propose_consults` returns more than the remaining budget.
- a failing `propose_consults`/`ask_colleague` degrades (work still completes,
  no exception escapes the node).
- `default_team_task_deps` wires consult OFF (both hooks None) when `self_id` is
  blank — the safe default for any caller that hasn't been updated to pass it.
"""

from __future__ import annotations

from my_crew.agent.team_task_graph import MAX_CONSULTS, TeamTaskDeps, build_team_task_graph
from my_crew.config.config_builders import build_settings_from_dict


def _base_deps(**overrides):
    def read_handoff() -> str:
        return ""

    def run_work(title, handoff, hook):
        return f"work[{handoff}]", 0.01

    def run_self_check(text, acceptance):
        return True, [], 1.0

    def run_rework(title, prior_output, failures):
        raise AssertionError("rework should not run in these tests")

    def deliver_step(text, version, self_check_failed):
        return True, f"[done] {text}"

    kwargs = dict(
        read_handoff=read_handoff, run_work=run_work, run_self_check=run_self_check,
        run_rework=run_rework, deliver_step=deliver_step,
    )
    kwargs.update(overrides)
    return TeamTaskDeps(**kwargs)


def test_consult_off_by_default_no_propose_call_no_consult_fields_touched():
    """v12/P1 regression: a bare TeamTaskDeps() (ask_colleague=None) behaves exactly
    like pre-M33 — work runs once, no consult_count/consult_log side effects beyond
    the state schema's own defaults."""
    deps = _base_deps()
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result["result_text"] == "work[]"
    assert result.get("consult_count", 0) == 0
    assert result.get("consult_log", []) == []


def test_consult_happy_path_accumulates_count_log_and_cost():
    asked = []

    def propose_consults(title, handoff):
        return [("colleague-1", "Ưu tiên gì?")]

    def ask_colleague(agent_id, question):
        asked.append((agent_id, question))
        return "Nên làm A trước.", 0.02

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert asked == [("colleague-1", "Ưu tiên gì?")]
    assert result["consult_count"] == 1
    assert len(result["consult_log"]) == 1
    assert "colleague-1" in result["consult_log"][0]
    # work's own cost (0.01) + consult's cost (0.02)
    assert result["cost_usd"] == 0.03
    # the consult answer is folded into what `run_work` sees as handoff context
    assert "Nên làm A trước." in result["result_text"]


def test_consult_budget_caps_at_max_consults_even_if_more_proposed():
    call_count = {"n": 0}

    def propose_consults(title, handoff):
        # propose more than MAX_CONSULTS allows
        return [(f"colleague-{i}", f"q{i}") for i in range(MAX_CONSULTS + 3)]

    def ask_colleague(agent_id, question):
        call_count["n"] += 1
        return f"answer for {agent_id}", 0.01

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert call_count["n"] == MAX_CONSULTS
    assert result["consult_count"] == MAX_CONSULTS


def test_consult_respects_existing_consult_count_from_state():
    """A rework re-entry into `work` is not a real production path today (work runs
    once per attempt), but the counter must still cap correctly if state already
    carries a prior count — defensive budget check, not "count starts at 0"."""

    def propose_consults(title, handoff):
        return [("colleague-1", "q1"), ("colleague-2", "q2")]

    calls = []

    def ask_colleague(agent_id, question):
        calls.append(agent_id)
        return "a", 0.01

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t", "consult_count": MAX_CONSULTS - 1})

    assert len(calls) == 1  # only 1 slot left in the budget
    assert result["consult_count"] == MAX_CONSULTS


def test_consult_propose_failure_degrades_work_still_completes():
    def propose_consults(title, handoff):
        raise RuntimeError("propose boom")

    def ask_colleague(agent_id, question):
        raise AssertionError("ask_colleague should never run if propose failed")

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result["result_text"] == "work[]"
    assert result.get("consult_count", 0) == 0


def test_consult_ask_colleague_failure_degrades_and_skips_that_target():
    def propose_consults(title, handoff):
        return [("colleague-1", "q1"), ("colleague-2", "q2")]

    def ask_colleague(agent_id, question):
        if agent_id == "colleague-1":
            raise RuntimeError("boom")
        return "answer 2", 0.01

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    # colleague-1 failed and is skipped (not counted); colleague-2 succeeds and counts
    assert result["consult_count"] == 1
    assert "answer 2" in result["result_text"]


def test_consult_empty_answer_not_folded_into_handoff_or_counted_in_log():
    """`ask_colleague` returning `("", 0.0)` is the guard-skip / soft-degrade shape —
    it still consumes budget (a real call happened) but produces no visible text."""

    def propose_consults(title, handoff):
        return [("colleague-1", "q1")]

    def ask_colleague(agent_id, question):
        return "", 0.0

    deps = _base_deps(ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result["consult_count"] == 1
    assert result["consult_log"] == []
    assert result["result_text"] == "work[]"  # nothing folded into handoff


def test_default_team_task_deps_wires_consult_off_when_self_id_blank(tmp_path):
    from my_crew.agent.team_task_graph import default_team_task_deps

    settings = build_settings_from_dict({"data_dir": tmp_path})
    deps = default_team_task_deps(
        settings=settings, step_title="t", data_dir=tmp_path, task_id="task-1", step_seq=1,
    )
    assert deps.ask_colleague is None
    assert deps.propose_consults is None
    assert deps.set_attempt_id is None


def test_default_team_task_deps_wires_consult_on_when_self_id_given(tmp_path):
    from my_crew.agent.team_task_graph import default_team_task_deps

    settings = build_settings_from_dict({"data_dir": tmp_path})
    deps = default_team_task_deps(
        settings=settings, step_title="t", data_dir=tmp_path, task_id="task-1", step_seq=1,
        self_id="agent-a",
    )
    assert deps.ask_colleague is not None
    assert deps.propose_consults is not None
    assert deps.set_attempt_id is not None
