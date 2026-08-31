"""J4 — several briefs in one session: the offline predictor agrees, and work stays apart.

Two invariants, both of which need a real fleet to mean anything.

**The bridge.** `routing_bench.decide` re-implements the live routing chain so the
router can be scored offline, at zero model cost, inside an old tag's worktree. Its own
docstring states the contract that makes that legitimate: the offline decision and the
`route_json` written during a real run "phải nói cùng một thứ tiếng". Nothing enforced
it. A drift between the two would not turn any test red — it would quietly make every
release comparison a measurement of the copy instead of the product. So this case runs
briefs through a REAL delegate and asserts the stored route matches the prediction.

**No cross-talk.** Multiple tasks live in one home, one store, one artifact root. If
task A's output can land in task B's directory, the CEO reads the wrong deliverable and
nothing anywhere reports an error. Asserted by giving each brief a sentinel that could
not appear in the other's work.

Briefs are deliberately short and cheap. The point is which lane the router picks and
where the bytes land — not the quality of the prose, which the judge benchmark scores.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.fullflow_live.topology import boot, is_settled, poll_until, task_status

#: (label, brief). Chosen to cover BOTH prediction sources — `heuristic` (the router
#: guesses) and `prefix` (the CEO forces a lane) — because a bridge that only holds for
#: the guessing path would miss any drift in prefix handling entirely.
BRIEFS = (
    ("heuristic_sprint", "Viết đoạn giới thiệu 3 câu về công ty cho trang chủ."),
    ("prefix_team", "team: Viết đoạn giới thiệu 3 câu về công ty."),
)


@pytest.fixture
def fleet(tmp_path, live_api_key):
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        yield server
    finally:
        server.stop()


def _stored_route(home, task_id: str) -> dict:
    db = home / ".data" / "team_tasks.sqlite3"
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT route_json FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row and row[0] else {}


@pytest.mark.live_slow
def test_j4_the_offline_router_predicts_what_the_live_fleet_actually_stores(fleet):
    """The bridge. Predict offline, run live, compare the fields the bench compares."""
    from my_crew.bench.routing_bench import decide

    for label, brief in BRIEFS:
        predicted_mode, predicted_source, _reason, predicted_signals = decide(brief)

        code, body = fleet.post(
            "/api/control-plane/delegate", {"brief": brief}, timeout=180
        )
        assert code == 200, f"[{label}] preview failed {code}: {body!r}"
        task_id = body.get("task_id")
        assert task_id, f"[{label}] preview returned no task_id: {body!r}"

        route = _stored_route(fleet.home, task_id)
        assert route, f"[{label}] live run stored no route_json for {task_id}"

        # `mode` and `source` are two of the four axes `compare_routing` scores between
        # releases. If the live system disagrees with the predictor on either, the
        # offline benchmark is measuring its own copy of the logic, not the product.
        assert route.get("mode") == predicted_mode, (
            f"[{label}] routing bench predicted mode={predicted_mode!r} but the live "
            f"fleet stored {route.get('mode')!r} — the offline benchmark has drifted "
            "from the real routing chain, so its release comparisons are worthless"
        )
        assert route.get("source") == predicted_source, (
            f"[{label}] predicted source={predicted_source!r}, live stored "
            f"{route.get('source')!r} — same drift, one field over"
        )

        # `signals` carries the thresholds. A threshold edit usually moves a signal
        # before it flips a decision, so comparing them catches drift a release early.
        #
        # Subset, not equality, and the distinction is the product's design rather than
        # a loosened assertion: `route_signals` is computed from the BRIEF, while a team
        # route additionally records `boundary_counts` — the boundary distribution of the
        # ACCEPTED PLAN (`_team_route` in ops_assign_team_task). That key cannot exist
        # offline, because producing it requires running a decomposition, and the whole
        # premise of the routing bench is costing zero model calls. Measured: the live
        # `prefix_team` route stored exactly the four predicted signals plus
        # `boundary_counts: {specialization: 1}`.
        #
        # So the invariant with teeth is: every key the predictor DOES produce must
        # match. Extra plan-derived keys live-side are expected; a differing value on a
        # shared key is the drift this case exists to catch.
        live_signals = route.get("signals")
        if live_signals is not None:
            shared = {k: live_signals.get(k) for k in predicted_signals}
            assert shared == predicted_signals, (
                f"[{label}] signals differ on a shared key — predicted "
                f"{predicted_signals!r}, live stored {shared!r} (full: {live_signals!r}); "
                "a threshold moved on one side only"
            )


@pytest.mark.live_slow
def test_j4b_concurrent_tasks_do_not_cross_contaminate_their_artifacts(fleet):
    """Two briefs in flight at once must not write into each other's artifacts.

    Each brief carries a sentinel word that has no reason to appear in the other's
    output. Finding one in the wrong task's directory means the artifact path is keyed
    on something that is not the task id — the failure mode where the CEO opens a
    deliverable and reads someone else's work, with nothing logged as wrong.
    """
    marks = {
        "ALPHAMARK7391": "Viết đúng một câu chứa chính xác từ khoá ALPHAMARK7391.",
        "BETAMARK5127": "Viết đúng một câu chứa chính xác từ khoá BETAMARK5127.",
    }

    task_ids: dict[str, str] = {}
    for mark, brief in marks.items():
        code, body = fleet.post(
            "/api/control-plane/delegate", {"brief": brief, "confirm": True}, timeout=180
        )
        assert code == 200, f"[{mark}] delegate failed {code}: {body!r}"
        assert body.get("task_id"), f"[{mark}] no task_id: {body!r}"
        task_ids[mark] = body["task_id"]

    assert len(set(task_ids.values())) == 2, (
        f"two delegates produced the same task id: {task_ids} — the ids are not unique, "
        "which alone would make every per-task path collide"
    )

    for mark, task_id in task_ids.items():
        poll_until(
            lambda tid=task_id: (lambda s: s if is_settled(s) else None)(
                task_status(fleet, tid)
            ),
            timeout_s=300, interval_s=3, what=f"[{mark}] task {task_id} to settle",
        )

    # Read every file under each task's own directory and check the OTHER task's
    # sentinel never appears there.
    data = fleet.home / ".data"
    for mark, task_id in task_ids.items():
        others = [m for m in marks if m != mark]
        own_files = [p for p in data.rglob("*") if p.is_file() and task_id in str(p)]
        blob = "\n".join(
            p.read_text(encoding="utf-8", errors="replace") for p in own_files
        )
        for other in others:
            assert other not in blob, (
                f"task {task_id} (sentinel {mark}) contains another task's sentinel "
                f"{other} — artifacts are crossing between tasks, so a CEO reading one "
                "deliverable may be reading a different task's work"
            )
