"""A step that produced NOTHING must not be graded as acceptable work.

The tools tier degrades to an empty string when its loop hits the recursion cap
(`invoke_capped` catches `GraphRecursionError` and returns an empty assistant turn so the
step still reaches self_check/deliver rather than failing outright). That degrade is
deliberate — but it means "" is a reachable `result_text`, and self_check was grading it
like any other output.

Production shape (task 3e4a8d64ea20/step1): the step spent $0.0008, wrote nothing, passed
self-check, and was persisted `done` with `self_check_failed: False`. Its dependents then
received an empty handoff and had to invent or give up. An empty result is the ABSENCE of
work, not work of poor quality, and it is decidable without asking a model anything.

No LLM and no network — the guard returns before any provider call is made.
"""

from __future__ import annotations

from my_crew.agent.team_task_graph import default_team_task_deps


def _deps(tmp_path):
    """Real deps, real `_run_self_check`. `settings=None` is safe precisely because the
    empty-result guard must short-circuit before `_llm()` is ever touched — a test that
    needed a provider would be testing the wrong thing."""
    return default_team_task_deps(
        settings=None, step_title="Thu thập dữ liệu giá thuê",
        data_dir=tmp_path, task_id="t1", step_seq=1,
    )


def test_an_empty_result_fails_self_check(tmp_path):
    passed, failures, _ = _deps(tmp_path).run_self_check("", "có bảng số liệu kèm nguồn")
    assert passed is False
    assert failures, "a failure must be stated so rework/coordinator has something to act on"


def test_whitespace_only_is_also_empty(tmp_path):
    """The degrade path yields ""; a model that emits only a newline is the same nothing."""
    passed, _, _ = _deps(tmp_path).run_self_check("   \n\t  ", "có bảng số liệu kèm nguồn")
    assert passed is False


def test_empty_fails_even_when_the_step_has_no_acceptance_rubric(tmp_path):
    """The blank-criteria shortcut passes ungraded steps trivially. Ordered AFTER it, the
    empty guard would never fire for the steps most able to hide a blank — the ones nobody
    wrote criteria for. This pins the ordering, not just the behavior."""
    passed, _, _ = _deps(tmp_path).run_self_check("", "")
    assert passed is False


def test_the_failure_message_says_the_result_was_empty(tmp_path):
    """A coordinator reading "không đạt tiêu chí" would send it back to be rewritten. Saying
    the step returned nothing points at the real cause (the loop cap, not the writing)."""
    _, failures, _ = _deps(tmp_path).run_self_check("", "có bảng số liệu")
    assert any("rỗng" in f for f in failures), failures


def test_a_non_empty_result_is_still_graded_normally(tmp_path):
    """The guard must not swallow real output — an ungraded (no-rubric) step with actual
    content still takes the pre-existing trivial-pass path, no provider call."""
    passed, failures, _ = _deps(tmp_path).run_self_check("Giá thuê hạng A: 64.7 USD/m²", "")
    assert passed is True
    assert failures == []
