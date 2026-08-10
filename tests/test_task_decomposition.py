"""Team-task decomposition: schema parsing + deterministic code-side validation.

Load-bearing (mirrors `task_decomposition.py`'s "LLM proposes, code validates" split):
- `parse_decomposed_task` rejects non-JSON and schema-mismatched output with
  `DecompositionError`, never lets a malformed LLM completion become a `DecomposedTask`.
- `validate_decomposition` re-checks step count, DAG acyclicity, and `assigned_to`
  authorization from CODE — a model that proposes an unauthorized assignee, a cycle, or
  too many steps is rejected regardless of what it claims.
- `decomposition_content_hash` is deterministic (same steps ⇒ same hash) and sensitive
  to any mutation (added/removed/reassigned step, changed deps) — the TOCTOU-proof
  binding `ops_assign_team_task.run_assign_team_task`'s confirm step relies on.
"""

from __future__ import annotations

import json

import pytest

from my_crew.agent.task_decomposition import (
    MAX_STEPS,
    DecompositionError,
    decomposition_content_hash,
    parse_decomposed_task,
    validate_decomposition,
)


def _raw(steps: list[dict], requires_approval: bool = True) -> str:
    return json.dumps({"steps": steps, "requires_approval": requires_approval})


def _step(step_id: str, assigned_to: str = "agent-a", deps: list[str] | None = None) -> dict:
    return {"step_id": step_id, "title": f"title-{step_id}", "assigned_to": assigned_to,
            "deps": deps or []}


# --- parse_decomposed_task ---------------------------------------------------------


def test_parse_rejects_non_json():
    with pytest.raises(DecompositionError):
        parse_decomposed_task("not json at all")


def test_parse_rejects_json_that_is_not_an_object():
    with pytest.raises(DecompositionError):
        parse_decomposed_task(json.dumps(["a", "list", "not", "an", "object"]))


def test_parse_rejects_missing_steps_field():
    with pytest.raises(DecompositionError):
        parse_decomposed_task(json.dumps({"requires_approval": True}))


def test_parse_rejects_blank_title():
    raw = _raw([{"step_id": "s1", "title": "   ", "assigned_to": "agent-a", "deps": []}])
    with pytest.raises(DecompositionError):
        parse_decomposed_task(raw)


def test_parse_accepts_well_formed_single_step():
    task = parse_decomposed_task(_raw([_step("s1")]))
    assert task.steps[0].step_id == "s1"
    assert task.requires_approval is True


def test_parse_rejects_duplicate_step_ids():
    with pytest.raises(DecompositionError):
        parse_decomposed_task(_raw([_step("s1"), _step("s1")]))


def test_parse_rejects_dep_on_unknown_step():
    with pytest.raises(DecompositionError):
        parse_decomposed_task(_raw([_step("s1", deps=["ghost"])]))


def test_parse_rejects_self_dependency():
    with pytest.raises(DecompositionError):
        parse_decomposed_task(_raw([_step("s1", deps=["s1"])]))


def test_parse_rejects_more_than_max_steps():
    steps = [_step(f"s{i}") for i in range(MAX_STEPS + 1)]
    with pytest.raises(DecompositionError):
        parse_decomposed_task(_raw(steps))


# --- validate_decomposition ---------------------------------------------------------


def test_validate_accepts_linear_chain_with_known_staff():
    task = parse_decomposed_task(_raw([
        _step("s1", assigned_to="agent-a"),
        _step("s2", assigned_to="agent-b", deps=["s1"]),
    ]))
    validated = validate_decomposition(task, staff_ids={"agent-a", "agent-b"})
    assert validated is task


def test_validate_rejects_unauthorized_assignee():
    task = parse_decomposed_task(_raw([_step("s1", assigned_to="ghost-agent")]))
    with pytest.raises(DecompositionError, match="ghost-agent"):
        validate_decomposition(task, staff_ids={"agent-a"})


