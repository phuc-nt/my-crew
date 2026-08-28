"""A rework ROW must actually receive the reviewer's findings.

A failed peer review mints a `rework` row whose `deps[0]` points at the REVIEW step,
on the documented theory that the rework brief (prior draft + `Danh sách lỗi cần sửa:`)
"already rides inside the review-step's OWN verdict artifact" and so arrives through the
ordinary deps-handoff mechanism.

It did not. `_read_deps_handoff` resolves a dep to `step-<dep_seq>.json`, but a review
step never writes that file — `run_review_step` writes `step-<parent_seq>-review-<round>
.json` instead. `read_step_artifact` returned None, the loop hit `continue`, and the
rework row entered `perceive` with an EMPTY deps handoff: no prior draft, no failure
list. Measured on production task 51ad15207896 — all seven rework rows across three
review rounds read 0 chars, while every verdict artifact on disk held its failure list
intact. The reviewer graded correctly and the finding was written correctly; only the
delivery path was severed, so nothing surfaced as an error.

Downstream that silence is what made rework useless rather than merely weak: with no
failure text in the handoff, the work node's `build_search_query` had nothing but the
title and the CEO-brief boilerplate to build from, so every round re-ran a near-identical
query, got back the same sources that had already failed review, and stalled at the
round cap.
"""

from __future__ import annotations

import pytest

from my_crew.agent.team_task_artifact import write_review_verdict_artifact
from my_crew.agent.team_task_graph import _read_deps_handoff
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture
def store(tmp_path):
    s = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    yield s
    s.close()


def _task_with_failed_review(store: TeamTaskStore, *, task_id="t1", review_round=0):
    """A done content step + the review row that failed it, shaped like the real mint."""
    steps = [{"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a",
              "deps": [], "needs_review": True}]
    store.create_task(task_id=task_id, title="demo", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash="h")
    store.reserve_step(task_id, "s1")
    store.mark_done(task_id, "s1", outcome_ref="x", cost_usd=0.0)
    review_id = f"s1-review-{review_round}-{review_round}"
    store.insert_step(task_id, {
        "step_id": review_id, "title": "Soát chéo: draft báo cáo",
        "assigned_to": "agent-b", "deps": ["s1"], "step_type": "review",
        "parent_step_id": "s1", "review_round": review_round,
    })
    store.reserve_step(task_id, review_id)
    store.mark_done(task_id, review_id, outcome_ref="y", cost_usd=0.0)
    return review_id


def test_rework_row_receives_the_reviewers_failure_list(store, tmp_path):
    """The bug, at the seam where it actually bit: dep resolves, artifact does not."""
    review_id = _task_with_failed_review(store)
    content_seq = store.get_step("t1", "s1").seq
    write_review_verdict_artifact(tmp_path, "t1", content_seq, 0, {
        "passed": False,
        "failures": ["thiếu nguồn cho số 40,74", "chưa nêu mốc thời gian"],
        "notes": [], "criteria": [], "reviewed_version": "v1", "round": 0,
        "result_text": (
            "Bản nháp trước đó về thanh toán không tiền mặt.\n\n"
            "Danh sách lỗi cần sửa:\n"
            "- thiếu nguồn cho số 40,74\n"
            "- chưa nêu mốc thời gian"
        ),
    })

    handoff = _read_deps_handoff(tmp_path, "t1", (review_id,))

    assert handoff, "rework row read an EMPTY handoff — the failure list never arrived"
    assert "Danh sách lỗi cần sửa" in handoff
    assert "40,74" in handoff, "the specific defect the reviewer named must survive"
    assert "Bản nháp trước đó" in handoff, "the prior draft must survive too"


def test_each_review_round_reads_its_own_verdict_not_an_earlier_one(store, tmp_path):
    """Round N's rework must read round N's findings.

    Verdicts are per-round files by design (round is baked into the filename so a later
    re-review never clobbers an earlier one). Resolving the wrong round would feed a
    rework the defects it had ALREADY fixed — which looks identical to the original bug
    from the outside: rework churns, nothing improves, the round cap stalls it.
    """
    review_0 = _task_with_failed_review(store, review_round=0)
    content_seq = store.get_step("t1", "s1").seq
    review_1 = "s1-review-1-1"
    store.insert_step("t1", {
        "step_id": review_1, "title": "Soát chéo: draft báo cáo",
        "assigned_to": "agent-b", "deps": ["s1"], "step_type": "review",
        "parent_step_id": "s1", "review_round": 1,
    })
    store.reserve_step("t1", review_1)
    store.mark_done("t1", review_1, outcome_ref="y2", cost_usd=0.0)

    for rnd, marker in ((0, "LOI-VONG-0"), (1, "LOI-VONG-1")):
        write_review_verdict_artifact(tmp_path, "t1", content_seq, rnd, {
            "passed": False, "failures": [marker], "notes": [], "criteria": [],
            "reviewed_version": f"v{rnd}", "round": rnd,
            "result_text": f"nháp vòng {rnd}\n\nDanh sách lỗi cần sửa:\n- {marker}",
        })

    h0 = _read_deps_handoff(tmp_path, "t1", (review_0,))
    h1 = _read_deps_handoff(tmp_path, "t1", (review_1,))

    assert "LOI-VONG-0" in h0 and "LOI-VONG-1" not in h0
    assert "LOI-VONG-1" in h1 and "LOI-VONG-0" not in h1


