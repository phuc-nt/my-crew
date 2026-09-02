"""A step whose self-check never passes must NOT be recorded as `done`.

Before this, `deliver` returned `status="done"` even when `self_check_failed` was True —
the whole rework budget could be exhausted, the result still failing its own acceptance
criteria, and the DAG would treat it as a satisfied dependency: the next step read the
bad output as input, and once every step "finished" the task aggregated and delivered an
unacceptable result to the CEO.

The new terminal is `needs_decision`: the step DID produce an artifact (unlike `failed`,
where there is nothing to read), it is just not acceptable, so it stays blocking until
the coordinator reads the artifact and decides. Load-bearing here:

- The artifact still exists and cost is still recorded — the coordinator's decision is
  worthless without something to read.
- A dependent step does NOT dispatch off a `needs_decision` dep.
- A task with a `needs_decision` step does NOT auto-aggregate to the CEO...
- ...and is NOT a `_dead_end_result` dead-end either (that path is for `failed`/
  `timeout`, where no artifact exists — stalling here would throw away a recoverable
  result before anyone read it).
- The pass path is untouched: a step that meets acceptance is still plain `done`.
- The lease guard applies exactly like `mark_done`'s: a stale `attempt_id` is a no-op.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.agent.coordinator_graph import _dead_end_result, ready_pending_steps
from my_crew.agent.team_task_graph import TeamTaskDeps, build_team_task_graph
from my_crew.runtime.team_task_store import TeamTaskStore

# --- step graph: the deliver-node verdict -----------------------------------------


def _graph_deps(*, verdicts: list[tuple[bool, list[str], float]]):
    """One `run_self_check` verdict per call, last entry repeating — same shape as
    `test_team_task_graph_selfcheck.py`'s helper."""
    seen: dict[str, object] = {"deliver_args": None}
    n = {"i": 0}

    def run_self_check(result_text, acceptance):
        i = n["i"]
        n["i"] = i + 1
        return verdicts[min(i, len(verdicts) - 1)]

    def deliver_step(text, version, self_check_failed):
        seen["deliver_args"] = (text, version, self_check_failed)
        return True, f"[ket qua] {text}"

    deps = TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda title, handoff, hook: ("ban nhap", 0.01),
        run_self_check=run_self_check,
        run_rework=lambda title, prior, failures: (f"{prior}+sua", 0.02),
        deliver_step=deliver_step,
    )
    return deps, seen


def test_exhausted_rework_budget_delivers_needs_decision_not_done():
    """Self-check fails every time: the graph still delivers (never loops forever) but
    the status it reports back to the runner is `needs_decision`, not `done`."""
    deps, seen = _graph_deps(verdicts=[(False, ["thieu phan A"], 0.3)])
    graph = build_team_task_graph(deps=deps)

    result = graph.invoke({"step_title": "soan", "acceptance": "phai co phan A"})

    assert result["status"] == "needs_decision"
    assert result["delivered"] is True  # the artifact IS written — that is the point
    assert seen["deliver_args"][2] is True  # deliver saw self_check_failed


def test_passing_self_check_still_delivers_done():
    """The accepted path is unchanged."""
    deps, seen = _graph_deps(verdicts=[(True, [], 0.9)])
    graph = build_team_task_graph(deps=deps)

    result = graph.invoke({"step_title": "soan", "acceptance": "phai co phan A"})

    assert result["status"] == "done"
    assert seen["deliver_args"][2] is False


# --- store: the terminal write ------------------------------------------------------


def _planned_store(tmp_path) -> TeamTaskStore:
    """Two steps, s2 depending on s1 — the minimum shape that can show a dependent
    refusing to dispatch."""
    from my_crew.agent.task_decomposition import decomposition_content_hash

    steps = [
        {"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "viet bao cao", "assigned_to": "agent-b", "deps": ["s1"]},
    ]
    plan_hash = decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s["deps"]), needs_shell=False,
        )
        for s in steps
    ]))
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=plan_hash)
    return store


