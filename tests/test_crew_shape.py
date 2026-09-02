"""The crew shapes: what each surviving one requires of a plan, and what falls through.

A shape is the router's proof that a crew buys something a sprint cannot — separate
contexts for breadth, an independent grader, or a permission boundary. These tests pin
the classification on synthetic plans so the bench can trust `route["shape"]`.
"""

from __future__ import annotations

import pytest

from my_crew.agent.crew_shape import (
    CREW_SHAPES,
    DO_REVIEW_MAX_STEPS,
    classify_shape,
    enforce_refusal_boundary,
    mark_do_review,
)
from my_crew.agent.task_decomposition import DecomposedTask, TeamStepPlan


def _step(step_id: str, assigned_to: str = "agent-a", deps: tuple[str, ...] = (), **flags):
    return TeamStepPlan(step_id=step_id, title=f"bước {step_id}", assigned_to=assigned_to,
                        deps=deps, **flags)


def _plan(*steps: TeamStepPlan) -> DecomposedTask:
    return DecomposedTask(steps=tuple(steps), pic_id="agent-a")


_NO_ASK = {"needs_independent_review": 0}
_ASK = {"needs_independent_review": 1}


def test_two_parallel_lookups_merged_are_not_a_crew():
    """The fan-out shape was benched and killed: blind-judged over 4 cases × 3 runs the
    parallel-sources crew beat a sprint 4/12 times at 1.5× the cost, and its
    cheap-specialist variant lost 8/12. A plan that looks like one has no boundary a
    sprint lacks, so it classifies as nothing and runs as a sprint."""
    plan = _plan(_step("s1", needs_web=True), _step("s2", "agent-b", needs_web=True),
                 _step("s3", deps=("s1", "s2")))

    assert classify_shape(plan, _NO_ASK) is None


def test_one_lookup_then_a_write_up_is_not_a_crew():
    """A single source needs no second context — one agent holds it next to the brief."""
    plan = _plan(_step("s1", needs_web=True), _step("s2", "agent-b", deps=("s1",)))

    assert classify_shape(plan, _NO_ASK) is None


def test_parallel_lookups_nobody_merges_are_not_a_crew():
    """Breadth without a merge is two sprints, not a crew: no step reads both."""
    plan = _plan(_step("s1", needs_web=True), _step("s2", "agent-b", needs_web=True))

    assert classify_shape(plan, _NO_ASK) is None


@pytest.mark.parametrize("flag", ["needs_shell", "external_write", "needs_mail"])
def test_any_sensitive_step_makes_a_permission_chain(flag):
    plan = _plan(_step("s1"), _step("s2", "agent-b", deps=("s1",), **{flag: True}))

    assert classify_shape(plan, _NO_ASK) == "permission_chain"


def test_a_sensitive_step_outranks_every_other_shape_and_any_length():
    """Safety first: the sprint hardcodes shell/write off, so a plan with one shell step
    must never be classified as anything a sprint could absorb — however long it is,
    and even when its other steps are plain parallel lookups."""
    plan = _plan(
        _step("s1", needs_web=True), _step("s2", "agent-b", needs_web=True),
        _step("s3", deps=("s1", "s2")), _step("s4", deps=("s3",)),
        _step("s5", deps=("s4",), needs_shell=True),
    )

    assert classify_shape(plan, _ASK) == "permission_chain"


def test_a_small_plan_the_ceo_wants_checked_is_do_review():
    plan = _plan(_step("s1"), _step("s2", "agent-b", deps=("s1",)))

    assert classify_shape(plan, _ASK) == "do_review"
    assert classify_shape(plan, _NO_ASK) is None


def test_do_review_is_only_for_small_plans():
    """A longer plan already reviews its terminal under the standing policy; the shape
    exists to buy a grader for ONE deliverable, not to bless a long chain."""
    steps = [_step("s1")]
    for i in range(2, DO_REVIEW_MAX_STEPS + 2):
        steps.append(_step(f"s{i}", deps=(f"s{i - 1}",)))

    assert len(steps) == DO_REVIEW_MAX_STEPS + 1
    assert classify_shape(_plan(*steps), _ASK) is None
    assert classify_shape(_plan(*steps[:DO_REVIEW_MAX_STEPS]), _ASK) == "do_review"


def test_mark_do_review_flags_only_the_terminal_and_is_idempotent():
    plan = _plan(_step("s1"), _step("s2", "agent-b", deps=("s1",)))

    marked = mark_do_review(plan)

    assert [s.needs_review for s in marked.steps] == [False, True]
    assert mark_do_review(marked) is marked


def test_every_shape_has_a_precedence_slot():
    assert set(CREW_SHAPES) == {"permission_chain", "do_review"}
    assert "fanout" not in CREW_SHAPES  # killed by the bench; a fan-out plan is a sprint


_WRITE_REFUSAL = "ghi ra ngoài công ty ('gửi email')"


def test_a_refused_write_brief_whose_plan_lost_the_flag_gets_it_back_on_the_terminal():
    """The model reads the brief's "gửi email" and still writes a plan with no
    `external_write` step. Without the repair the shape gate would sprint it — and the
    sprint hardcodes writes off, dropping the review the refusal was for."""
    plan = _plan(_step("s1", needs_web=True), _step("s2", "agent-b", deps=("s1",)))

    fixed = enforce_refusal_boundary(plan, _WRITE_REFUSAL)

    flags = {s.step_id: s.external_write for s in fixed.steps}
    assert flags == {"s1": False, "s2": True}
    assert classify_shape(fixed, _NO_ASK) == "permission_chain"


def test_a_plan_that_already_carries_a_write_step_is_left_alone():
    plan = _plan(_step("s1", external_write=True), _step("s2", "agent-b", deps=("s1",)))

    assert enforce_refusal_boundary(plan, _WRITE_REFUSAL) is plan


@pytest.mark.parametrize("refusal", ["", "cần chạy shell/mã ('chạy test')",
                                     "CEO nêu cần nhiều người ('chia việc')"])
def test_only_the_external_write_refusal_has_a_flag_to_restore(refusal):
    plan = _plan(_step("s1"), _step("s2", "agent-b", deps=("s1",)))

    assert enforce_refusal_boundary(plan, refusal) is plan
