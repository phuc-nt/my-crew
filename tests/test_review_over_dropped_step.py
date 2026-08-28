"""A dropped step must never be reviewed — in any autonomy band, at any round.

Found live (lanes9 bench): the coordinator's skip-with-gap dropped a stuck research
step, but its author sat in the SUPERVISED band, whose review gate used to return True
unconditionally — ignoring the `needs_review = 0` that `mark_step_dropped` writes for
exactly this reason. A review was minted over the placeholder; the drop had also
retired the attempt lease (`attempt_id = NULL`), so the review locked version `""`
against an artifact keeping the pre-drop version — a mismatch no re-review can clear.
The verdict-None re-mint path then spun fresh reviews at the same round until the
task's review budget stalled a task whose content steps were ALL done, delivering
nothing.

Two guards under test: `effective_needs_review` refuses a dropped step before the band
read, and `maybe_handle_review_done` ends (never re-mints) a review chain whose parent
was dropped after the review was minted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.ops_stalled_task import drop_step_with_placeholder
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.band_store import BAND_SUPERVISED, BandStore
from my_crew.runtime.team_task_steps import is_dropped_step
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_data_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 999,
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        roster_ok=lambda agent_id: True,
        aggregate=lambda task: ("done summary", 0.01),
        deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def _dropped_single_step_task(store) -> None:
    """One-step plan whose step ran, self-checked out to needs_decision, and got
    dropped through the real shared primitive — the exact lanes9 shape."""
    steps = [
        {"step_id": "s1", "title": "nghiên cứu thị trường", "assigned_to": "agent-a",
         "deps": [], "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo", original_request="làm demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", outcome_ref="x", cost_usd=0.0)
    task = store.get("t1")
    step = next(s for s in task.steps if s.step_id == "s1")
    assert drop_step_with_placeholder(store, task, step, reason="tra cứu bất khả thi")


def _supervise(agent_id: str) -> None:
    band = BandStore()
    band.set(agent_id, BAND_SUPERVISED, reason="t", changed_by="ceo")
    band.close()


def test_is_dropped_step_is_exactly_the_retired_lease_signature(tmp_path):
    store = _store(tmp_path)
    _dropped_single_step_task(store)
    dropped = next(s for s in store.get("t1").steps if s.step_id == "s1")
    assert dropped.status == "done" and not dropped.attempt_id
    assert is_dropped_step(dropped)
    # a worker-delivered done keeps its attempt — never reads as dropped
    assert not is_dropped_step(
        SimpleNamespace(status="done", attempt_id="a1b2"))
    # not-yet-terminal rows never read as dropped, leased or not
    assert not is_dropped_step(SimpleNamespace(status="needs_decision", attempt_id=None))
    assert not is_dropped_step(SimpleNamespace(status="pending", attempt_id=None))


def test_supervised_band_never_reviews_a_dropped_step(tmp_path):
    """The lanes9 mint hole: supervised used to outrank the drop's needs_review=0."""
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    store = _store(tmp_path)
    _dropped_single_step_task(store)
    _supervise("agent-a")
    task = store.get("t1")
    dropped = next(s for s in task.steps if s.step_id == "s1")
    assert effective_needs_review(task, dropped) is False
    # control: the band still forces a review on a genuinely delivered step
    delivered = SimpleNamespace(
        step_id="s2", assigned_to="agent-a", needs_review=False, deps=(),
        external_write=False, status="done", attempt_id="w0rk", step_type="work")
    assert effective_needs_review(task, delivered) is True


def test_tick_aggregates_a_dropped_supervised_step_instead_of_minting_review(
    tmp_path, monkeypatch,
):
    import my_crew.agent.team_task_roster as roster_mod

    store = _store(tmp_path)
    _dropped_single_step_task(store)
    _supervise("agent-a")
    # a reviewer IS available — the no-peer review-skip path must not be what saves us
    monkeypatch.setattr(roster_mod, "assignable_staff",
                        lambda: [("agent-a", "pm"), ("agent-qa", "pm")])

    result = run_one_tick(_deps(store))

    assert result.action == "aggregated"
    task = store.get("t1")
    assert [s for s in task.steps if s.step_type == "review"] == []
    assert task.status == "done"


