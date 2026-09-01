"""M32 review-insert ticker rule (`coordinator_nodes.review_insert`): a `done` `work`
step with `needs_review=True` mints a review-step child; a `done` `review` step's
verdict drives rework-insert (or, at the cap, ends the chain); a `done` `rework` step mints the next
review round. Exercised directly against the pure functions with a real
`TeamTaskStore` (SQLite) + a fake `CoordinatorDeps`, mirroring `test_coordinator_graph
.py`'s fixture style.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import my_crew.agent.team_task_roster as roster_mod
from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
from my_crew.agent.coordinator_nodes.review_insert import (
    MAX_REVIEW_ROUNDS,
    maybe_handle_review_done,
    maybe_insert_review,
    maybe_insert_review_after_rework,
)
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_artifact import write_review_verdict_artifact
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _content_hash(steps: list[dict]) -> str:
    from types import SimpleNamespace

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan_one_step(store: TeamTaskStore, *, needs_review: bool = True, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": needs_review},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))
    store.reserve_step(task_id, "s1")
    store.mark_done(task_id, "s1", outcome_ref="x", cost_usd=0.0)


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        escalate=lambda task, step, kind, msg: None, now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def _wire_roster(monkeypatch, roster: list[tuple[str, str]]) -> None:
    monkeypatch.setattr(roster_mod, "assignable_staff", lambda: roster)


# --- rule 1: work -> review insert ---------------------------------------------------


def test_work_step_done_with_needs_review_mints_review_child(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    inserted = maybe_insert_review(_deps(store), task, done_step)
    assert inserted is True

    task = store.get("t1")
    review_steps = [s for s in task.steps if s.step_type == "review"]
    assert len(review_steps) == 1
    review = review_steps[0]
    assert review.assigned_to == "agent-qa"
    assert review.parent_step_id == "s1"
    assert review.review_round == 0
    assert review.system_inserted is True
    assert review.needs_review is False


def test_work_step_without_needs_review_never_mints_review(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=False)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review"]


def test_review_insert_is_idempotent_no_double_mint(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")
    maybe_insert_review(_deps(store), task, done_step)

    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")
    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert len([s for s in task.steps if s.step_type == "review"]) == 1


def test_no_eligible_reviewer_skips_without_stalling(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm")])  # only the author — no peer
    events = []
    monkeypatch.setattr(
        "my_crew.agent.coordinator_nodes.review_insert.append_office_event",
        lambda *a, **kw: events.append(kw.get("body", {}).get("milestone")),
    )
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review"]
    assert task.status != "stalled"
    assert events == ["review_skipped"]


# --- rule 2: review done -> verdict handling ------------------------------------------


def _mint_review(store, task_id="t1", content_step_id="s1", *, reviewer="agent-qa",
                  review_round=0) -> None:
    store.insert_step(task_id, {
        "step_id": f"{content_step_id}-review-{review_round}", "title": "soat",
        "assigned_to": reviewer, "deps": [content_step_id], "step_type": "review",
        "parent_step_id": content_step_id, "review_round": review_round,
    })
    step_id = f"{content_step_id}-review-{review_round}"
    store.reserve_step(task_id, step_id)
    store.mark_done(task_id, step_id, outcome_ref="x", cost_usd=0.0)


def test_passed_verdict_is_a_clean_no_op(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0, {"passed": True, "failures": []},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "rework"]
    assert task.status != "stalled"


def test_needs_rework_verdict_mints_rework_step_with_original_author(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0,
        {"passed": False, "failures": ["thieu so lieu"], "result_text": "brief"},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    task = store.get("t1")
    rework_steps = [s for s in task.steps if s.step_type == "rework"]
    assert len(rework_steps) == 1
    rework = rework_steps[0]
    assert rework.assigned_to == "agent-a"  # original content-step author
    assert rework.parent_step_id == "s1"
    assert rework.review_round == 0
    assert rework.deps == (review_step.step_id,)


def test_rework_inherits_the_web_grant_of_the_step_it_redoes(tmp_path, monkeypatch):
    """A fix round that cannot re-fetch its own sources is not a fix round.

    Observed live (task a0865653ed89): a `needs_web` research step failed review, and
    its rework — minted without the flag — was routed to the searchless tier, so it
    could only answer "Công cụ tìm kiếm web không khả dụng" and park on a clarify
    instead of redoing the lookup.
    """
    store = _store(tmp_path)
    steps = [
        {"step_id": "s1", "title": "tra giá công cụ", "assigned_to": "agent-a",
         "deps": [], "needs_review": True, "needs_web": True},
    ]
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0,
        {"passed": False, "failures": ["thieu so lieu"], "result_text": "brief"},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    rework = next(s for s in store.get("t1").steps if s.step_type == "rework")
    assert rework.needs_web is True


def test_rework_round_cap_ends_the_chain_after_max_rounds(tmp_path, monkeypatch):
    """No stall, no escalate, no further mint — the task proceeds to delivery, where
    the aggregate quotes the unresolved verdict (tested in team_tick_collaborators)."""
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store, review_round=MAX_REVIEW_ROUNDS)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, MAX_REVIEW_ROUNDS,
        {"passed": False, "failures": ["van sai"], "result_text": "brief"},
    )
    escalated = []
    task = store.get("t1")
    review_step = next(
        s for s in task.steps
        if s.step_type == "review" and s.review_round == MAX_REVIEW_ROUNDS
    )

    deps = _deps(store, escalate=lambda t, s, kind, msg: escalated.append(kind))
    assert maybe_handle_review_done(deps, task, review_step) is False
    task = store.get("t1")
    assert task.status != "stalled"
    assert escalated == []
    assert not [s for s in task.steps if s.step_type == "rework"]


def test_round_cap_holds_when_reached_by_actually_reworking_each_round(
    tmp_path, monkeypatch
):
    """The cap must hold on the path production actually takes: every round's rework is
    minted by the rule itself, not pre-placed.

    The sibling test above reaches `MAX_REVIEW_ROUNDS` with NO rework rows on the step,
    which cannot happen in a real run -- getting to round N requires rounds 0..N-1 to
    each have minted and finished a rework. The final round's failure must end the
    chain quietly: no round-`MAX_REVIEW_ROUNDS` rework, no stall, no escalate.
    """
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    from my_crew.runtime.team_task_paths import team_tasks_root

    escalated: list[str] = []
    deps = _deps(store, escalate=lambda t, s, kind, msg: escalated.append(kind))
    _mint_review(store)

    # Every round fails review, exactly as the runaway live task did.
    for rnd in range(MAX_REVIEW_ROUNDS + 1):
        write_review_verdict_artifact(
            team_tasks_root(), "t1", 1, rnd,
            {"passed": False, "failures": ["van sai"], "result_text": "brief"},
        )
        task = store.get("t1")
        review_step = next(
            s for s in task.steps
            if s.step_type == "review" and s.review_round == rnd
        )
        maybe_handle_review_done(deps, task, review_step)

        task = store.get("t1")
        if task.status == "stalled":
            break
        rework = next(
            (s for s in task.steps
             if s.step_type == "rework" and s.review_round == rnd), None,
        )
        if rework is None:
            break
        store.reserve_step("t1", rework.step_id)
        store.mark_done("t1", rework.step_id, outcome_ref="x", cost_usd=0.0)
        maybe_insert_review_after_rework(deps, store.get("t1"), rework)

    task = store.get("t1")
    rounds = sorted(s.review_round for s in task.steps if s.step_type == "rework")
    assert rounds == list(range(MAX_REVIEW_ROUNDS)), (
        f"rework minted at rounds {rounds}; the cap allows at most "
        f"{MAX_REVIEW_ROUNDS} (rounds 0..{MAX_REVIEW_ROUNDS - 1})"
    )
    assert task.status != "stalled"
    assert escalated == []


def test_task_review_budget_ends_chains_before_round_cap_when_whole_task_churns(
    tmp_path, monkeypatch
):
    """Trần TẦNG TASK: trần theo-từng-bước không thấy tổng — một task nhiều bước có thể
    hợp lệ đốt hàng chục row soát/sửa mà không bước nào cạn round riêng (đo live: 6 bước
    → 11 review + 7 rework). Khi tổng row review+rework chạm ngân sách (2× số bước nội
    dung, sàn 5), verdict fail tiếp theo phải kết thúc chuỗi (không mint thêm) dù round
    của bước đó chưa cạn — dừng đốt tiền; ý kiến reviewer đi theo bản giao."""
    store = _store(tmp_path)
    steps = [
        {"step_id": f"s{i}", "title": f"buoc {i}", "assigned_to": "agent-a",
         "deps": [], "needs_review": True}
        for i in (1, 2, 3)
    ]
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    for i in (1, 2, 3):
        store.reserve_step("t1", f"s{i}")
        store.mark_done("t1", f"s{i}", outcome_ref="x", cost_usd=0.0)

    # 3 bước nội dung → ngân sách 6. Dồn 6 row soát/sửa: s1 churn trọn 2 vòng
    # (2 review + 2 rework), s2 và s3 mỗi bước 1 review vòng 0.
    _mint_review(store, content_step_id="s1", review_round=0)
    for rnd in (0, 1):
        store.insert_step("t1", {
            "step_id": f"s1-rework-{rnd}", "title": "sua", "assigned_to": "agent-a",
            "deps": [f"s1-review-{rnd}"], "step_type": "rework",
            "parent_step_id": "s1", "review_round": rnd,
        })
        store.reserve_step("t1", f"s1-rework-{rnd}")
        store.mark_done("t1", f"s1-rework-{rnd}", outcome_ref="x", cost_usd=0.0)
    _mint_review(store, content_step_id="s1", review_round=1)
    _mint_review(store, content_step_id="s2", review_round=0)
    _mint_review(store, content_step_id="s3", review_round=0)

    from my_crew.runtime.team_task_paths import team_tasks_root

    s3_seq = next(s.seq for s in store.get("t1").steps if s.step_id == "s3")
    write_review_verdict_artifact(
        team_tasks_root(), "t1", s3_seq, 0,
        {"passed": False, "failures": ["van sai"], "result_text": "brief"},
    )
    escalated = []
    task = store.get("t1")
    review_step = next(
        s for s in task.steps if s.step_type == "review" and s.parent_step_id == "s3"
    )
    assert review_step.review_round < MAX_REVIEW_ROUNDS  # round riêng CHƯA cạn

    deps = _deps(store, escalate=lambda t, s, kind, msg: escalated.append(kind))
    assert maybe_handle_review_done(deps, task, review_step) is False
    task = store.get("t1")
    assert task.status != "stalled"
    assert escalated == []
    assert not [
        s for s in task.steps if s.step_type == "rework" and s.parent_step_id == "s3"
    ]


def test_task_review_budget_floor_never_cuts_a_single_step_task_early(
    tmp_path, monkeypatch
):
    """Task 1 bước: ngân sách sàn (5) đúng bằng mức một bước được phép dùng trọn
    (3 review + 2 rework) — trần task không bao giờ cắt sớm hơn trần bước, nên đường
    round-cap hiện có giữ nguyên hành vi và lý do escalate cũ."""
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0,
        {"passed": False, "failures": ["thieu"], "result_text": "brief"},
    )
    escalated = []
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")
    deps = _deps(store, escalate=lambda t, s, kind, msg: escalated.append(kind))

    assert maybe_handle_review_done(deps, task, review_step) is True  # mints rework
    task = store.get("t1")
    assert task.status != "stalled"
    assert escalated == []
    assert len([s for s in task.steps if s.step_type == "rework"]) == 1


def test_stale_artifact_remints_a_fresh_review_at_same_round(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    # no verdict artifact written -> stale/missing
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    task = store.get("t1")
    review_steps = [s for s in task.steps if s.step_type == "review"]
    assert len(review_steps) == 2  # original + freshly re-minted
    assert all(s.review_round == 0 for s in review_steps)


def test_stale_remint_at_round_one_keeps_locking_the_rework_artifact(
    tmp_path, monkeypatch
):
    """A round-≥1 review locks the latest REWORK's artifact (`_insert_review_step`
    docstring); its verdict-None re-mint must reproduce that lock, not fall back to
    the content step — a re-review graded against the artifact round 0 already
    rejected would re-litigate the wrong document."""
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "sua", "assigned_to": "agent-a",
        "deps": ["s1"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.reserve_step("t1", "s1-rework-0")
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    # The round-1 review as `maybe_insert_review_after_rework` mints it: deps lock
    # onto the rework row. No verdict artifact is written → stale/missing.
    store.insert_step("t1", {
        "step_id": "s1-review-1", "title": "soat", "assigned_to": "agent-qa",
        "deps": ["s1-rework-0"], "step_type": "review", "parent_step_id": "s1",
        "review_round": 1,
    })
    store.reserve_step("t1", "s1-review-1")
    store.mark_done("t1", "s1-review-1", outcome_ref="x", cost_usd=0.0)

    task = store.get("t1")
    review_step = next(
        s for s in task.steps if s.step_type == "review" and s.review_round == 1
    )
    assert maybe_handle_review_done(_deps(store), task, review_step) is True

    task = store.get("t1")
    reminted = [
        s for s in task.steps
        if s.step_type == "review" and s.step_id != "s1-review-1"
    ]
    assert len(reminted) == 1
    assert reminted[0].review_round == 1
    assert reminted[0].deps == ("s1-rework-0",)


# --- rule 3: rework done -> next review round -----------------------------------------


def test_rework_done_mints_next_review_round(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "draft báo cáo", "assigned_to": "agent-a",
        "deps": ["s1-review-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.reserve_step("t1", "s1-rework-0")
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])

    task = store.get("t1")
    rework_step = next(s for s in task.steps if s.step_type == "rework")

    assert maybe_insert_review_after_rework(_deps(store), task, rework_step) is True
    task = store.get("t1")
    round1_reviews = [s for s in task.steps if s.step_type == "review" and s.review_round == 1]
    assert len(round1_reviews) == 1
    assert round1_reviews[0].deps == ("s1-rework-0",)


def test_rework_done_next_round_no_reviewer_skips_without_stalling(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "draft báo cáo", "assigned_to": "agent-a",
        "deps": ["s1-review-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.reserve_step("t1", "s1-rework-0")
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    _wire_roster(monkeypatch, [("agent-a", "pm")])  # no peer this round

    task = store.get("t1")
    rework_step = next(s for s in task.steps if s.step_type == "rework")

    assert maybe_insert_review_after_rework(_deps(store), task, rework_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review" and s.review_round == 1]
    assert task.status != "stalled"


def test_rework_step_inherits_content_step_source_deps(tmp_path, monkeypatch):
    """The review artifact carries the failed output + failures, but FIXING a data
    defect needs the same source inputs the original author had. deps=[review] alone
    starved the reworker (observed live: it reported thiếu dữ liệu and degraded the
    artifact into the review-round cap)."""
    store = _store(tmp_path)
    steps = [
        {"step_id": "src", "title": "thu thập dữ liệu", "assigned_to": "agent-a",
         "deps": [], "needs_review": False},
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a",
         "deps": ["src"], "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.reserve_step("t1", "src")
    store.mark_done("t1", "src", outcome_ref="x", cost_usd=0.0)
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 2, 0,
        {"passed": False, "failures": ["thieu so lieu"], "result_text": "brief"},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    task = store.get("t1")
    rework = next(s for s in task.steps if s.step_type == "rework")
    # Failure brief first (review artifact), then the author's own source inputs.
    assert rework.deps == (review_step.step_id, "src")


# --- concurrent ticks: two overlapping ticks must not collide on the minted id ---------


def test_two_overlapping_ticks_do_not_crash_minting_the_same_next_review_round(
    tmp_path, monkeypatch,
):
    """Two ticks holding the same pre-insert snapshot must not raise on the second mint.

    The daemon runs a poke-triggered team-tick ALONGSIDE the minute cadence, and
    `run_poked_team_tick` reasons that an overlap is harmless because "the step lease/DB
    already serialize real actions". The lease serializes step DISPATCH; minting a review
    row takes no lease. `_insert_review_step` derives its `step_id` suffix from a
    `mint_count` read off the in-memory `task.steps`, so two ticks that both read the task
    before either insert compute the SAME suffix and the second insert hits
    `UNIQUE(task_id, step_id)`.

    Measured on the user's own daemon log: 5 occurrences of `worker coordinator/team-tick
    failed`, every one of them `sqlite3.IntegrityError: UNIQUE constraint failed:
    team_steps.task_id, team_steps.step_id` raised from this exact path, each immediately
    preceded by a `poke-triggered team-tick` line.

    The unique index is doing its job — no duplicate row is written, so this is not
    corruption. The damage is that the exception escapes `run_one_tick` and kills the
    WHOLE tick, discarding every other task that tick would have served. A tick that loses
    a race to mint a row it did not need to mint should be a no-op, not a crash.
    """
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "draft báo cáo", "assigned_to": "agent-a",
        "deps": ["s1-review-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.reserve_step("t1", "s1-rework-0")
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])

    # BOTH ticks read the task before either inserts — the overlap the daemon allows.
    task_tick_a = store.get("t1")
    task_tick_b = store.get("t1")
    rework_a = next(s for s in task_tick_a.steps if s.step_type == "rework")
    rework_b = next(s for s in task_tick_b.steps if s.step_type == "rework")

    assert maybe_insert_review_after_rework(_deps(store), task_tick_a, rework_a) is True

    # The loser of the race must simply decline; the round is already minted.
    assert maybe_insert_review_after_rework(_deps(store), task_tick_b, rework_b) is False

    task = store.get("t1")
    round1 = [s for s in task.steps if s.step_type == "review" and s.review_round == 1]
    assert len(round1) == 1, f"exactly one round-1 review must exist, got {round1!r}"


def test_two_overlapping_ticks_do_not_crash_minting_the_same_rework_row(
    tmp_path, monkeypatch,
):
    """Same race, one row-type over: the rework mint has no DB-level guard either.

    `_insert_rework_step`'s id is fully deterministic (`<content>-rework-<round>`) and its
    only idempotency guard is `rework_this_round`, computed from the caller's in-memory
    `task.steps`. Two overlapping ticks therefore both pass the guard and the second
    INSERT collides, killing that tick exactly as the review-mint race did.
    """
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0,
        {"passed": False, "failures": ["thieu so lieu"], "result_text": "brief"},
    )
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])

    task_tick_a = store.get("t1")
    task_tick_b = store.get("t1")
    review_a = next(s for s in task_tick_a.steps if s.step_type == "review")
    review_b = next(s for s in task_tick_b.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task_tick_a, review_a) is True
    assert maybe_handle_review_done(_deps(store), task_tick_b, review_b) is False

    task = store.get("t1")
    reworks = [s for s in task.steps if s.step_type == "rework"]
    assert len(reworks) == 1, f"exactly one rework row must exist, got {reworks!r}"
