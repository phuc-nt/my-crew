"""`acceptance` is per-step METADATA, not DAG structure — it must NEVER change
`decomposition_content_hash` (see that function's docstring and
`task_decomposition.TeamStepPlan.acceptance`'s field comment). A task WITH acceptance
text must hash byte-identical to the SAME DAG with no acceptance at all; changing
ONLY the acceptance text on an already-hashed task must not move the hash.
"""

from __future__ import annotations

import json

from my_crew.agent.task_decomposition import decomposition_content_hash, parse_decomposed_task


def _raw(steps: list[dict], requires_approval: bool = True) -> str:
    return json.dumps({"steps": steps, "requires_approval": requires_approval})


def test_task_with_acceptance_hashes_identical_to_task_without_it():
    no_acceptance = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
    ]))
    with_acceptance = parse_decomposed_task(_raw([
        {
            "step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
            "acceptance": "phải có tiêu đề và 3 gạch đầu dòng",
        },
    ]))
    assert decomposition_content_hash(no_acceptance) == decomposition_content_hash(with_acceptance)


def test_changing_acceptance_text_alone_does_not_change_the_hash():
    task_a = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
         "acceptance": "tiêu chí A"},
    ]))
    task_b = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
         "acceptance": "tiêu chí HOÀN TOÀN KHÁC, dài hơn nhiều"},
    ]))
    assert decomposition_content_hash(task_a) == decomposition_content_hash(task_b)


def test_multi_step_dag_with_acceptance_on_every_step_still_hashes_like_bare_dag():
    bare = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"]},
    ]))
    annotated = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
         "acceptance": "criteria 1"},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"],
         "acceptance": "criteria 2"},
    ]))
    assert decomposition_content_hash(bare) == decomposition_content_hash(annotated)


def test_acceptance_field_defaults_to_blank_string_when_absent():
    task = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
    ]))
    assert task.steps[0].acceptance == ""


def test_hash_matches_a_frozen_golden_digest_for_a_fixed_dag():
    """The other tests in this file only prove with-vs-without-acceptance equality
    (live-computed on both sides) — they would NOT catch a canonical-serialization
    drift (key order, separators, `ensure_ascii`) in `decomposition_content_hash`
    itself, which would silently invalidate every already-stored `plan_hash` in
    production without failing any test. Pin the digest for a fixed, v12-shaped
    (no-acceptance) 2-step DAG — same fixture as
    `test_multi_step_dag_with_acceptance_on_every_step_still_hashes_like_bare_dag`'s
    `bare` task — against a hardcoded literal computed once from the canonical JSON
    this function documents (sorted keys, `ensure_ascii=True`, `(",", ":")` separators).
    A change to that serialization must fail THIS test, loudly, not just silently ship.
    """
    task = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"]},
    ]))
    assert (
        decomposition_content_hash(task)
        == "95ef945813af3e00a53347a34048899928fca3a5b0a578aa8ee4afb5e76f74cc"
    )


def test_acceptance_is_stripped_of_surrounding_whitespace():
    task = parse_decomposed_task(_raw([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
         "acceptance": "  có khoảng trắng quanh  "},
    ]))
    assert task.steps[0].acceptance == "có khoảng trắng quanh"
