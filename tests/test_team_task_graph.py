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

from dataclasses import replace
from types import SimpleNamespace

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

        def complete(self, _messages, **_kw):
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

        def complete(self, _messages, **_kw):
            return _FakeResult()

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="review", data_dir=tmp_path,
        task_id="task-1", step_seq=2, step_deps=("s1",),
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "review"})

    # The CEO's original brief now PREFIXES every step's handoff (subject grounding —
    # a generic step title left workers guessing which entities the task was about);
    # the dep artifact itself must still ride in full after it.
    assert result["handoff_context"].endswith("step 1 output")
    assert result["result_text"] == "step 2 output"


def test_default_deps_missing_prior_artifact_yields_empty_handoff(tmp_path, monkeypatch):
    settings = build_settings_from_dict({"data_dir": tmp_path})

    class _FakeResult:
        content = "output"
        cost_usd = None

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages, **_kw):
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


def test_failed_self_check_persists_its_reasons_in_the_artifact(tmp_path, monkeypatch):
    """`self_check_failed: true` with no WHY forced replaying the grader by hand to
    diagnose a failed step (done live, task 5eea1ae1c969). The accumulated failure
    reasons must ride in the artifact the coordinator and CEO read."""
    settings = build_settings_from_dict({"data_dir": tmp_path})

    class _FakeResult:
        content = "kết quả thiếu link"
        cost_usd = 0.01

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages, **_kw):
            return _FakeResult()

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="draft", data_dir=tmp_path,
        task_id="task-9", step_seq=1,
    )
    # Deterministic failing grader + no-op rework: the graph exhausts rework and
    # delivers with self_check_failed=True.
    deps = replace(
        deps,
        run_self_check=lambda _t, _a, _h="": (False, ["thiếu link nguồn (0 chuỗi http)"], 0.9),
        run_rework=lambda *_a, **_k: ("kết quả thiếu link", None),
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "- có link nguồn"})

    assert result["status"] == "needs_decision"
    artifact = read_step_artifact(tmp_path, "task-9", 1)
    assert artifact["self_check_failed"] is True
    assert any("thiếu link" in r for r in artifact["self_check_failures"])


def test_rework_looks_up_the_data_its_check_says_is_missing(tmp_path, monkeypatch):
    """The failure this closes: a self-check demanding data the attempt never fetched
    left `rework` with no way to get it, so the model either invented the figure or
    blanked the rows it could not defend. Live, it blanked them — a sourced draft
    became "Không có dữ liệu" and the task stalled (tasks f62348234949, 7ebfc0374c5c).
    The rework node now runs the SAME search hook `work` already holds, keyed on the
    failures, which name exactly what is missing."""
    settings = build_settings_from_dict({"data_dir": tmp_path})
    replies = ["bản nháp thiếu giá", "bản nháp đã có giá"]
    seen: list[list[dict[str, str]]] = []
    checks = {"n": 0}

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **kw):
            seen.append(list(messages))
            if kw.get("role") == "review":
                checks["n"] += 1
                # Fail the first check (which drives one rework), then pass.
                content = (
                    '{"passed": true, "failures": [], "confidence": 0.9}'
                    if checks["n"] > 1
                    else '{"passed": false, "failures": ["thiếu giá gói cá nhân"],'
                         ' "confidence": 0.4}'
                )
                return SimpleNamespace(content=content, cost_usd=0.0)
            return SimpleNamespace(content=replies.pop(0) if replies else "", cost_usd=0.01)

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    queries: list[str] = []

    def hook(query: str) -> str:
        queries.append(query)
        return "Spotify 59.000đ/tháng — spotify.com, đọc 2026-08-17"

    deps = default_team_task_deps(
        settings=settings, step_title="Bảng giá Spotify", data_dir=tmp_path,
        task_id="task-rw", step_seq=1, search_hook=hook,
    )
    graph = build_team_task_graph(deps=deps)
    graph.invoke({"step_title": "Bảng giá Spotify", "acceptance": "Có giá gói cá nhân"})

    assert len(queries) == 2, "work searched once, rework searched again for the gap"
    assert "giá gói cá nhân" in queries[1], "the rework query is built from the FAILURES"
    prompts = ["\n".join(m.get("content", "") for m in call) for call in seen]
    assert any("spotify.com" in p for p in prompts), \
        "the found data must reach the rework prompt"


def test_rework_without_a_search_hook_still_reworks(tmp_path, monkeypatch):
    """A tool-less step (review row, needs_web=False work step) has no hook at all —
    the rework path must stay exactly as it was for those, not raise."""
    settings = build_settings_from_dict({"data_dir": tmp_path})
    calls = {"n": 0}

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages, **kw):
            if kw.get("role") == "review":
                calls["n"] += 1
                content = '{"passed": true, "failures": [], "confidence": 0.9}' \
                    if calls["n"] > 1 else \
                    '{"passed": false, "failures": ["thiếu A"], "confidence": 0.4}'
                return SimpleNamespace(content=content, cost_usd=0.0)
            return SimpleNamespace(content="nội dung", cost_usd=0.01)

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    deps = default_team_task_deps(
        settings=settings, step_title="viết", data_dir=tmp_path,
        task_id="task-nohook", step_seq=1, search_hook=None,
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "viết", "acceptance": "phải có A"})

    assert result["rework_count"] == 1
    assert result["self_check_failed"] is False
