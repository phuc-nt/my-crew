"""J5 — SIGKILL mid-task, then reboot onto the same home.

The crash this models is the realistic one: no SIGTERM, no shutdown hook, no chance to
flush anything. The laptop lid closes, the OOM killer fires, the container is evicted.
Whatever is on disk at that instant is the entire state of the company.

Two questions, neither answerable without really killing a real process:

1. **Does the work survive?** The task, its route, and its spend must still be there
   after a reboot. A store that loses a paid-for task on a hard kill is losing the
   CEO's money and the record of what was done with it.
2. **Does the new fleet finish it?** A task left mid-flight must be picked up and driven
   to a settled state. Surviving in the store but never moving again is the worse
   failure of the two: it looks fine on the dashboard and silently never completes.

Measured behaviour this pins (probed before it was asserted): a step SIGKILLed while
`running` stays `running` on disk — correct, since no process remained alive to write
anything else — and the rebooted coordinator takes it from there.
"""

from __future__ import annotations

import time

import pytest

from tests.fullflow_live.topology import (
    boot,
    is_settled,
    poll_until,
    task_status,
)

BRIEF = "Viết đoạn 3 câu giới thiệu công ty cho trang chủ."


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def test_j5_work_survives_a_hard_kill_and_the_next_fleet_finishes_it(home, live_api_key,
                                                                     journey_budget):
    first = boot(home, api_key=live_api_key)
    task_id = None
    try:
        code, body = first.post(
            "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=180
        )
        assert code == 200, f"delegate failed {code}: {body!r}"
        task_id = body.get("task_id")
        assert task_id, f"delegate returned no task_id: {body!r}"

        # Kill only once work is genuinely IN FLIGHT. Killing during `pending` would
        # test nothing interesting — the interrupted-mid-write case is the whole point.
        def a_step_is_running():
            status = task_status(first, task_id)
            steps = status.get("steps") or []
            if any(s.get("status") == "running" for s in steps):
                return status
            return None

        poll_until(a_step_is_running, timeout_s=120, interval_s=2,
                   what="a step to reach running before the kill")
    finally:
        # SIGKILL the whole process group: no handler runs, nothing is flushed.
        first.kill_hard()

    time.sleep(2)
    assert first.proc.poll() is not None, (
        "the fleet survived SIGKILL — this case cannot test crash recovery if the "
        "process is still running and still writing to the same home"
    )

    # -- reboot onto the SAME home, exactly as an operator restarting the service ------
    second = boot(home, api_key=live_api_key, seed=False)
    try:
        # 1. The work is still there. Read through the new process's HTTP surface, not
        #    off disk: what matters is that the restarted system can SEE it.
        status = task_status(second, task_id)
        assert status.get("task_id") == task_id, (
            f"the rebooted fleet cannot find task {task_id} — a paid-for task was lost "
            f"to a hard kill: {status!r}"
        )
        steps_after_reboot = status.get("steps") or []
        assert steps_after_reboot, (
            f"task {task_id} came back with no steps — the plan was lost even though "
            "the task row survived"
        )

        # 2. And the new fleet drives it to completion. Surviving but never moving is
        #    the failure that hides: the dashboard looks healthy forever.
        final = poll_until(
            lambda: (lambda s: s if is_settled(s) else None)(task_status(second, task_id)),
            timeout_s=300, interval_s=3,
            what=f"the rebooted fleet to settle recovered task {task_id}",
        )

        cost = (final.get("cost") or {}).get("total_cost_usd") or 0.0
        assert cost > 0, (
            f"recovered task settled having spent {cost} — the spend record from before "
            "the crash was lost, so the company cannot account for money it paid"
        )
        journey_budget.note_cost(cost)

        # 3. Recovery did not proceed by swallowing exceptions on every tick.
        #
        # Two errors are expected in THIS environment and are excluded by name rather
        # than by widening the check, because both were traced to a cause and neither is
        # about crash recovery:
        #
        # - `milestone-mirror`: cannot open its cursor DB, because `.data/agents/<id>/`
        #   does not exist and `sqlite3.connect` will not create a missing parent.
        #   Measured: a clean fleet that was never killed logs it identically.
        # - `done fast-path send failed`: on completion the coordinator tries to Telegram
        #   the operator, and this harness seeds a deliberately fake bot token so a test
        #   run can never message a real person. The product treats the failure as
        #   non-fatal on purpose (the mirror still delivers). Excluding it is therefore
        #   excluding the test's own sandbox, not a product defect — and it appears only
        #   when the task actually reaches `done`, which is why this case passed
        #   intermittently before the cause was found.
        #
        # Anything else from the tick loop is a real recovery failure and fails here.
        expected_in_sandbox = ("milestone-mirror", "done fast-path send failed")
        log = second.log()
        recovery_failures = [
            line for line in log.splitlines()
            if ("team-tick" in line or "team_tick_runner" in line
                or "coordinator" in line.lower())
            and ("Traceback" in line or "ERROR" in line)
            and not any(known in line for known in expected_in_sandbox)
        ]
        assert not recovery_failures, (
            "the rebooted fleet's coordinator is erroring while handling the recovered "
            "task:\n" + "\n".join(recovery_failures[:20])
        )
    finally:
        second.stop()