def test_mark_needs_decision_keeps_artifact_ref_and_cost(tmp_path):
    """`outcome_ref` + `cost_usd` must survive — the coordinator reads the artifact to
    decide, and the money was really spent whether or not the result was acceptable."""
    store = _planned_store(tmp_path)
    attempt = store.reserve_step("t1", "s1")

    updated = store.mark_needs_decision(
        "t1", "s1", outcome_ref="team-tasks/t1/step-1.json",
        cost_usd=0.07, attempt_id=attempt,
    )

    assert updated is True
    step = store.get_step("t1", "s1")
    assert step.status == "needs_decision"
    assert step.outcome_ref == "team-tasks/t1/step-1.json"
    assert step.cost_usd == 0.07


def test_mark_needs_decision_with_stale_attempt_is_a_no_op(tmp_path):
    """Same lease guard as `mark_done`: a superseded attempt must not overwrite the
    status the current lease-holder is working toward."""
    store = _planned_store(tmp_path)
    stale = store.reserve_step("t1", "s1")
    fresh = store.reserve_step("t1", "s1")
    assert stale != fresh

    updated = store.mark_needs_decision("t1", "s1", attempt_id=stale)

    assert updated is False
    step = store.get_step("t1", "s1")
    assert step.status == "running"


# --- DAG gating ---------------------------------------------------------------------


def test_dependent_step_does_not_dispatch_off_a_needs_decision_dep(tmp_path):
    """s2 depends on s1. With s1 `needs_decision`, s2 must stay unready — an
    unacceptable result must never become another step's input."""
    store = _planned_store(tmp_path)
    attempt = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", outcome_ref="ref.json", attempt_id=attempt)

    assert [s.step_id for s in ready_pending_steps(store.get("t1"))] == []


def test_task_with_a_needs_decision_step_neither_aggregates_nor_dead_ends(tmp_path):
    """Two guards at once. `all(status == "done")` must be False so the task does not
    aggregate an unacceptable result to the CEO — and `_dead_end_result` must return
    None so the task is not stalled either: unlike `failed`/`timeout` there IS an
    artifact here, and stalling would discard it before the coordinator read it."""
    store = _planned_store(tmp_path)
    a1 = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", outcome_ref="ref.json", attempt_id=a1)
    task = store.get("t1")

    assert not all(s.status == "done" for s in task.steps)
    assert _dead_end_result(SimpleNamespace(), task) is None


# --- a capped draft is delivered for a decision, never reworked ----------------------


def test_a_cost_capped_draft_that_fails_self_check_is_not_reworked(monkeypatch):
    """The spend ceiling, not the worker, cut this draft short — a rework would run under
    the same ceiling and (measured live) overwrite the capped text with a bare refusal,
    losing the cap note the CEO needed to read. So the first failing check is terminal:
    no rework call, the capped text is what deliver hands over, status needs_decision."""
    from my_crew.runtime_backends.loop_cost_guard import with_cost_cap_gap_note

    capped = with_cost_cap_gap_note("Tôi sẽ tra cứu lịch sử.", [0.004], 0.0005, 1)
    reworks: list[str] = []
    seen: dict[str, object] = {}

    def run_rework(title, prior, failures):
        reworks.append(prior)
        return "bản sửa không có ghi chú trần", 0.02

    def deliver_step(text, version, self_check_failed):
        seen["deliver_args"] = (text, version, self_check_failed)
        return True, text

    deps = TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda title, handoff, hook: (capped, 0.004),
        run_self_check=lambda result_text, acceptance: (False, ["chỉ có ý định"], 0.9),
        run_rework=run_rework,
        deliver_step=deliver_step,
    )
    graph = build_team_task_graph(deps=deps)

    result = graph.invoke({"step_title": "tra lịch sử", "acceptance": "nêu một mạch việc"})

    assert reworks == []
    assert result["status"] == "needs_decision"
    assert seen["deliver_args"][0] == capped  # the note survives to the artifact
    assert seen["deliver_args"][2] is True


def test_an_uncapped_failing_draft_still_gets_its_rework_round():
    """Boundary of the rule above: without the cap note the rework budget applies as
    before — one rework, then needs_decision."""
    deps, seen = _graph_deps(verdicts=[(False, ["thieu phan A"], 0.3)])
    graph = build_team_task_graph(deps=deps)

    result = graph.invoke({"step_title": "soan", "acceptance": "phai co phan A"})

    assert result["status"] == "needs_decision"
    assert seen["deliver_args"][0].endswith("+sua")  # the rework ran once
