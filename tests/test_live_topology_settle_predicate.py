"""`is_settled` — the stop condition every live case's polling loop depends on.

Offline on purpose, and deliberately NOT under `tests/fullflow_live/`: that package's
conftest marks everything it collects as `live`, and `pyproject.toml` sets
`addopts = ["-m", "not live"]`. A guard placed there would be skipped by a plain `pytest`
run — that is, skipped exactly when it is needed. It costs nothing to run here, and it
pins harness logic rather than product behaviour, so it belongs in the free lane.

The case that motivated this: a live run planned `[step1 done, step2 waiting_clarify]`.
Nothing would ever move that task again without the CEO answering, but a rule that
required ALL steps to be parked kept polling for the full 900s and then failed a case
whose actual assertions would all have passed. A stop condition that cannot recognise a
stopped task turns a green test red on the clock.
"""

from __future__ import annotations

import pytest

from tests.fullflow_live.topology import is_settled


def _status(state: str | None, *step_statuses: str) -> dict:
    """A task-status payload shaped like `build_task_status`'s output, trimmed to the
    two fields `is_settled` actually reads."""
    return {
        "state": {"status": state},
        "steps": [{"status": s} for s in step_statuses],
    }


@pytest.mark.parametrize("terminal", ["done", "delivered", "cancelled", "failed"])
def test_a_terminal_task_state_settles_whatever_the_steps_say(terminal):
    """The task-level state is authoritative when it is terminal — a stale `running` row
    under a `done` task must not keep a suite polling."""
    assert is_settled(_status(terminal, "running"))


def test_finished_and_parked_steps_together_settle():
    """The measured regression: partly finished, remainder parked on a human."""
    assert is_settled(_status("open", "done", "waiting_clarify"))


def test_all_parked_steps_settle():
    assert is_settled(_status("open", "waiting_clarify", "blocked"))


def test_a_live_step_beside_a_finished_one_does_NOT_settle():
    """The half this fix must not break. A `done` step is finished, but it is not a reason
    to stop waiting on a sibling that is still running — treating it as one would end
    polling mid-flight and read a half-built plan as final."""
    assert not is_settled(_status("open", "done", "running"))


def test_all_finished_steps_defer_to_the_task_state():
    """Every step finished but the task not yet terminal means work is still in flight at
    the task level (aggregate/delivery). Settling here would race the aggregate step and
    read costs and outputs before they are written."""
    assert not is_settled(_status("open", "done", "done"))


def test_no_steps_never_settles():
    """A task with no rows yet has not been planned; `all([])` is vacuously True, so
    without an explicit guard an empty plan would look settled."""
    assert not is_settled(_status("open"))
