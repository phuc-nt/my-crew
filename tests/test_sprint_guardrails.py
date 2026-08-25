"""v77 phase 3: sprint mode inside the EXISTING guardrails — band, budget, audit.

The claim this file defends is a negative one: sprint mode adds no safety mechanism
of its own and relaxes none. A sprint task is a degenerate team task, so the band
review gate, the per-task cost cap, and the audit chain must reach it through exactly
the paths every other step uses. Each test below pins one of those paths, because the
failure mode is silent — a sprint step that quietly skips a gate looks identical to
one that passed it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from my_crew.runtime.band_store import (
    BAND_NORMAL,
    BAND_SUPERVISED,
    BAND_TRUSTED,
    BandStore,
    band_for,
)


def _patch_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)


def _sprint_step(assigned_to="agent-a", needs_review=False, external_write=False):
    return SimpleNamespace(
        step_id="sprint", assigned_to=assigned_to, needs_review=needs_review,
        deps=(), external_write=external_write, step_type="sprint",
        split_proposal_json="", status="done",
    )


# --- band × sprint: the review gate reaches a sprint step ----------------------------


def test_supervised_forces_a_review_on_a_sprint_step(monkeypatch, tmp_path):
    """The review gate is the band's ONLY lever. A sprint step is content, so a
    supervised author must still get their one final review before deliver."""
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("agent-a", BAND_SUPERVISED, reason="t", changed_by="ceo")
    store.close()
    step = _sprint_step(needs_review=False)
    assert effective_needs_review(SimpleNamespace(steps=[step]), step) is True


def test_sprint_review_flag_survives_every_band_including_trusted(monkeypatch, tmp_path):
    """Sprint là đường zero-eyes duy nhất còn lại (một bước, một tiến trình, bản giao
    đi thẳng đến CEO), nên cờ review của nó không band nào được miễn — kể cả trusted,
    band vốn được waive mọi review nội bộ trên bước `work`."""
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    _patch_data_dir(monkeypatch, tmp_path)
    step = _sprint_step(needs_review=True)
    task = SimpleNamespace(steps=[step])
    assert band_for("agent-a") == BAND_NORMAL
    assert effective_needs_review(task, step) is True

    store = BandStore()
    store.set("agent-a", BAND_TRUSTED, reason="t", changed_by="ceo")
    store.close()
    assert effective_needs_review(task, step) is True

    # Đối chứng: cùng band trusted, một bước `work` nội bộ vẫn được waive như cũ —
    # ngoại lệ chỉ khoét đúng cho step_type == "sprint".
    work = SimpleNamespace(
        step_id="w1", assigned_to="agent-a", needs_review=True, deps=(),
        external_write=False, step_type="work",
    )
    assert effective_needs_review(SimpleNamespace(steps=[work]), work) is False


def test_sprint_plan_builder_always_sets_the_review_flag():
    """`_build_sprint_task` là nơi duy nhất sinh bước sprint — cờ review phải bật từ
    nguồn, không dựa vào ai nhớ bật nó ở downstream."""
    from types import SimpleNamespace as NS

    from my_crew.agent.ops_assign_team_task import _build_sprint_task

    plan = NS(goal="khảo sát 5 dịch vụ", assigned_to="agent-a",
              acceptance="đủ 5 dịch vụ", needs_web=True)
    task = _build_sprint_task(plan, pic_requested="")
    assert task.steps[0].needs_review is True
    assert task.steps[0].external_write is False
    assert task.steps[0].needs_shell is False


def test_the_review_gate_is_reached_via_is_content_step_not_a_work_literal():
    """`maybe_insert_review` guards on `is_content_step`. A `== "work"` literal there
    would swallow the supervised band's only lever for a whole mode of work."""
    from my_crew.agent.coordinator_nodes import review_insert
    from my_crew.runtime.team_task_steps import CONTENT_STEP_TYPES, is_content_step

    assert "sprint" in CONTENT_STEP_TYPES
    assert is_content_step(_sprint_step()) is True
    src = Path("my_crew/agent/coordinator_nodes/review_insert.py").read_text()
    assert "is_content_step(done_step)" in src
    assert hasattr(review_insert, "effective_needs_review")


def test_the_sprint_runner_never_reads_a_band():
    """Autonomy invariant, extended to v77: band_for has exactly ONE runtime consumer
    (the review gate). The sprint work loop must not become a second one."""
    assert "band_for" not in Path("my_crew/runtime/sprint_runner.py").read_text()


