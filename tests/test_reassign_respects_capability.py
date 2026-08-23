"""A reassign may not hand a step to an agent that lacks the tools it DECLARES needing.

`roster_ok` answers "may this agent hold a step at all" — it says nothing about whether
this particular agent can DO this particular step. Production shape (task d4679e1fbe14):
a web data-collection step stalled on the researcher was reassigned to an agent with no
`web_search:` flag. That agent is dispatchable and doomed — with no way to look anything
up its best honest outcome is reporting the gap, and its worst is inventing the figures.

The step's `needs_web` declaration is the only requirement source. The predicate once
also refused moving any step away from a web-capable holder, and that misfired live: a
synthesis step (needs_web=0) stuck on the researcher could not go to the analyst, so a
nearly-finished task was concluded as a failure. Steps that declare nothing move freely;
the coordinator keeps its main lever for agents stuck for non-tooling reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
from my_crew.agent.coordinator_nodes.stuck_decision import (
    MAX_INTERVENTIONS,
    decide_stuck_step,
)
from my_crew.runtime.team_task_steps import TeamStep
from my_crew.runtime.team_task_store import TeamTask


def _Step(assigned_to: str = "researcher") -> TeamStep:
    return TeamStep(
        task_id="t1", step_id="step1", seq=1, title="Thu thập dữ liệu giá thuê",
        assigned_to=assigned_to, deps=(), status="needs_decision", outcome_ref=None,
        cost_usd=None, attempt_id=None, child_pid=None, spawned_at=None, last_seen=None,
        lease_expires_at=None, escalated_at=None, approval_id=None, acceptance="",
        step_type="work", needs_review=False, system_inserted=False,
        parent_step_id=None, review_round=0,
    )


def _Task() -> TeamTask:
    return TeamTask(
        id="t1", title="Nghiên cứu giá thuê", original_request="nghiên cứu giá thuê",
        status="running", created_at="2026-08-06T00:00:00", assigned_by="ceo",
        cost_usd_total=0.0, plan_hash="h", decompose_cost_usd=0.0,
        aggregate_cost_usd=0.0, escalated_at=None,
    )


@dataclass
class _Store:
    reassigned: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    interventions: int = 0

    def bump_intervention(self, _task_id, _step_id):
        self.interventions += 1
        return self.interventions

    def reassign_step(self, _task_id, step_id, new_assignee):
        self.reassigned.append((step_id, new_assignee))

    def append_step_guidance(self, *_a, **_k):
        pass

    def reset_step_to_pending(self, *_a, **_k):
        pass

    def mark_failed(self, _task_id, step_id, *_a, **_k):
        # Returns True like the real store: the caller reads this to detect a write
        # that matched no row, and a falsy stand-in would send it down the repair path.
        self.failed.append(step_id)
        return True

    def set_delivery(self, *_a, **_k):
        pass

    def set_task_status(self, *_a, **_k):
        pass

    def set_final_summary(self, *_a, **_k):
        pass


def _deps(store, *, judgement_target: str, can_do) -> CoordinatorDeps:
    return CoordinatorDeps(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        roster_ok=lambda _a: True,
        can_do_step=can_do,
        judge_stuck_step=lambda _brief, _step: {
            "decision": "reassign", "assign_to": judgement_target,
            "guidance": "tra web rồi tổng hợp", "reason": "cần người khác",
        },
        escalate=lambda *_a, **_k: None,
    )


def test_a_downgrade_is_refused_and_the_task_concludes_honestly():
    """The exact production move: web step from an agent WITH search to one WITHOUT."""
    store = _Store()
    result = decide_stuck_step(
        _deps(store, judgement_target="analyst", can_do=lambda a, _s: a != "analyst"),
        _Task(), _Step(),
    )
    assert store.reassigned == [], "the doomed reassign must not be written"
    assert result.action != "stuck_reassigned"


def test_the_refusal_names_the_missing_capability_not_a_vague_failure():
    """A CEO reading "không đổi được người" learns nothing actionable. Saying the
    proposed agent lacks the tool points at the fix (grant it, or accept the gap)."""
    store = _Store(interventions=1)  # 2nd ruling — past the retry-first coercion
    captured = []
    deps = _deps(store, judgement_target="analyst", can_do=lambda a, _s: a != "analyst")
    deps.escalate = lambda _t, _s, _k, msg: captured.append(msg)
    decide_stuck_step(deps, _Task(), _Step())
    assert any("công cụ" in m for m in captured), captured


def test_a_capable_reassign_still_goes_through():
    """The gate must not freeze reassignment in general — that is the coordinator's
    main lever for an agent that is stuck for any non-tooling reason."""
    store = _Store(interventions=1)  # 2nd ruling — past the retry-first coercion
    result = decide_stuck_step(
        _deps(store, judgement_target="analyst", can_do=lambda _a, _s: True),
        _Task(), _Step(),
    )
    assert store.reassigned == [("step1", "analyst")]
    assert result.action == "stuck_reassigned"


def test_the_default_collaborator_allows_every_reassign():
    """Unwired `can_do_step` keeps pre-existing behavior — every existing fake roster
    ("agent-a"/"agent-b") must stay dispatchable without knowing about this gate."""
    store = _Store(interventions=1)  # 2nd ruling — past the retry-first coercion
    deps = CoordinatorDeps(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        roster_ok=lambda _a: True,
        judge_stuck_step=lambda _b, _s: {
            "decision": "reassign", "assign_to": "agent-b", "reason": "x",
        },
        escalate=lambda *_a, **_k: None,
    )
    decide_stuck_step(deps, _Task(), _Step(assigned_to="agent-a"))
    assert store.reassigned == [("step1", "agent-b")]


def test_only_downgrades_are_blocked_not_lateral_moves():
    """Real predicate: an agent whose current holder never had search can be moved
    anywhere. Blocking those would strand ordinary steps for no benefit."""
    from my_crew.runtime.team_tick_runner import _can_do_step

    class _S:
        assigned_to = ""

    assert _can_do_step("anyone", _S()) is True


def test_a_step_that_declares_no_web_need_moves_off_a_web_capable_holder(monkeypatch):
    """Live team run: a synthesis step (needs_web=0) stuck on the researcher was
    refused reassignment to the analyst purely because the researcher COULD search,
    and the task — with every survey step already done — was concluded as a failure.
    The declaration is the requirement; who currently holds the step is not."""
    from types import SimpleNamespace

    import my_crew.runtime.team_tick_runner as ttr

    step = SimpleNamespace(needs_web=False, assigned_to="researcher")
    monkeypatch.setattr(ttr, "_web_search_enabled", lambda a: a == "researcher")
    assert ttr._can_do_step("analyst", step) is True


def test_first_ruling_reassign_is_coerced_to_retry_with_guidance():
    """Retry-first policy: measured live, the judge chose reassign on the FIRST failure
    5/6 times and it was wrong every time (the original assignee fixed it on retry once
    given the failure list; the new assignee started from zero — twice a deep_agent that
    could not run the web search the step needed). First ruling retries; reassign is
    earned from the second ruling."""
    store = _Store()  # interventions=0 → this ruling is the first
    result = decide_stuck_step(
        _deps(store, judgement_target="analyst", can_do=lambda _a, _s: True),
        _Task(), _Step(),
    )
    assert store.reassigned == []  # no reassign written on ruling #1
    assert result.action == "stuck_retry"


def test_needs_web_step_requires_a_searching_assignee(monkeypatch):
    """v74: a step DECLARED to need live web lookup refuses any searchless candidate,
    regardless of what its current holder can do (the pre-v74 gate only refused
    downgrades relative to the current assignee)."""
    from types import SimpleNamespace

    import my_crew.runtime.team_tick_runner as ttr

    step = SimpleNamespace(needs_web=True, assigned_to="searchless-holder")
    monkeypatch.setattr(ttr, "_web_search_enabled", lambda a: a == "capable")
    assert ttr._can_do_step("capable", step) is True
    assert ttr._can_do_step("also-searchless", step) is False


def test_a_doomed_reassign_becomes_a_retry_instead_of_ending_the_task():
    """Live task c357f5481bf5 stalled here, and the loss was an INTERVENTION, not a rule.

    `MAX_INTERVENTIONS` is 2, and ruling #1 is always coerced to retry — so ruling #2 is
    the only one that may reassign. When the judge spends it proposing an agent that
    `can_do_step` must refuse, the step is concluded even though the capable original
    holder never got a second guided attempt. For a `needs_web` brief where only the
    researcher can search, "change assignee" is never reachable, so `give_up` there
    trades a real remaining attempt for a move that could not have worked.

    Refusing the move stays correct; ending the task on it does not. The refusal now
    degrades to `retry_with_guidance` with the capable holder, and only concludes when
    the interventions are genuinely spent.
    """
    store = _Store(interventions=1)  # 2nd ruling — reassign is allowed here
    result = decide_stuck_step(
        _deps(store, judgement_target="analyst", can_do=lambda a, _s: a != "analyst"),
        _Task(), _Step(),
    )
    assert store.reassigned == [], "the doomed reassign must still be refused"
    assert store.failed == [], "a refused reassign must not conclude the task"
    assert result.action == "stuck_retry"


def test_a_doomed_reassign_still_concludes_once_interventions_are_spent():
    """The degrade-to-retry must not become an infinite loop: at the cap the step is
    concluded exactly as before, so the anti-loop bound remains the hard gate."""
    store = _Store(interventions=MAX_INTERVENTIONS)  # this ruling is the last one
    result = decide_stuck_step(
        _deps(store, judgement_target="analyst", can_do=lambda a, _s: a != "analyst"),
        _Task(), _Step(),
    )
    assert store.reassigned == []
    assert store.failed == ["step1"], "at the cap it must still conclude honestly"
    assert result.action != "stuck_retry"
