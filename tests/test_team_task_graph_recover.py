"""The v14 blocked-step recovery loop: `work` fails → `recover` (one best-effort
consult about the blocker) → `work` retries once → success delivers / second failure
re-raises exactly like pre-v14.

Load-bearing:
- fail once → recover consults with the blocker in the brief → retry succeeds →
  deliver; costs from the failed pass's consult spend are NOT lost.
- fail twice → the second exception propagates (runner's mark_failed/escalate
  contract unchanged — `route_after_work` never sees an over-budget failure).
- success on the first pass → recover never runs, `work_error` stays empty
  (pre-v14 byte-identical path).
- consult off (hooks None) → recover still retries once (plain retry, transient
  errors are the common case) and the retry's failure is terminal.
- pre-work consult is SKIPPED on the retry pass (recover already asked the one
  targeted question — no budget double-burn).
"""

from __future__ import annotations

import pytest

from my_crew.agent.team_task_graph import MAX_RECOVER, TeamTaskDeps, build_team_task_graph


def _deps(run_work, **overrides):
    def read_handoff() -> str:
        return ""

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


def test_fail_once_recover_consults_blocker_then_retry_delivers():
    calls = {"work": 0}
    proposed_briefs = []

    def run_work(title, handoff, hook):
        calls["work"] += 1
        if calls["work"] == 1:
            raise RuntimeError("provider 500")
        return f"work[{handoff}]", 0.01

    def propose_consults(title, handoff):
        proposed_briefs.append(title)
        return [("colleague-1", "kẹt vì sao?")]

    def ask_colleague(agent_id, question):
        return "Thử đổi cách tiếp cận B.", 0.02

    deps = _deps(run_work, ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert calls["work"] == 2
    assert result["delivered"] is True
    assert result["recover_count"] == 1
    assert result["work_error"] == ""
    # the recover consult saw the blocker text, and its advice reached the retry
    assert any("ĐANG BỊ KẸT" in b and "provider 500" in b for b in proposed_briefs)
    assert "Thử đổi cách tiếp cận B." in result["result_text"]
    # pass-1 pre-work consult (0.02) + recover consult (0.02) + successful retry (0.01)
    # — the failed pass's consult spend is NOT lost when the retry overwrites the slice
    assert result["cost_usd"] == pytest.approx(0.05)


def test_fail_twice_second_exception_propagates_like_pre_v14():
    calls = {"work": 0}

    def run_work(title, handoff, hook):
        calls["work"] += 1
        raise RuntimeError(f"boom {calls['work']}")

    deps = _deps(run_work)
    graph = build_team_task_graph(deps=deps)
    with pytest.raises(RuntimeError, match="boom 2"):
        graph.invoke({"step_title": "t"})
    assert calls["work"] == 1 + MAX_RECOVER


def test_success_first_pass_recover_never_runs():
    def run_work(title, handoff, hook):
        return "ok", 0.01

    def propose_consults(title, handoff):
        raise AssertionError("propose must not run for recovery on a success path")

    deps = _deps(run_work)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result.get("recover_count", 0) == 0
    assert result.get("work_error", "") == ""
    assert result["delivered"] is True


def test_consult_off_recover_still_plain_retries_once():
    calls = {"work": 0}

    def run_work(title, handoff, hook):
        calls["work"] += 1
        if calls["work"] == 1:
            raise RuntimeError("transient")
        return "ok", None

    deps = _deps(run_work)  # ask_colleague / propose_consults both None
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert calls["work"] == 2
    assert result["delivered"] is True
    assert result["recover_count"] == 1
    assert result.get("recover_hint", "") == ""


def test_retry_pass_skips_pre_work_consult_no_budget_double_burn():
    calls = {"work": 0, "propose": 0}

    def run_work(title, handoff, hook):
        calls["work"] += 1
        if calls["work"] == 1:
            raise RuntimeError("stuck")
        return "ok", None

    def propose_consults(title, handoff):
        calls["propose"] += 1
        return [("colleague-1", "q")]

    def ask_colleague(agent_id, question):
        return "a", 0.01

    deps = _deps(run_work, ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    # pass 1 pre-work propose + recover propose = 2; the RETRY pass proposes nothing
    assert calls["propose"] == 2
    assert result["consult_count"] == 2
    assert result["delivered"] is True


def test_recover_consult_failure_degrades_to_plain_retry():
    calls = {"work": 0}

    def run_work(title, handoff, hook):
        calls["work"] += 1
        if calls["work"] == 1:
            raise RuntimeError("stuck")
        return "ok", None

    def propose_consults(title, handoff):
        raise RuntimeError("propose boom")

    def ask_colleague(agent_id, question):
        raise AssertionError("never reached — propose failed")

    deps = _deps(run_work, ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result["delivered"] is True
    assert result["recover_count"] == 1
    assert result.get("recover_hint", "") == ""


def test_paid_consult_answers_survive_retry_when_recover_consult_empty():
    """Review finding M1 pinned: pass-1 pre-work consult answers are PAID context —
    they must reach the recovery retry's run_work even when the recover node itself
    got no consult budget/answer (worst case: budget fully burned before the failure)."""
    calls = {"work": 0}
    seen_handoffs = []

    def run_work(title, handoff, hook):
        calls["work"] += 1
        seen_handoffs.append(handoff)
        if calls["work"] == 1:
            raise RuntimeError("stuck")
        return f"work[{handoff}]", None

    def propose_consults(title, handoff):
        # two targets on pass 1 — burns the WHOLE MAX_CONSULTS budget before the failure
        return [("c-1", "q1"), ("c-2", "q2")]

    def ask_colleague(agent_id, question):
        return f"advice-{agent_id}", 0.01

    deps = _deps(run_work, ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "t"})

    assert result["recover_hint"] == ""  # recover had no budget left — no hint
    # ...yet the retry STILL saw both paid answers via the state-persisted context
    assert "advice-c-1" in seen_handoffs[1]
    assert "advice-c-2" in seen_handoffs[1]
    assert "advice-c-1" in result["result_text"]


def test_work_error_squashed_to_single_line():
    """Review finding m1 pinned: a multi-line exception string is squashed before it
    rides into state/the recover consult brief."""
    calls = {"work": 0}
    captured = {}

    def run_work(title, handoff, hook):
        calls["work"] += 1
        if calls["work"] == 1:
            raise RuntimeError("line1\nline2\ttab   spaces")
        return "ok", None

    def propose_consults(title, handoff):
        captured["brief"] = title
        return []

    def ask_colleague(agent_id, question):
        return "", 0.0

    deps = _deps(run_work, ask_colleague=ask_colleague, propose_consults=propose_consults)
    graph = build_team_task_graph(deps=deps)
    graph.invoke({"step_title": "t"})

    assert "\n" not in captured["brief"] and "\t" not in captured["brief"]
    assert "line1 line2 tab spaces" in captured["brief"]


def test_recover_phase_tag_passes_room_projection_allowlist():
    """v13 lesson pinned: a NEW phase tag must clear the write-time allowlist, or the
    room event silently drops it — graph writer, projection and FE label must agree."""
    from my_crew.agent.team_task_graph import PHASE_RECOVER
    from my_crew.server.office_event_projection import summarize_office_event

    body = summarize_office_event("step_status", {"phase": PHASE_RECOVER, "status": "started"})
    assert body["phase"] == PHASE_RECOVER
