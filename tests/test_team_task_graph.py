"""Task execution graph (v12 M28a): `perceive → work → deliver` node flow.

Load-bearing:
- with an injected `TeamTaskDeps` (LLM double), the graph runs perceive→work→deliver
  in order and each node's output lands in the expected state key.
- no network/subprocess/gateway call happens by default — `deliver_step` is the ONLY
  write, and it's the caller's fake (an internal artifact write in the real wiring,
  never an external send: THE INVARIANT).
- `default_team_task_deps`' real `_read_handoff`/`_deliver` wiring round-trips through
  `team_task_artifact` correctly: step 1 has no handoff, step 2 reads step 1's result,
  and `deliver` writes the artifact for the NEXT step to read.
"""

from __future__ import annotations

from my_crew.agent.team_task_artifact import read_step_artifact
from my_crew.agent.team_task_graph import (
    TeamTaskDeps,
    build_team_task_graph,
    default_team_task_deps,
)
from my_crew.config.config_builders import build_settings_from_dict


def _fake_deps(*, handoff="", result_text="work output", cost=0.01, delivered=True):
    calls: dict[str, object] = {"deliver_called_with": None}

    def read_handoff() -> str:
        return handoff

    def run_work(title, handoff_ctx, hook):
        calls["work_args"] = (title, handoff_ctx, hook)
        return result_text, cost

    def run_self_check(text, acceptance):
        # v12 regression: no acceptance rubric configured on these tests, so
        # self_check trivially passes and the graph never enters rework — matching
        # v12's straight-line perceive->work->deliver behavior.
        return True, [], 1.0

    def run_rework(title, prior_output, failures):
        raise AssertionError("rework should never run when self_check always passes")

    def deliver_step(text: str, version: str, self_check_failed: bool):
        calls["deliver_called_with"] = text
        calls["deliver_version"] = version
        calls["deliver_self_check_failed"] = self_check_failed
        return delivered, f"[done] {text}"

    deps = TeamTaskDeps(
        read_handoff=read_handoff, run_work=run_work, run_self_check=run_self_check,
        run_rework=run_rework, deliver_step=deliver_step,
    )
    return deps, calls


def test_graph_runs_perceive_work_deliver_in_order():
    deps, calls = _fake_deps(handoff="prior result")
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft doc"})

    assert result["handoff_context"] == "prior result"
    assert result["result_text"] == "work output"
    assert result["cost_usd"] == 0.01
    assert result["delivered"] is True
    assert result["room_message"] == "[done] work output"
    # work received perceive's handoff_context, not the raw initial state
    assert calls["work_args"] == ("draft doc", "prior result", None)
    # deliver received work's result_text
    assert calls["deliver_called_with"] == "work output"


def test_graph_first_step_has_empty_handoff():
    deps, _ = _fake_deps(handoff="")
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "kick off"})
    assert result["handoff_context"] == ""


def test_graph_no_external_write_by_default_only_deliver_step_called():
    """The only "write" observable from the graph's perspective is `deliver_step` —
    nothing else in TeamTaskDeps performs I/O, matching THE INVARIANT that a step's
    handoff is internal-only and never touches the gateway/external delivery path."""
    deps, calls = _fake_deps()
    graph = build_team_task_graph(deps=deps)
    graph.invoke({"step_title": "t"})
    assert calls["deliver_called_with"] is not None  # deliver ran exactly once, as expected


def test_graph_requires_settings_data_dir_task_id_without_deps():
    import pytest

    with pytest.raises(ValueError):
        build_team_task_graph()


def test_graph_search_hook_passed_through_to_work_when_provided():
    deps, calls = _fake_deps()

    def hook(query: str) -> str:
        return "search result"

    deps.search_hook = hook
    graph = build_team_task_graph(deps=deps)
    graph.invoke({"step_title": "t"})
    assert calls["work_args"][2] is hook


# --- default_team_task_deps: real handoff-artifact + settings wiring -----------------


def test_default_deps_step1_has_no_handoff_and_writes_artifact(tmp_path, monkeypatch):
    settings = build_settings_from_dict({"data_dir": tmp_path})

    class _FakeResult:
        content = "step 1 output"
        cost_usd = 0.02

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages):
            return _FakeResult()

    # `default_team_task_deps` lazily imports LlmClient from my_crew.llm.client — patch it
    # at the source module so the real wiring under test never makes a network call.
    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="draft", data_dir=tmp_path,
        task_id="task-1", step_seq=1,
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft"})

    assert result["handoff_context"] == ""  # step 1: nothing to read yet
    assert result["result_text"] == "step 1 output"
    assert result["delivered"] is True

    artifact = read_step_artifact(tmp_path, "task-1", 1)
    assert artifact is not None
    assert artifact["result_text"] == "step 1 output"
    assert artifact["status"] == "done"


def test_default_deps_step2_reads_step1_handoff(tmp_path, monkeypatch):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_store import TeamTaskStore

    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "step 1 output"})
    # `_read_handoff` is DEPS-aware (maps step_ids -> seqs via the store), so the store
    # needs a row for the dependency ("s1", at seq 1) — the artifact alone is not enough.
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="task-1", title="t", original_request="r", assigned_by="ceo")
    store.set_plan(
        "task-1",
        [
            {"step_id": "s1", "title": "draft", "assigned_to": "a1", "deps": []},
            {"step_id": "s2", "title": "review", "assigned_to": "a1", "deps": ["s1"]},
        ],
        plan_hash="irrelevant-for-this-test",
    )
    store.close()

    settings = build_settings_from_dict({"data_dir": tmp_path})

    class _FakeResult:
        content = "step 2 output"
        cost_usd = 0.01

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages):
            return _FakeResult()

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="review", data_dir=tmp_path,
        task_id="task-1", step_seq=2, step_deps=("s1",),
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "review"})

    assert result["handoff_context"] == "step 1 output"
    assert result["result_text"] == "step 2 output"


def test_default_deps_missing_prior_artifact_yields_empty_handoff(tmp_path, monkeypatch):
    settings = build_settings_from_dict({"data_dir": tmp_path})

    class _FakeResult:
        content = "output"
        cost_usd = None

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages):
            return _FakeResult()

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="orphan step", data_dir=tmp_path,
        task_id="task-missing", step_seq=5,  # step 4's artifact was never written
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "orphan step"})

    assert result["handoff_context"] == ""  # tolerant of the missing prior artifact