# --- external write: fail-closed at the router, hardcoded off at the step ------------


def test_an_external_write_brief_never_reaches_sprint_mode():
    """A sprint step hardcodes `external_write=False`, and `effective_needs_review`
    keeps a review mandatory for external writes at EVERY band. So an external-write
    brief reaching sprint mode would lose the one review it is guaranteed — the router
    refuses it first, on both the heuristic path and the CEO's forced-prefix path."""
    from my_crew.agent.sprint_intake import classify_brief, sprint_refusal

    brief = "gửi email cho khách về bảng giá mới"
    assert sprint_refusal(brief)
    assert classify_brief(brief)[0] is False


def test_a_shell_brief_never_reaches_sprint_mode():
    """`needs_shell=True` routes to the sandbox tier BEFORE the sprint pin in
    `resolve_step_runtime`, which would silently discard `work_override` and hand the
    model back the react loop. Keeping shell briefs out of sprint mode is what makes
    the hardcoded `needs_shell=False` on the step safe."""
    from my_crew.agent.sprint_intake import classify_brief, sprint_refusal

    brief = "chạy script dọn dữ liệu rồi tổng hợp lại"
    assert sprint_refusal(brief)
    assert classify_brief(brief)[0] is False


# --- budget: the cap gates the SPAWN, and a sprint step is one spawn -----------------


def test_a_sprint_step_is_bounded_at_three_llm_calls():
    """There is no in-worker budget check anywhere in this repo — the per-task cap is
    enforced at dispatch (`check_cost_cap` + `spawn_headroom_usd`), once per tick,
    before a step is spawned. What keeps a sprint step's in-flight spend bounded is the
    pipeline's own hard ceiling, not a mid-flight check: 1 draft + at most
    MAX_REVISE_ROUNDS revises, with no loop the model can extend."""
    from my_crew.runtime import sprint_runner

    assert sprint_runner.MAX_REVISE_ROUNDS == 2
    assert sprint_runner.MAX_TOTAL_QUERIES == 8
    assert sprint_runner.MAX_SPRINT_PREFETCH_QUERIES < sprint_runner.MAX_TOTAL_QUERIES
    # The scaled budget an entity list buys is hard-capped too: however long the
    # enumeration, prefetch and total query counts stay decidable for the cost cap.
    assert sprint_runner.sprint_query_budget(0) == (
        sprint_runner.MAX_SPRINT_PREFETCH_QUERIES,
        sprint_runner.MAX_TOTAL_QUERIES,
    )
    assert sprint_runner.sprint_query_budget(30) == (
        sprint_runner.SCALED_PREFETCH_CAP,
        sprint_runner.SCALED_TOTAL_CAP,
    )


def test_sprint_cost_sums_every_call_the_pipeline_made(monkeypatch):
    """`check_cost_cap` sums the step rows. The pipeline returns ONE total covering
    every call it made, so a sprint step's true spend is visible to the cap even though
    the cap never sees the individual draft/revise calls. A total that only counted the
    draft would under-report a 3-call step by two thirds."""
    import my_crew.llm.client as client_mod
    import my_crew.runtime.sprint_runner as mod

    calls = {"n": 0}

    class _Llm:
        def complete(self, _messages, **_kw):
            calls["n"] += 1
            return SimpleNamespace(content="Chỉ nói về Netflix.", cost_usd=0.02)

    monkeypatch.setattr(mod, "LlmClient", lambda _s: _Llm(), raising=False)
    monkeypatch.setattr(client_mod, "LlmClient", lambda _s: _Llm())
    work = mod.build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance="Phải có: Netflix, Spotify",
        prefetch=lambda *_a: "kết quả",
    )
    _text, cost = work("so sánh dịch vụ streaming", "", None)
    assert calls["n"] > 1  # a gap forced at least one revise round
    assert cost == round(0.02 * calls["n"], 10) or abs(cost - 0.02 * calls["n"]) < 1e-9


# --- dead end: the escalation names the ONE remedy a sprint task actually has -------


def _escalation_task(step_type="sprint", task_id="t1"):
    return SimpleNamespace(id=task_id, title="Demo", steps=[_sprint_step()]
                           if step_type == "sprint" else [
                               SimpleNamespace(step_id="s1", step_type="work")])


