"""J2 — an escalation task runs to completion inside a REAL fleet.

Scope note, stated up front because it bounds what this file can honestly claim:
`escalate_to_manager` currently has **no production call site**. Grepped: the only
non-test references are two comments and `is_escalation_origin`, which the ticker uses
as a recursion brake. Its intended caller is the customer digital-assistant, which the
CEO deferred out of this round. So there is no way to make a running fleet escalate by
talking to it over HTTP, and a journey that pretended otherwise would be theatre.

What this file therefore does: mint the escalation the way its real caller will — the
same function, in its own process, pointed at the RUNNING fleet's home — then let the
live coordinator in a third process pick it up and run it for real. Only the trigger is
synthetic; everything after it (dispatch, execution, the recursion brake, what the
control plane reports) is the real system across a real socket. That is a strictly
larger surface than the in-process suite covers, and the gap is named rather than hidden.

The H1 regression guard is the reason this is worth running live at all: a task's route
`source` must survive the whole lifecycle, including a dead end.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from tests.fullflow_live.topology import boot, is_settled, poll_until, task_status

MANAGER_ID = "secretary"  # a real worker in the seeded roster
SOURCE_TAG = "customer_assistant"


@pytest.fixture
def fleet(tmp_path, live_api_key):
    """A fleet whose company.yaml names a manager, so escalation has somewhere to go."""
    home = tmp_path / "home"
    from tests.fullflow_live.topology import seed_home

    seed_home(home, api_key=live_api_key)
    company = home / "company.yaml"
    company.write_text(
        company.read_text(encoding="utf-8") + f"manager_id: {MANAGER_ID}\n",
        encoding="utf-8",
    )
    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


_MINT_SCRIPT = """
import json, sys
from my_crew.runtime.company import load_company
from my_crew.runtime.manager_escalation import escalate_to_manager

payload = json.loads(sys.argv[1])
task_id = escalate_to_manager(
    source=payload["source"],
    summary=payload["summary"],
    context_ref=payload["context_ref"],
    origin_route=payload["origin_route"],
    company=load_company(),
)
print(json.dumps({"task_id": task_id}))
"""


def _mint_escalation(home, *, summary: str, origin_route=None) -> str | None:
    """Mint via the real function, in a SUBPROCESS pointed at the fleet's home.

    A subprocess rather than an in-process import because `MY_CREW_HOME` is read at
    import time and fans out into several module-level constants (`DATA_DIR`,
    `team_tasks_root`, ...). Re-pointing the env and reloading modules in this process
    would depend on reloading every one of them in the right order; miss a single
    binding and the escalation is written into the developer's own `.data/` instead of
    the tmp home. The process boundary makes that class of mistake impossible, and it
    is also how the real caller will run: a fresh process with the env already set.
    """
    env = dict(os.environ)
    env["MY_CREW_HOME"] = str(home)
    payload = json.dumps({
        "source": SOURCE_TAG, "summary": summary,
        "context_ref": "j2-journey", "origin_route": origin_route,
    })
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", _MINT_SCRIPT, payload],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"minting the escalation failed rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])["task_id"]


def _route_row(home, task_id: str) -> dict:
    """Read route_json straight from the store the fleet writes.

    Necessary because the HTTP view allowlists route fields down to
    (mode, source, reason) — `origin`, the recursion marker, is deliberately not
    exposed. So `source` is asserted through HTTP (the contract an outside caller
    sees) and `origin` on disk (the invariant the brake depends on).
    """
    db = home / ".data" / "team_tasks.sqlite3"
    con = sqlite3.connect(db)
    try:
        cur = con.execute("SELECT route_json FROM team_tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return {}
    return json.loads(row[0])


def test_j2_an_escalation_runs_in_a_real_fleet_and_keeps_its_source(fleet, journey_budget):
    task_id = _mint_escalation(
        fleet.home,
        summary="Khách yêu cầu hoàn tiền vượt thẩm quyền của trợ lý, cần người phụ trách quyết.",
    )
    assert task_id, "escalation with a configured manager must mint a task"

    # The control plane — a separate process — must see work it did not mint itself.
    status = task_status(fleet, task_id)
    assert status.get("task_id") == task_id

    final = poll_until(
        lambda: (lambda st: st if is_settled(st) else None)(task_status(fleet, task_id)),
        timeout_s=300, interval_s=3,
        what=f"escalation task {task_id} to settle in the live fleet",
    )

    # H1 regression guard: `source` must survive the entire lifecycle. It was once
    # overwritten when a task hit a dead end, which silently erased where an
    # escalation came from — exactly the field an operator needs when triaging one.
    served_source = (final.get("route") or {}).get("source") or ""
    assert served_source == SOURCE_TAG, (
        f"route source is {served_source!r}, expected {SOURCE_TAG!r} — the origin tag "
        "was overwritten during the task's lifecycle (H1 regression)"
    )

    route = _route_row(fleet.home, task_id)
    assert route.get("origin") == "escalation", (
        f"escalation marker missing from the stored route: {route!r} — without it the "
        "recursion brake cannot recognise this task"
    )

    steps = final.get("steps") or []
    assert len(steps) == 1, f"an escalation is a ONE-step vehicle, got {len(steps)}: {steps}"

    journey_budget.note_cost((final.get("cost") or {}).get("total_cost_usd") or 0.0)


def test_j2b_an_escalation_task_cannot_escalate_again(fleet, journey_budget):
    """The recursion brake, asserted structurally rather than by trusting the model.

    Without it, a manager task that itself stalls could mint another manager task,
    and so on — a loop that spends real money on every iteration.

    Note the third call. `escalate_to_manager` returns None down FOUR different paths
    (recursion guard, manager not roster-assignable, daily cap, unreadable company),
    so `second is None` on its own is not evidence the brake fired — measured: with
    `manager_id` silently resolving to `coordinator`, every call returns None and this
    case still goes green with the brake deleted. The delegate-origin control below
    fails in exactly that scenario, which is what makes the None above mean something.
    """
    first = _mint_escalation(fleet.home, summary="Việc vượt thẩm quyền lần một.")
    assert first, "this case needs one successful escalation to build on"

    origin_route = _route_row(fleet.home, first)
    assert origin_route.get("origin") == "escalation", origin_route

    second = _mint_escalation(
        fleet.home,
        summary="Cố escalate lần nữa từ chính task escalation.",
        origin_route=origin_route,
    )
    assert second is None, (
        f"an escalation task escalated AGAIN (minted {second}) — the recursion brake "
        "is not holding, and each hop costs real money"
    )

    # Control: a task that came from somewhere OTHER than an escalation must still be
    # able to escalate. This pins the brake to `origin == "escalation"` rather than to
    # "an origin_route was supplied", and proves minting was live for this whole case.
    from_delegate = _mint_escalation(
        fleet.home,
        summary="Việc thường vượt thẩm quyền, cần người phụ trách quyết.",
        origin_route={"origin": "delegate", "source": "ceo"},
    )
    assert from_delegate, (
        "a NON-escalation origin was also refused — minting is broken for an unrelated "
        "reason, so the None above proves nothing about the recursion brake"
    )

    journey_budget.note_cost(0.0)
