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


def _status(state: str | None, *steps: str | tuple) -> dict:
    """A task-status payload shaped like `build_task_status`'s output, trimmed to the
    fields `is_settled` actually reads. A step is a status string, or
    `(step_id, status, deps)` when the dependency graph matters."""
    rows = []
    for i, step in enumerate(steps):
        if isinstance(step, str):
            rows.append({"step_id": f"s{i}", "status": step, "deps": []})
        else:
            step_id, status, deps = step
            rows.append({"step_id": step_id, "status": status, "deps": list(deps)})
    return {"state": {"status": state}, "steps": rows}


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


def test_pending_steps_behind_a_parked_dependency_settle():
    """The second measured regression, on the mail-gate case: the first step parked on a
    CEO question and the two behind it stayed `pending` because their dependency never
    finished. The coordinator logged `no actionable step in any open task` for 14 minutes;
    the case failed on the clock with every assertion satisfied. A pending step that
    nothing but the CEO can unblock is as stopped as the step it waits on."""
    assert is_settled(_status(
        "open",
        ("read_emails", "waiting_clarify", []),
        ("build_table", "pending", ["read_emails"]),
        ("finalize_report", "pending", ["read_emails", "build_table"]),
    ))


def test_a_pending_step_whose_dependencies_are_all_done_does_NOT_settle():
    """Blocked-by-parked is not blocked-by-anything: a pending step whose deps have all
    finished will be spawned on the next tick, so the task is still moving."""
    assert not is_settled(_status(
        "open",
        ("ask", "waiting_clarify", []),
        ("gather", "done", []),
        ("write", "pending", ["gather"]),
    ))


def test_a_pending_step_with_no_dependencies_does_NOT_settle():
    assert not is_settled(_status("open", ("ask", "waiting_clarify", []), ("free", "pending", [])))


def test_a_pending_step_behind_a_running_dependency_does_NOT_settle():
    assert not is_settled(_status(
        "open",
        ("ask", "waiting_clarify", []),
        ("gather", "running", []),
        ("write", "pending", ["gather"]),
    ))


def test_no_steps_never_settles():
    """A task with no rows yet has not been planned; `all([])` is vacuously True, so
    without an explicit guard an empty plan would look settled."""
    assert not is_settled(_status("open"))


def test_every_full_lifecycle_journey_case_is_marked_live_slow():
    """`docs/releasing.md` sells `-m "live and not live_slow"` as the QUICK pre-release
    subset. That promise only holds if every case driving a whole task lifecycle actually
    carries the marker, and nothing enforced it.

    Measured: all nine `test_live_journey_*` cases carried no marker at all, so each one —
    booting a real fleet, polling to a settled state, and in J5 hard-killing and rebooting
    a process — sat inside the "quick" subset. Whoever trusted the doc got a subset that
    was minutes and real money more expensive than advertised.

    Collect the marker from the modules themselves rather than restating a list here, so
    a journey case added later is covered the day it lands instead of the day someone
    remembers to update this test.
    """
    import importlib
    import pkgutil

    import tests.fullflow_live as live_pkg

    unmarked = []
    for mod_info in pkgutil.iter_modules(live_pkg.__path__):
        if not mod_info.name.startswith("test_live_journey_"):
            continue
        module = importlib.import_module(f"{live_pkg.__name__}.{mod_info.name}")
        for attr in dir(module):
            if not attr.startswith("test_"):
                continue
            fn = getattr(module, attr)
            marks = getattr(fn, "pytestmark", [])
            if not any(m.name == "live_slow" for m in marks):
                unmarked.append(f"{mod_info.name}::{attr}")

    assert not unmarked, (
        "these full-lifecycle journey cases are missing @pytest.mark.live_slow, so they "
        "fall into the pre-release QUICK subset that docs/releasing.md defines as "
        f"`-m \"live and not live_slow\"`: {sorted(unmarked)}"
    )
