"""The step graph's self-check / rework loop (`team_task_graph.py`'s
`self_check`/`rework` nodes + `route_after_check`).

Load-bearing:
- fail-then-pass: `work` runs exactly once, `rework` runs exactly once, `deliver`
  receives `self_check_failed=False`.
- fail-fail (budget exhausted at `max_rework=2`): `rework` runs exactly twice,
  `rework_count==2` at delivery, `deliver` receives `self_check_failed=True` — a
  stuck self-check must still deliver (R5: never loop forever), just flagged.
- pass-immediately: `deliver` runs with no `rework` call at all.
- No checkpoint-resume test: this graph compiles with `checkpointer=None` by design
  (Decision B) — a crash mid-attempt is not resumable, the next tick spawns a FRESH
  attempt_id and re-runs from `perceive`, so there is no phantom-resume path to test.
"""

from __future__ import annotations

from my_crew.agent.team_task_graph import TeamTaskDeps, build_team_task_graph


def _make_deps(*, verdicts: list[tuple[bool, list[str], float]]):
    """`verdicts` is consumed in order, one per `run_self_check` call — the Nth call
    (0-indexed) returns `verdicts[min(n, len(verdicts) - 1)]` so a test can express
    "fail, fail, then keep failing" with a short list."""
    calls: dict[str, object] = {"work_calls": 0, "rework_calls": 0, "deliver_args": None}
    check_calls = {"n": 0}

    def read_handoff() -> str:
        return ""

    def run_work(title, handoff, hook):
        calls["work_calls"] = int(calls["work_calls"]) + 1
        return "draft v0", 0.01

    def run_self_check(result_text, acceptance):
        n = check_calls["n"]
        check_calls["n"] = n + 1
        idx = min(n, len(verdicts) - 1)
        return verdicts[idx]

    def run_rework(title, prior_output, failures):
        calls["rework_calls"] = int(calls["rework_calls"]) + 1
        return f"{prior_output}+fix{calls['rework_calls']}", 0.02

    def deliver_step(text, version, self_check_failed):
        calls["deliver_args"] = (text, version, self_check_failed)
        return True, f"[done] {text}"

    deps = TeamTaskDeps(
        read_handoff=read_handoff, run_work=run_work, run_self_check=run_self_check,
        run_rework=run_rework, deliver_step=deliver_step,
    )
    return deps, calls


def test_fail_then_pass_reworks_once_and_delivers_not_failed():
    deps, calls = _make_deps(verdicts=[(False, ["thiếu phần A"], 0.4), (True, [], 0.9)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 1
    assert result["self_check_failed"] is False
    assert result["rework_count"] == 1
    assert calls["deliver_args"][2] is False  # self_check_failed passed to deliver_step
    assert calls["deliver_args"][0] == "draft v0+fix1"


def test_fail_fail_exhausts_rework_budget_and_delivers_flagged():
    deps, calls = _make_deps(verdicts=[(False, ["vẫn thiếu A"], 0.3)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 2  # capped at max_rework=2, never loops forever
    assert result["rework_count"] == 2
    assert result["self_check_failed"] is True
    assert calls["deliver_args"][2] is True
    # deliver still runs with the LATEST (still-failing) result, not a blank/aborted one
    assert calls["deliver_args"][0] == "draft v0+fix1+fix2"


def test_pass_immediately_never_reworks():
    deps, calls = _make_deps(verdicts=[(True, [], 1.0)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 0
    assert result["self_check_failed"] is False
    assert result.get("rework_count", 0) == 0
    assert calls["deliver_args"][0] == "draft v0"


def test_blank_acceptance_skips_check_semantics_but_graph_still_uses_default_deps_open_gate():
    """Not `default_team_task_deps` here (fake deps), but the SHAPE of "acceptance
    blank -> trivially passes" is asserted at the real wiring level in
    `test_team_task_graph.py`'s existing regression coverage; this test only pins
    that a fake `run_self_check` returning passed=True with no acceptance text set
    behaves identically to the "criteria configured and passed" path — no special
    casing inside the graph itself for blank acceptance (that logic lives in
    `default_team_task_deps._run_self_check`, not in the graph's routing)."""
    deps, calls = _make_deps(verdicts=[(True, [], 1.0)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": ""})

    assert calls["rework_calls"] == 0
    assert result["self_check_failed"] is False