def test_a_review_minted_before_the_drop_ends_instead_of_reminting_forever(
    tmp_path, monkeypatch,
):
    """Mid-flight shape: the review row exists, its parent then got dropped, the
    reviewer run wrote no verdict (stale artifact). The old verdict-None path minted
    a fresh review at the same round every tick until the budget stalled the task."""
    import my_crew.agent.team_task_roster as roster_mod

    store = _store(tmp_path)
    _dropped_single_step_task(store)
    store.insert_step("t1", {
        "step_id": "s1-review-0-0", "title": "Soát chéo: nghiên cứu thị trường",
        "assigned_to": "agent-qa", "deps": ["s1"], "step_type": "review",
        "parent_step_id": "s1", "review_round": 0,
    })
    store.reserve_step("t1", "s1-review-0-0")
    # review finishes with NO verdict artifact — exactly what a stale-artifact
    # reviewer run leaves behind
    review_attempt = next(
        s.attempt_id for s in store.get("t1").steps if s.step_id == "s1-review-0-0")
    store.mark_done("t1", "s1-review-0-0", outcome_ref="x", cost_usd=0.0,
                    attempt_id=review_attempt)
    monkeypatch.setattr(roster_mod, "assignable_staff",
                        lambda: [("agent-a", "pm"), ("agent-qa", "pm")])

    result = run_one_tick(_deps(store))

    assert result.action == "aggregated"
    task = store.get("t1")
    reviews = [s for s in task.steps if s.step_type == "review"]
    assert len(reviews) == 1  # no fresh mint — the chain ended at the dropped parent
    assert [s for s in task.steps if s.step_type == "rework"] == []
    assert task.status == "done"


def _delivered_single_step_task(store) -> None:
    """One-step plan whose content step finished NORMALLY (lease kept) — the parent
    for the dynamic-row drop cases, where only the review/rework row got dropped."""
    steps = [
        {"step_id": "s1", "title": "nghiên cứu thị trường", "assigned_to": "agent-a",
         "deps": [], "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo", original_request="làm demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    attempt = store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0, attempt_id=attempt)


def _drop_row(store, step_id: str) -> None:
    """Run a dynamic row into needs_decision and CEO-drop it through the real
    primitive (`drop_stalled_step` has no step_type filter, so review/rework rows
    are legitimate prey)."""
    store.reserve_step("t1", step_id)
    store.mark_needs_decision("t1", step_id, outcome_ref="x", cost_usd=0.0)
    task = store.get("t1")
    step = next(s for s in task.steps if s.step_id == step_id)
    assert drop_step_with_placeholder(store, task, step)


def test_a_dropped_rework_row_never_mints_the_next_review_round(tmp_path, monkeypatch):
    """CEO drops a dead rework: the next-round review would lock onto its placeholder
    (guaranteed stale), and that round's failure would mint yet another rework —
    resurrecting the row the drop meant to end."""
    import my_crew.agent.team_task_roster as roster_mod
    from my_crew.agent.coordinator_nodes.review_insert import maybe_insert_review_after_rework

    store = _store(tmp_path)
    _delivered_single_step_task(store)
    store.insert_step("t1", {
        "step_id": "s1-review-0-0", "title": "Soát chéo", "assigned_to": "agent-qa",
        "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 0,
    })
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "Sửa lại", "assigned_to": "agent-a",
        "deps": ["s1-review-0-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    _drop_row(store, "s1-rework-0")
    monkeypatch.setattr(roster_mod, "assignable_staff",
                        lambda: [("agent-a", "pm"), ("agent-qa", "pm")])

    task = store.get("t1")
    rework = next(s for s in task.steps if s.step_id == "s1-rework-0")
    assert maybe_insert_review_after_rework(_deps(store), task, rework) is False
    reviews = [s for s in store.get("t1").steps if s.step_type == "review"]
    assert [s.review_round for s in reviews] == [0]  # no round-1 mint


def test_a_dropped_review_row_ends_its_chain_instead_of_reminting(tmp_path):
    """CEO drops a dead review row: its placeholder yields no verdict, and the old
    verdict-None branch would immediately re-mint the exact row the CEO just killed."""
    from my_crew.agent.coordinator_nodes.review_insert import maybe_handle_review_done

    store = _store(tmp_path)
    _delivered_single_step_task(store)
    store.insert_step("t1", {
        "step_id": "s1-review-0-0", "title": "Soát chéo", "assigned_to": "agent-qa",
        "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 0,
    })
    _drop_row(store, "s1-review-0-0")

    task = store.get("t1")
    review = next(s for s in task.steps if s.step_id == "s1-review-0-0")
    assert maybe_handle_review_done(_deps(store), task, review) is False
    refreshed = store.get("t1")
    assert len([s for s in refreshed.steps if s.step_type == "review"]) == 1
    assert [s for s in refreshed.steps if s.step_type == "rework"] == []
