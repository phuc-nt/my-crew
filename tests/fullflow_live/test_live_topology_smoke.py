"""T1–T3 — the real fleet boots, works over a real socket, and honours auth.

These three prove the harness itself before any journey leans on it. If T1 is red,
every journey failure below it is uninterpretable: you cannot tell a routing bug from a
fleet that never started. So the smokes assert boot, work, and auth separately.

Real model calls, real processes, real HTTP. No mocks anywhere.
"""

from __future__ import annotations

import json
import secrets

import pytest

from tests.fullflow_live.topology import boot, poll_until

#: Task-level states from which an UNATTENDED fleet will not move on its own.
#:
#: `waiting_clarify` belongs here, and finding that out is one of the things this
#: topology bought: measured live, a plain "write me a paragraph" brief ran the writer,
#: spent real money, then parked asking the CEO a question. With nobody at the keyboard
#: it waits forever — correct product behaviour, but it means "terminal" for an
#: unattended run is *settled*, not *finished*. Treating only done/failed as terminal
#: made T2 time out at 300s against a system that was working exactly as designed.
SETTLED_TASK_STATES = {
    "done", "delivered", "cancelled", "failed", "blocked", "needs_decision",
}
#: Step-level states that mean the same thing one level down: the step is parked on a
#: human, so the task above it will sit at `open` indefinitely.
SETTLED_STEP_STATES = {"waiting_clarify", "needs_decision", "blocked"}


@pytest.fixture
def fleet(tmp_path, live_api_key):
    """A booted fleet in its own home, torn down (and orphan-checked) after the test."""
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        yield server
    finally:
        server.stop()
        assert server.proc.poll() is not None, (
            "serve survived SIGTERM — a leaked supervisor would keep writing to the "
            "test home and poison the next case"
        )


def test_t1_fleet_boots_serves_health_and_ticks(fleet):
    """Boot → /health → the coordinator's real loop is actually running.

    Health alone is a weak signal: it proves the web child is up while the scheduler
    child may have crashed on import, and `serve` only notices when a child *exits*.
    So this also waits for evidence the tick loop ran — the thing every journey depends on.
    """
    status, body = fleet.get("/health")
    assert status == 200, f"/health returned {status}: {body!r}"

    # Overview is served by the same process but reads the store the scheduler writes,
    # so a 200 here means the two halves agree on one home.
    status, overview = fleet.get("/api/control-plane/overview")
    assert status == 200, f"overview returned {status}: {overview!r}"
    assert "coordinator_ok" in json.dumps(overview), f"unexpected overview shape: {overview!r}"

    # Proof the scheduler child is LOOPING, not merely spawned. Deliberately not the
    # supervisor's own "running web, scheduler" banner, nor the one-shot "service
    # started" line: both print before the loop does any work, so a scheduler that
    # crashed on its first iteration would still satisfy them. The loop emits a
    # per-tick reaper line, so requiring the count to GROW is the honest signal.
    def ticked_twice():
        occurrences = fleet.log().count("sandbox reaper")
        return occurrences if occurrences >= 2 else None

    poll_until(
        ticked_twice, timeout_s=30, interval_s=1,
        what="the scheduler loop to complete at least two ticks",
    )

    log = fleet.log()
    assert "service started; tick interval 2s" in log, (
        f"MY_CREW_TICK_INTERVAL_S did not reach the scheduler child:\n{log}"
    )
    assert "Traceback" not in log, f"a child raised during boot:\n{log}"


def test_t2_work_delegated_over_real_http_runs_and_settles(fleet, journey_budget):
    """The journey v2 could not run: HTTP in, real coordinator, real model, cost out.

    Asserts system invariants only — that the task settles and that real money was
    spent. NOT which agent got it, how many steps it took, or whether it finished
    versus stopped to ask; those are model choices and asserting them buys flakes,
    not safety.
    """
    status, body = fleet.post(
        "/api/control-plane/delegate",
        {"brief": "Viết một đoạn 3 câu giới thiệu công ty cho trang chủ.", "confirm": True},
        timeout=180,
    )
    assert status == 200, f"delegate returned {status}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"
    assert body.get("confirmed") is True, f"one-step confirm did not take: {body!r}"

    def settled():
        code, status_body = fleet.get(f"/api/control-plane/tasks/{task_id}", timeout=30)
        if code != 200:
            return None
        state = (status_body.get("state") or {}).get("status")
        if state in SETTLED_TASK_STATES:
            return status_body
        steps = status_body.get("steps") or []
        if steps and all(s.get("status") in SETTLED_STEP_STATES for s in steps):
            return status_body
        return None

    final = poll_until(
        settled, timeout_s=300, interval_s=3,
        what=f"task {task_id} to settle (finished, or parked awaiting the CEO)",
    )

    state = final["state"]["status"]
    step_states = [s.get("status") for s in (final.get("steps") or [])]
    assert state in SETTLED_TASK_STATES or all(
        s in SETTLED_STEP_STATES for s in step_states
    ), f"task did not settle: state={state!r} steps={step_states!r}"
    # A run that cost nothing did not call a model — the whole point of a live suite.
    total = (final.get("cost") or {}).get("total_cost_usd") or 0.0
    assert total > 0, f"task finished with cost {total} — no real model call happened"
    journey_budget.note_cost(total)


def test_t3_auth_on_blocks_anonymous_and_admits_a_real_login(tmp_path, live_api_key):
    """With a password hash set, the control plane is closed until a real login.

    v2 never covered this: calling handlers directly skips the auth middleware
    entirely, so an auth regression would have been invisible to the whole suite.
    """
    import bcrypt

    password = "topology-smoke-pw"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    server = boot(
        tmp_path / "home",
        api_key=live_api_key,
        env_overrides={
            "WEB_AUTH_PASSWORD_HASH": hashed,
            # Auth-on without a session secret is refused at boot (a forgeable cookie
            # is worse than no auth at all) — a real guard, measured here. Generated
            # per-run rather than hardcoded so no fixed secret enters the repo.
            "WEB_SESSION_SECRET": secrets.token_hex(32),
        },
    )
    try:
        # /health stays public by design — it is how a supervisor probes liveness.
        assert server.get("/health")[0] == 200

        code, body = server.get("/api/control-plane/overview")
        assert code in (401, 403), (
            f"control plane answered {code} with NO session — auth is not enforced: {body!r}"
        )

        # Login takes username + password; the username defaults to "admin".
        # Only ONE bad attempt: /api/login is rate-limited per client IP, and a test
        # that burns the budget would get 429s instead of the 401 it means to assert.
        code, body = server.post(
            "/api/login", {"username": "admin", "password": "wrong-password"}
        )
        assert code in (401, 403), f"a wrong password was accepted ({code}): {body!r}"

        code, body = server.post("/api/login", {"username": "admin", "password": password})
        assert code == 200, f"real login failed ({code}): {body!r}"

        code, body = server.get("/api/control-plane/overview")
        assert code == 200, f"control plane still closed after a valid login: {code} {body!r}"
    finally:
        server.stop()