def test_a_sprint_dead_end_offers_the_switch_to_the_crew():
    """`reassign` is the coordinator's normal answer to a step nobody can finish, and
    it is the one answer that cannot help here: every sprint step runs the SAME
    code-paced pipeline, so a different agent re-runs identical code. The remedy is a
    mode change, which only the CEO can make — so the escalation has to say so.

    v78 made that remedy one-touch: `upgrade_to_team <id>` rebuilds the work as a crew
    task carrying the dead run's draft, instead of asking the CEO to retype the brief
    behind a `team:` prefix and lose everything the sprint already produced."""
    from my_crew.runtime.team_tick_collaborators import (
        _SPRINT_UPGRADE_SUGGESTION,
        _is_sprint_dead_end,
    )

    assert _is_sprint_dead_end(_escalation_task(), "gave_up") is True
    assert "upgrade_to_team" in _SPRINT_UPGRADE_SUGGESTION


def test_the_upgrade_hint_stays_off_a_step_the_coordinator_is_still_retrying():
    """`stuck` fires on retry_with_guidance/reassign, which put the step BACK to
    pending. Suggesting a fresh team task there would talk the CEO into abandoning
    work the coordinator is actively still trying to finish."""
    from my_crew.runtime.team_tick_collaborators import _is_sprint_dead_end

    for kind in ("stuck", "step_failed", "task_stalled_dead_step", "cost_cap_exceeded"):
        assert _is_sprint_dead_end(_escalation_task(), kind) is False


def test_a_team_task_dead_end_gets_no_sprint_hint():
    """A normal team task already has the amend/one-touch remedies; telling its CEO to
    'switch to team mode' would be nonsense."""
    from my_crew.runtime.team_tick_collaborators import _is_sprint_dead_end

    assert _is_sprint_dead_end(_escalation_task(step_type="work"), "gave_up") is False


@pytest.mark.parametrize("name", [
    "_SPRINT_UPGRADE_SUGGESTION", "_SPRINT_UPGRADED_TEMPLATE",
    "_AMEND_SUGGESTION_TEMPLATE", "_ONE_TOUCH_SUGGESTION_TEMPLATE",
])
def test_escalation_command_hints_carry_no_task_derived_text(name):
    """The constant-template rule, asserted on every hint that ends up as a command
    line the CEO may copy-paste: interpolate the code-assigned task id and NOTHING
    else. Task/step titles can carry text absorbed from a hostile brief or from a web
    result a prior step echoed, so a hint composed from them could smuggle a different
    command into the CEO's clipboard.

    Checking the placeholder NAMES rather than banning `{` altogether: these hints do
    have to name a specific task to be one-touch, and forbidding interpolation outright
    would only push the composition somewhere this test cannot see.
    """
    import my_crew.runtime.team_tick_collaborators as mod

    template = getattr(mod, name)
    placeholders = set(re.findall(r"{(\w+)}", template))
    assert placeholders <= {"task_id", "new_task_id"}, (
        f"{name} interpolates {placeholders - {'task_id', 'new_task_id'}} — only "
        "code-assigned task ids may appear in a copy-pasteable command hint"
    )


# --- audit: searches ride the same audited path as every other web search -----------


def test_sprint_searches_go_through_the_audited_launcher():
    """Sprint picks its own queries but must not open a new egress path — it calls
    `prefetch_queries`, the same launcher collect steps use, which writes to the agent's
    audit chain with the same WebSearchConfig gates."""
    src = Path("my_crew/runtime/sprint_runner.py").read_text()
    assert "from my_crew.runtime.collect_prefetch import prefetch_queries" in src
    launcher = Path("my_crew/runtime/collect_prefetch.py").read_text()
    assert "AuditLog" in launcher
    assert "audit_log=audit_log" in launcher