def test_validate_rejects_dependency_cycle():
    # step_id-level cycle: parse_decomposed_task's own model_validator only rejects
    # a dep on an unknown id or itself, not a longer cycle (s1->s2->s1) — that is
    # exactly what validate_decomposition's Kahn's-algorithm check is for.
    task = parse_decomposed_task(
        json.dumps({
            "steps": [
                {"step_id": "s1", "title": "t1", "assigned_to": "agent-a", "deps": ["s2"]},
                {"step_id": "s2", "title": "t2", "assigned_to": "agent-a", "deps": ["s1"]},
            ],
        })
    )
    with pytest.raises(DecompositionError, match="vòng lặp"):
        validate_decomposition(task, staff_ids={"agent-a"})


def test_validate_empty_staff_rejects_every_step():
    task = parse_decomposed_task(_raw([_step("s1", assigned_to="agent-a")]))
    with pytest.raises(DecompositionError):
        validate_decomposition(task, staff_ids=set())


# --- decomposition_content_hash ------------------------------------------------------


def test_hash_is_deterministic_for_same_steps():
    task = parse_decomposed_task(_raw([_step("s1"), _step("s2", deps=["s1"])]))
    assert decomposition_content_hash(task) == decomposition_content_hash(task)


def test_hash_changes_when_a_step_is_reassigned():
    task_a = parse_decomposed_task(_raw([_step("s1", assigned_to="agent-a")]))
    task_b = parse_decomposed_task(_raw([_step("s1", assigned_to="agent-b")]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)


def test_hash_changes_when_a_step_is_added():
    task_a = parse_decomposed_task(_raw([_step("s1")]))
    task_b = parse_decomposed_task(_raw([_step("s1"), _step("s2")]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)


def test_needs_shell_defaults_false():
    task = parse_decomposed_task(_raw([_step("s1")]))
    assert task.steps[0].needs_shell is False


def test_needs_shell_parses_true():
    raw = _raw([{**_step("s1"), "needs_shell": True}])
    assert parse_decomposed_task(raw).steps[0].needs_shell is True


def test_hash_changes_when_needs_shell_set():
    """needs_shell selects the runtime/trust boundary → it must bind the CEO confirm."""
    task_a = parse_decomposed_task(_raw([_step("s1")]))
    task_b = parse_decomposed_task(_raw([{**_step("s1"), "needs_shell": True}]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)


def test_hash_all_false_needs_shell_is_migration_identical():
    """A DAG where every step is needs_shell=False MUST hash byte-identical to a pre-v45 DAG
    (needs_shell emitted only when True) — so existing confirmed tasks don't false-stall on
    plan-hash-mismatch after the field was added."""
    import json as _json

    task = parse_decomposed_task(_raw([_step("s1"), _step("s2", deps=["s1"])]))
    # Reconstruct the pre-v45 canonical form (no needs_shell key at all) and hash it the same way.
    import hashlib

    pre_v45 = _json.dumps(
        {"steps": [{"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
                    "deps": list(s.deps)} for s in task.steps]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    assert decomposition_content_hash(task) == hashlib.sha256(pre_v45.encode()).hexdigest()


def test_hash_is_independent_of_step_input_order_when_content_equal():
    # Same two steps, same final tuple order (pydantic preserves list order) —
    # confirms the hash is a pure function of the parsed steps, not of dict key order
    # in the raw JSON (canonical json.dumps(sort_keys=True) neutralizes that).
    raw_a = json.dumps({"steps": [_step("s1"), _step("s2", deps=["s1"])]})
    raw_b = json.dumps({"steps": [_step("s2", deps=["s1"]), _step("s1")][::-1]})
    task_a = parse_decomposed_task(raw_a)
    task_b = parse_decomposed_task(raw_b)
    assert decomposition_content_hash(task_a) == decomposition_content_hash(task_b)


def test_decompose_prompt_instructs_needs_review_and_acceptance():
    # E2E-found regression: the decompose system prompt must tell the LLM to set
    # needs_review + acceptance, or every step ships needs_review=false and peer review
    # never fires in production (the graph/store default them false).
    from my_crew.llm.team_task_prompt import build_team_decompose_messages

    msgs = build_team_decompose_messages(brief="x", staff=[("a", "office")])
    system = msgs[0]["content"]
    assert "needs_review" in system
    assert "acceptance" in system
    assert "external_write" in system  # v63: review-waiver flag must be described too


# --- v63 external_write + small-task review waiver -----------------------------------


def test_external_write_defaults_false_and_parses_true():
    assert parse_decomposed_task(_raw([_step("s1")])).steps[0].external_write is False
    raw = _raw([{**_step("s1"), "external_write": True}])
    assert parse_decomposed_task(raw).steps[0].external_write is True


def test_hash_changes_when_external_write_set():
    """external_write drives the review-waiver policy → the CEO confirm must bind it."""
    task_a = parse_decomposed_task(_raw([_step("s1")]))
    task_b = parse_decomposed_task(_raw([{**_step("s1"), "external_write": True}]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)


def test_hash_all_false_external_write_is_migration_identical():
    """All-internal DAG (every pre-v63 task) must hash byte-identical to the pre-v63
    canonical form — no plan-hash-mismatch stall after the field was added."""
    import hashlib

    task = parse_decomposed_task(_raw([_step("s1"), _step("s2", deps=["s1"])]))
    pre_v63 = json.dumps(
        {"steps": [{"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
                    "deps": list(s.deps)} for s in task.steps]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    assert decomposition_content_hash(task) == hashlib.sha256(pre_v63.encode()).hexdigest()


def _reviewed_step(step_id: str, deps: list[str] | None = None, **extra) -> dict:
    return {**_step(step_id, deps=deps), "needs_review": True, **extra}


def test_small_internal_task_waives_every_needs_review():
    task = parse_decomposed_task(
        _raw([_reviewed_step("s1"), _reviewed_step("s2", deps=["s1"]),
              _reviewed_step("s3", deps=["s2"])])
    )
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    assert all(s.needs_review is False for s in validated.steps)


def test_small_task_with_external_write_reviews_terminal_and_external_only():
    task = parse_decomposed_task(
        _raw([_reviewed_step("s1"),
              _reviewed_step("s2", deps=["s1"], external_write=True)])
    )
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    # v64 policy: an external task is never waived; review lands on the terminal
    # (which here is also the external step) — the intermediate relies on self-check.
    assert [s.needs_review for s in validated.steps] == [False, True]


def test_large_internal_task_reviews_only_the_terminal():
    """v64 (UAT evidence: 5 work steps ballooned to 23 rows under LLM-flagged review):
    only the terminal synthesis step is peer-reviewed; intermediates self-check."""
    steps = [_reviewed_step("s1")] + [
        _reviewed_step(f"s{i}", deps=[f"s{i - 1}"]) for i in range(2, 6)
    ]
    task = parse_decomposed_task(_raw(steps))
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    assert [s.needs_review for s in validated.steps] == [False, False, False, False, True]


def test_external_write_step_is_always_reviewed_even_mid_chain():
    steps = [
        _step("s1"),
        {**_step("s2", deps=["s1"]), "external_write": True},  # mid-chain external
        _step("s3", deps=["s2"]),
        _step("s4", deps=["s3"]),
    ]
    task = parse_decomposed_task(_raw(steps))
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    assert [s.needs_review for s in validated.steps] == [False, True, False, True]


def test_no_pic_fanout_reviews_every_terminal():
    # Two parallel leaves, no gather: both are terminals → both reviewed.
    steps = [_step("s1"), _step("s2")]
    task = parse_decomposed_task(_raw(steps))
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    # 2 steps, all-internal → small-task waiver wins (0 review). Push past the waiver:
    steps4 = [_step("s1"), _step("s2"), _step("s3"), _step("s4")]
    validated4 = validate_decomposition(
        parse_decomposed_task(_raw(steps4)), staff_ids=["agent-a"]
    )
    assert all(s.needs_review is False for s in validated.steps)
    assert [s.needs_review for s in validated4.steps] == [True, True, True, True]


def test_review_waiver_never_shifts_the_plan_hash():
    """needs_review is not hash material — the waiver must not invalidate the hash the
    preview/confirm flow computed on the validated task."""
    task = parse_decomposed_task(_raw([_reviewed_step("s1"), _reviewed_step("s2", deps=["s1"])]))
    validated = validate_decomposition(task, staff_ids=["agent-a"])
    assert all(s.needs_review is False for s in validated.steps)
    assert decomposition_content_hash(task) == decomposition_content_hash(validated)


# --- v64 plan-time shell guard -------------------------------------------------------


def test_shell_step_rejected_when_fleet_has_no_sandbox_agent():
    from my_crew.agent.team_task_roster import validate_shell_steps

    task = parse_decomposed_task(_raw([{**_step("s1"), "needs_shell": True}]))
    with pytest.raises(DecompositionError, match="CHƯA có agent nào cấu hình sandbox"):
        validate_shell_steps(task.steps, capable_ids=set())


def test_shell_step_rejected_when_assigned_to_non_sandbox_agent():
    from my_crew.agent.team_task_roster import validate_shell_steps

    task = parse_decomposed_task(_raw([{**_step("s1", assigned_to="agent-a"),
                                        "needs_shell": True}]))
    with pytest.raises(DecompositionError, match="phải giao cho agent có sandbox"):
        validate_shell_steps(task.steps, capable_ids={"agent-b"})


def test_shell_step_passes_on_sandbox_capable_assignee_and_no_shell_never_checks():
    from my_crew.agent.team_task_roster import validate_shell_steps

    task = parse_decomposed_task(_raw([{**_step("s1", assigned_to="agent-b"),
                                        "needs_shell": True}]))
    validate_shell_steps(task.steps, capable_ids={"agent-b"})  # no raise
    plain = parse_decomposed_task(_raw([_step("s1")]))
    validate_shell_steps(plain.steps, capable_ids=set())  # no shell step -> no raise


def test_hash_changes_when_needs_web_set_and_flagless_stays_migration_identical():
    """v74: needs_web selects the step's runtime tier → binds the confirm, but is
    emitted only when True so every flagless DAG (all pre-v74 tasks) hashes
    byte-identical — no plan-hash-mismatch stall on migration."""
    task_a = parse_decomposed_task(_raw([_step("s1")]))
    task_b = parse_decomposed_task(_raw([{**_step("s1"), "needs_web": True}]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)

    import hashlib
    import json as _json

    flagless = parse_decomposed_task(_raw([_step("s1"), _step("s2", deps=["s1"])]))
    pre_v74 = _json.dumps(
        {"steps": [{"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
                    "deps": list(s.deps)} for s in flagless.steps]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    assert decomposition_content_hash(flagless) == hashlib.sha256(pre_v74.encode()).hexdigest()


# --- v74 phase 3: entity fan-out ----------------------------------------------------


def test_fanout_plan_two_parallel_collects_validates():
    """The shape the fan-out prompt rule asks for — 2 dep-less collect steps feeding a
    terminal fan-in — must sail through parse + validate unchanged (no validator work
    was needed for v74; this pins that assumption)."""
    task = parse_decomposed_task(_raw([
        {**_step("collect_a", assigned_to="agent-a"), "needs_web": True},
        {**_step("collect_b", assigned_to="agent-b"), "needs_web": True},
        _step("finalize", assigned_to="agent-a", deps=["collect_a", "collect_b"]),
    ]))
    validated = validate_decomposition(task, staff_ids={"agent-a", "agent-b"})
    assert [s.step_id for s in validated.steps if not s.deps] == ["collect_a", "collect_b"]


def test_decompose_prompt_pins_fanout_rule():
    """v74: the ≥4-independent-entities → parallel collect split, with entity names
    demanded in title + acceptance, must stay in the decompose system prompt."""
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert "QUY TẮC TÁCH SONG SONG" in _DECOMPOSE_SYSTEM
    assert "4 THỰC THỂ" in _DECOMPOSE_SYSTEM
    assert "NÊU ĐÍCH DANH" in _DECOMPOSE_SYSTEM
    # e2e round v74-1 lesson: the flag must sit in the EXAMPLE SCHEMA, not only the
    # prose — the model mirrors the example and never emitted needs_web without it,
    # silently forcing research steps onto the searchless native tier.
    assert '"needs_web":false' in _DECOMPOSE_SYSTEM


# --- v74.2: code-side fan-out bias --------------------------------------------------


def test_count_enumerated_entities_on_real_brief_shapes():
    from my_crew.agent.task_decomposition import count_enumerated_entities

    assert count_enumerated_entities(
        "So sánh phí bán hàng trên 5 sàn: Shopee, Lazada, TikTok Shop, Tiki, Sendo. "
        "Mỗi sàn kèm link nguồn."
    ) == 5
    assert count_enumerated_entities("Viết bài về xu hướng AI, kèm 3 ví dụ.") < 4
    # "và" joins the last pair — still 4 entities
    assert count_enumerated_entities(
        "Khảo sát 4 công cụ: Notion, Obsidian, Logseq và Anytype. Kèm nguồn."
    ) == 4


def test_the_count_stops_where_the_attribute_clause_begins():
    """"A, B và C theo giá, offline" is three subjects and two attributes. Counting the
    attributes inflates the number quoted back to the planner, telling it to fan out
    over things that are not entities."""
    from my_crew.agent.task_decomposition import count_enumerated_entities

    assert count_enumerated_entities(
        "So sánh 5 công cụ note-taking: Notion, Obsidian, Logseq, Google Keep và "
        "Apple Notes theo giá, khả năng offline, liên kết ghi chú."
    ) == 5


def test_parenthesised_subjects_are_counted_over_the_attributes_after_the_colon():
    """Benchmark A's shape. Counting the three attributes put this brief UNDER the
    fan-out threshold, so the collection step was never split and the team run spent
    ~17 minutes on one bundled step."""
    from my_crew.agent.task_decomposition import count_enumerated_entities

    assert count_enumerated_entities(
        "So sánh 5 dịch vụ streaming nhạc tại Việt Nam (Spotify, YouTube Music, "
        "Apple Music, Zing MP3, Nhaccuatui): giá gói cá nhân, kho nhạc Việt, "
        "chất lượng âm thanh."
    ) == 5


def _task_from(steps: list[dict]):
    return parse_decomposed_task(_raw(steps))


def test_fanout_gap_flags_single_collect_and_accepts_split():
    from my_crew.agent.task_decomposition import fanout_gap

    brief = "So sánh 5 sàn: Shopee, Lazada, TikTok Shop, Tiki, Sendo. Kèm nguồn."
    single = _task_from([
        {**_step("research"), "needs_web": True},
        _step("finalize", deps=["research"]),
    ])
    assert "PHẢI tách" in fanout_gap(brief, single)

    split = _task_from([
        {**_step("r1"), "needs_web": True},
        {**_step("r2"), "needs_web": True},
        _step("finalize", deps=["r1", "r2"]),
    ])
    assert fanout_gap(brief, split) == ""


def test_fanout_gap_skips_non_research_and_small_briefs():
    from my_crew.agent.task_decomposition import fanout_gap

    listy_brief = "Soạn slide về 5 giá trị: Tốc độ, Trung thực, Kỷ luật, Tò mò, Bền bỉ."
    writing_only = _task_from([_step("draft"), _step("final", deps=["draft"])])
    assert fanout_gap(listy_brief, writing_only) == ""  # no needs_web step → nothing to fan

    small_brief = "So sánh Shopee với Lazada, kèm nguồn."
    single = _task_from([{**_step("research"), "needs_web": True}])
    assert fanout_gap(small_brief, single) == ""


def test_amend_prompt_pins_flags_in_example_schema():
    """Bài học lặp 2 lần (decompose 112033f, replan 260809): flag định tuyến phải nằm
    trong SCHEMA VÍ DỤ — model mirror ví dụ, mô tả bằng văn xuôi không đủ. Đường amend
    là đường mint bước mới thứ ba (decompose, split, amend) và từng thiếu toàn bộ."""
    from my_crew.agent.team_task_amend_prompt import _AMEND_SYSTEM

    assert '"needs_web":false' in _AMEND_SYSTEM
    assert '"needs_shell":false' in _AMEND_SYSTEM
    assert '"external_write":false' in _AMEND_SYSTEM
    assert '"acceptance"' in _AMEND_SYSTEM
