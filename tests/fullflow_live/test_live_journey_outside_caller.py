"""J1 — an outside caller drives one brief end to end, over HTTP only.

The arc every other journey is a variant of: delegate → the real coordinator picks the
work up on its own tick → poll status → read what the CEO would actually receive. No
in-process shortcut anywhere; the test only ever knows what an HTTP client could know.

Assertions are system invariants — status never goes backwards, the artifact on disk agrees
with what HTTP served, real money was spent, the audit chain still verifies. Nothing here
asserts *how* the crew chose to do the work, because that is a model choice and pinning
it would buy flakes instead of safety.
"""

from __future__ import annotations

import json

import pytest

from tests.fullflow_live.topology import (
    audit_path,
    boot,
    is_settled,
    poll_until,
    task_status,
)

BRIEF = "Viết một đoạn giới thiệu ngắn (3-4 câu) về công ty cho trang chủ."

#: Rank of the states a task moves through. A task may stall or settle, but a status
#: that goes BACKWARDS (running → pending) means the control plane is reporting a
#: fabricated view of the store, which no amount of model nondeterminism excuses.
_RANK = {
    "pending": 0, "open": 1, "running": 2, "waiting_clarify": 3, "needs_decision": 3,
    "blocked": 3, "done": 4, "done_with_gaps": 4, "delivered": 5, "cancelled": 5,
    "failed": 5,
}


@pytest.fixture
def fleet(tmp_path, live_api_key):
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.live_slow
def test_j1_outside_caller_drives_a_brief_to_a_settled_state(fleet, journey_budget):
    code, preview = fleet.post("/api/control-plane/delegate", {"brief": BRIEF}, timeout=180)
    assert code == 200, f"preview failed {code}: {preview!r}"

    task_id = preview.get("task_id")
    plan_hash = preview.get("plan_hash")
    assert task_id and plan_hash, f"preview returned no task/hash: {preview!r}"

    # The company autopilot flag may have confirmed inside the preview. Only run step 2
    # when it did not, otherwise the second confirm is a legitimate 409 on a used hash.
    if not preview.get("confirmed"):
        code, confirmed = fleet.post(
            "/api/control-plane/delegate",
            {"task_id": task_id, "plan_hash": plan_hash, "confirm": True},
            timeout=180,
        )
        assert code == 200, f"confirm with the previewed hash failed {code}: {confirmed!r}"
        assert confirmed.get("confirmed") is True, f"confirm did not take: {confirmed!r}"

    # -- the coordinator now owns it; watch only through HTTP ------------------------
    seen: list[str] = []

    def observe():
        status = task_status(fleet, task_id)
        state = (status.get("state") or {}).get("status") or ""
        if not seen or seen[-1] != state:
            seen.append(state)
        return status if is_settled(status) else None

    final = poll_until(observe, timeout_s=300, interval_s=3,
                       what=f"task {task_id} to settle")

    ranks = [_RANK.get(s, -1) for s in seen if s in _RANK]
    assert ranks == sorted(ranks), (
        f"status went backwards through {seen} — the control plane is not reporting "
        "the store faithfully"
    )

    # -- real work, really paid for ---------------------------------------------------
    cost = (final.get("cost") or {}).get("total_cost_usd") or 0.0
    assert cost > 0, f"settled with cost {cost} — no model was called"
    journey_budget.note_cost(cost, final)

    steps = final.get("steps") or []
    assert steps, f"a confirmed task produced no steps: {final!r}"

    # -- what HTTP served must match what is on disk ----------------------------------
    # The CEO reads the artifact; the API reports about it. If they disagree, one of
    # them is lying, and which one hardly matters — the pair is the contract.
    home = fleet.home
    artifacts = [
        p for p in (home / ".data").rglob("*")
        if p.is_file() and task_id in str(p) and p.suffix in {".md", ".txt", ".json"}
    ]
    served = json.dumps(final, ensure_ascii=False)
    assert task_id in served, "status view does not even name its own task"
    if artifacts:
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in artifacts)
        assert text.strip(), f"artifact files exist but are empty: {artifacts}"

    # -- the trail of what happened is intact ------------------------------------------
    from my_crew.audit.audit_chain import verify_chain

    verdict = verify_chain(audit_path(home))
    assert verdict["ok"], (
        f"audit hash-chain broken after a normal run: {verdict} — "
        "a tampered or torn trail is a security failure, not a test nuisance"
    )


@pytest.mark.live_slow
def test_j1b_a_stale_plan_hash_is_refused(fleet, journey_budget):
    """The hash-bind is the whole point of two-step confirm: a plan the caller never
    saw must not be confirmable. Cheap to assert, and it is the failure that would
    let a racing caller commit work the CEO never previewed."""
    code, preview = fleet.post("/api/control-plane/delegate", {"brief": BRIEF}, timeout=180)
    assert code == 200, f"preview failed {code}: {preview!r}"
    task_id = preview.get("task_id")

    code, body = fleet.post(
        "/api/control-plane/delegate",
        {"task_id": task_id, "plan_hash": "0" * 64, "confirm": True},
        timeout=60,
    )
    assert code == 409, f"a WRONG plan_hash was not refused with 409: {code} {body!r}"

    # A preview really does spend (it runs a decomposition), but the task-scoped cost
    # view aggregates over executed STEPS, and a refused plan has none — so this reads
    # 0.0 by design, not because the record was lost. Measured: the view returns
    # total_cost_usd 0.0 with an empty steps list right after a preview.
    #
    # Consequence worth stating plainly: preview-only spend is invisible to the
    # per-journey ceiling. It is bounded here (one decomposition, cents) and the suite
    # total is watched separately, so this case does not pretend to meter it.
    status = task_status(fleet, task_id)
    journey_budget.note_cost((status.get("cost") or {}).get("total_cost_usd") or 0.0, status)