def test_rework_row_still_reads_its_parents_source_deps(store, tmp_path):
    """The review dep must not displace the source data the rework also needs.

    `deps` is minted as `[review_step] + parent's own source deps`, so a fix round can
    re-read the upstream material it is correcting against. Both must arrive.
    """
    steps = [
        {"step_id": "src", "title": "thu thập số liệu", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a",
         "deps": ["src"], "needs_review": True},
    ]
    store.create_task(task_id="t2", title="demo", original_request="lam demo")
    store.set_plan("t2", steps, plan_hash="h2")
    store.reserve_step("t2", "src")
    store.mark_done("t2", "src", outcome_ref="a", cost_usd=0.0)
    store.reserve_step("t2", "s1")
    store.mark_done("t2", "s1", outcome_ref="b", cost_usd=0.0)

    from my_crew.agent.team_task_artifact import write_step_artifact
    src_seq = store.get_step("t2", "src").seq
    write_step_artifact(tmp_path, "t2", src_seq, {"result_text": "SO-LIEU-GOC"})

    review_id = "s1-review-0-0"
    store.insert_step("t2", {
        "step_id": review_id, "title": "Soát chéo", "assigned_to": "agent-b",
        "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 0,
    })
    store.reserve_step("t2", review_id)
    store.mark_done("t2", review_id, outcome_ref="c", cost_usd=0.0)
    content_seq = store.get_step("t2", "s1").seq
    write_review_verdict_artifact(tmp_path, "t2", content_seq, 0, {
        "passed": False, "failures": ["thiếu nguồn"], "notes": [], "criteria": [],
        "reviewed_version": "v1", "round": 0,
        "result_text": "nháp\n\nDanh sách lỗi cần sửa:\n- thiếu nguồn",
    })

    handoff = _read_deps_handoff(tmp_path, "t2", (review_id, "src"))

    assert "Danh sách lỗi cần sửa" in handoff, "reviewer findings missing"
    assert "SO-LIEU-GOC" in handoff, "parent's source data missing"


def test_a_passing_review_dep_hands_on_the_approved_text(store, tmp_path):
    """A passed verdict stores the approved result_text (no failure list appended).

    Reading verdicts for review deps must not assume failure: the same path serves a
    `passed` verdict, whose `result_text` is the clean output.
    """
    review_id = _task_with_failed_review(store)
    content_seq = store.get_step("t1", "s1").seq
    write_review_verdict_artifact(tmp_path, "t1", content_seq, 0, {
        "passed": True, "failures": [], "notes": [], "criteria": [],
        "reviewed_version": "v1", "round": 0, "result_text": "BAN-DA-DUYET",
    })

    handoff = _read_deps_handoff(tmp_path, "t1", (review_id,))

    assert handoff == "BAN-DA-DUYET"


def test_missing_verdict_artifact_degrades_quietly(store, tmp_path):
    """No verdict on disk ⇒ "", not a crash.

    Preserves the existing tolerant-of-absence contract; a rework whose verdict write
    failed must still run (weakly) rather than kill the step.
    """
    review_id = _task_with_failed_review(store)
    assert _read_deps_handoff(tmp_path, "t1", (review_id,)) == ""


def test_perceive_hands_the_fix_round_both_the_defects_and_the_ceo_brief(store, tmp_path):
    """End-to-end through `perceive`'s own reader, not just `_read_deps_handoff`.

    Every existing rework test checks either the row's COLUMNS at mint time or the
    internal node's PROMPT; none covered the artifact -> deps-handoff -> handoff_context
    join that a rework ROW actually travels. That gap is why an empty handoff shipped:
    each half looked correct in isolation.
    """
    from my_crew.config.config_builders import build_settings_from_env

    review_id = _task_with_failed_review(store)
    content_seq = store.get_step("t1", "s1").seq
    write_review_verdict_artifact(tmp_path, "t1", content_seq, 0, {
        "passed": False, "failures": ["thiếu nguồn cho số 40,74"],
        "notes": [], "criteria": [], "reviewed_version": "v1", "round": 0,
        "result_text": "nháp trước\n\nDanh sách lỗi cần sửa:\n- thiếu nguồn cho số 40,74",
    })

    from my_crew.agent.team_task_graph import default_team_task_deps

    deps = default_team_task_deps(
        settings=build_settings_from_env(), step_title="draft báo cáo",
        data_dir=tmp_path, task_id="t1", step_seq=999, step_deps=(review_id,),
    )
    handoff = deps.read_handoff()

    assert "thiếu nguồn cho số 40,74" in handoff, "the defect never reached perceive"
    assert "nháp trước" in handoff, "the prior draft never reached perceive"
    assert "YÊU CẦU GỐC CỦA CEO" in handoff, "the CEO brief must still ride along"