def test_a_sprint_search_round_leaves_a_verifiable_audit_chain(tmp_path, monkeypatch):
    """`mpm agent audit <id> verify --team` walks THIS file. Only the search provider
    is faked here — the launcher, the AuditLog writes and the hash chaining are all
    real, so this fails if a sprint round ever writes rows outside `AuditLog.record`
    (which is what computes `entry_hash`/`prev_hash`) and silently breaks the chain."""
    from my_crew.audit.audit_chain import verify_chain
    from my_crew.runtime import team_task_paths
    from my_crew.runtime.collect_prefetch import prefetch_queries
    from my_crew.tools import web_search_tool
    from my_crew.tools.search_result_formatter import SearchResult

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)
    hit = SearchResult(title="Netflix", snippet="giá 260k", source="netflix.com")
    # Fake ONLY the provider call. `tavily_fn` is a default argument bound at def
    # time, so patching the module attribute would not reach it (it reached the real
    # network instead); passing it through a wrapper keeps the audit write real.
    real = web_search_tool.web_search_outcome
    monkeypatch.setattr(
        web_search_tool, "web_search_outcome",
        lambda q, **kw: real(q, tavily_fn=lambda _q, _key: [hit], **kw),
    )

    bundle = prefetch_queries(
        SimpleNamespace(web_search=True),
        SimpleNamespace(tavily_api_key="t", brave_api_key=None,
                        data_dir=str(tmp_path / "agent")),
        ["giá Netflix", "giá Spotify"],
    )
    assert "KẾT QUẢ TÌM KIẾM" in bundle

    trail = team_task_paths.team_tasks_root() / "audit" / "audit.jsonl"
    verdict = verify_chain(trail)
    assert verdict["total"] == 2, "one audited row per query the sprint round issued"
    assert verdict["ok"] is True
    assert verdict["hashed"] == 2


# --- metrics: a sprint attempt is a work attempt, so the band loop can still see it --


def test_sprint_attempts_count_toward_the_metrics_the_band_loop_reads(
    tmp_path, monkeypatch,
):
    """`agent_metrics` filters work attempts by EXCLUDING review rows, not by matching
    `== "work"` — which is what silently admits `sprint`. That matters beyond a
    dashboard number: `band_loop` demotes on `needs_decision_rate`, so if sprint
    attempts were excluded an agent doing nothing but sprints would build no track
    record at all and become unreachable by the autonomy loop in either direction."""
    from my_crew.runtime.agent_metrics import agent_metrics
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    cs = CaptureStore(capture_db_path())
    try:
        for i in range(6):
            cs.record(attempt_id=f"sp{i}", task_id="t1", step_id=f"s{i}",
                      agent_id="researcher", engine="native", status="done",
                      step_type="sprint", duration_ms=1000, cost_usd=0.01)
        cs.record(attempt_id="sp-bad", task_id="t1", step_id="s9",
                  agent_id="researcher", engine="native", status="needs_decision",
                  step_type="sprint", duration_ms=1000, cost_usd=0.01)
        # A review row on the same agent must STILL be excluded — the sprint fix must
        # not have widened the filter into counting reviews as work.
        cs.record(attempt_id="rv", task_id="t1", step_id="s10",
                  agent_id="researcher", engine="native", status="done",
                  step_type="review", duration_ms=1000, cost_usd=0.01)
    finally:
        cs.close()

    agent = agent_metrics()["agents"]["researcher"]
    assert agent["attempts"] == 7
    assert agent["needs_decision_rate"]["value"] == round(1 / 7, 4)


# --- the sprint's rework node keeps a way to look things up --------------------------


def _toolless_for(step) -> bool:
    from my_crew.runtime.team_step_runner import step_is_toolless

    return step_is_toolless(step)


def test_a_web_sprint_keeps_a_search_hook_for_its_rework_node():
    """The sprint pipeline replaces the WORK node and runs its own searches, so the
    graph's hook is unreachable there. `rework` is a different node — and it was the
    one starving: asked to close data gaps with no way to look anything up, it blanked
    the rows it could not defend and stalled the task (f62348234949, 7ebfc0374c5c).
    A web-shaped sprint must therefore NOT be wired tool-less."""
    step = SimpleNamespace(step_type="sprint", needs_web=True, intervention_count=0)
    assert _toolless_for(step) is False


def test_a_tool_less_sprint_stays_tool_less():
    """Intake ruled this step write/reason-only — there is nothing to look up, and a
    hook here would buy a doomed search plus a disclaimer about it."""
    step = SimpleNamespace(step_type="sprint", needs_web=False, intervention_count=0)
    assert _toolless_for(step) is True


def test_a_review_step_stays_tool_less():
    """Grading reads its handoff; the hook's one search per run was pure cost."""
    step = SimpleNamespace(step_type="review", needs_web=True, intervention_count=0)
    assert _toolless_for(step) is True
