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


# --- v92 plan-time mail guard --------------------------------------------------------


def test_mail_step_rejected_when_fleet_has_no_mail_capable_agent():
    from my_crew.agent.team_task_roster import validate_mail_steps

    task = parse_decomposed_task(_raw([{**_step("s1"), "needs_mail": True}]))
    with pytest.raises(DecompositionError, match="CHƯA có agent nào được cấp quyền đọc thư"):
        validate_mail_steps(task.steps, capable_ids=set())


def test_mail_step_rejected_when_assigned_to_agent_without_mailbox_access():
    """The bug this flag exists for: a mail task assigned to a mail-less agent used to
    run to completion and spend real money answering "em không có quyền"."""
    from my_crew.agent.team_task_roster import validate_mail_steps

    task = parse_decomposed_task(_raw([{**_step("s1", assigned_to="agent-a"),
                                        "needs_mail": True}]))
    with pytest.raises(DecompositionError, match="phải giao cho agent có quyền Google"):
        validate_mail_steps(task.steps, capable_ids={"agent-b"})
    # The message must NAME the capable agent, or the retry has nothing to act on.
    with pytest.raises(DecompositionError, match="agent-b"):
        validate_mail_steps(task.steps, capable_ids={"agent-b"})


def test_mail_step_passes_on_capable_assignee_and_no_mail_never_checks():
    from my_crew.agent.team_task_roster import validate_mail_steps

    task = parse_decomposed_task(_raw([{**_step("s1", assigned_to="agent-b"),
                                        "needs_mail": True}]))
    validate_mail_steps(task.steps, capable_ids={"agent-b"})  # no raise
    plain = parse_decomposed_task(_raw([_step("s1")]))
    validate_mail_steps(plain.steps, capable_ids=set())  # no mail step -> no raise


def test_hash_changes_when_needs_mail_set_and_flagless_stays_migration_identical():
    """v92: needs_mail constrains who may hold the step → binds the confirm, but is
    emitted only when True so every flagless DAG (every pre-v92 task) hashes
    byte-identical — no plan-hash-mismatch stall on migration."""
    task_a = parse_decomposed_task(_raw([_step("s1")]))
    task_b = parse_decomposed_task(_raw([{**_step("s1"), "needs_mail": True}]))
    assert decomposition_content_hash(task_a) != decomposition_content_hash(task_b)

    import hashlib
    import json as _json

    flagless = parse_decomposed_task(_raw([_step("s1"), _step("s2", deps=["s1"])]))
    pre_v92 = _json.dumps(
        {"steps": [{"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
                    "deps": list(s.deps)} for s in flagless.steps]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    assert decomposition_content_hash(flagless) == hashlib.sha256(pre_v92.encode()).hexdigest()


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


def test_decompose_prompt_bans_bare_single_entity_collection_steps():
    """Measured across lanes9-12: 6 of 10 dropped steps were bare one-entity
    collect/lookup steps — they inherit quantitative criteria with no product around
    them, and when one dies its whole downstream branch starves. Below the parallel
    fan-out threshold the lookup must be folded INTO the producing step; at or above
    it, each collect step must batch multiple entities."""
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert "QUY TẮC GỘP THU THẬP" in _DECOMPOSE_SYSTEM
    assert "MỘT thực thể đứng" in _DECOMPOSE_SYSTEM
    assert "không bao giờ một bước một thực thể" in _DECOMPOSE_SYSTEM
    # The two rules must not contradict: batching kicks in exactly where the
    # parallel-split rule activates.
    assert _DECOMPOSE_SYSTEM.index("QUY TẮC TÁCH SONG SONG") \
        < _DECOMPOSE_SYSTEM.index("QUY TẮC GỘP THU THẬP")


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


def test_fanout_split_slices_the_packed_collect_into_named_parallel_steps():
    from my_crew.agent.task_decomposition import fanout_gap, fanout_split

    brief = "So sánh 5 sàn: Shopee, Lazada, TikTok Shop, Tiki, Sendo. Kèm nguồn."
    packed = _task_from([
        {**_step("research"), "needs_web": True, "acceptance": "kèm link nguồn"},
        _step("finalize", deps=["research"]),
    ])
    split = fanout_split(brief, packed)

    assert split is not None
    subs = [s for s in split.steps if s.needs_web and not s.deps]
    assert len(subs) == 2  # ≤6 entities → 2 parallel collect steps
    # Every entity is named in exactly one sub-step's title AND acceptance.
    for entity in ("Shopee", "Lazada", "TikTok Shop", "Tiki", "Sendo"):
        owners = [s for s in subs if entity in s.title]
        assert len(owners) == 1, entity
        assert entity in owners[0].acceptance
    # The original acceptance rubric survives on each sub.
    assert all("kèm link nguồn" in s.acceptance for s in subs)
    # The dependent was rewired onto the subs; the packed id is gone.
    finalize = next(s for s in split.steps if s.step_id == "finalize")
    assert set(finalize.deps) == {s.step_id for s in subs}
    assert all(s.step_id != "research" for s in split.steps)
    # The split satisfies the very gap that demanded it.
    assert fanout_gap(brief, split) == ""


def test_fanout_split_uses_three_steps_past_six_entities():
    from my_crew.agent.task_decomposition import fanout_split

    brief = ("Khảo sát 7 framework: React, Vue, Svelte, Angular, Solid, Qwik, Astro. "
             "Kèm nguồn.")
    packed = _task_from([
        {**_step("research"), "needs_web": True},
        _step("finalize", deps=["research"]),
    ])
    split = fanout_split(brief, packed)

    assert split is not None
    subs = [s for s in split.steps if s.needs_web and not s.deps]
    assert len(subs) == 3
    # 7 entities over 3 steps: 3+2+2, no entity dropped or duplicated.
    named = [e for s in subs for e in ("React", "Vue", "Svelte", "Angular", "Solid",
                                       "Qwik", "Astro") if e in s.title]
    assert sorted(named) == sorted(
        ["React", "Vue", "Svelte", "Angular", "Solid", "Qwik", "Astro"])


def test_fanout_split_declines_shapes_it_cannot_prove_safe():
    from my_crew.agent.task_decomposition import fanout_split

    brief = "So sánh 5 sàn: Shopee, Lazada, TikTok Shop, Tiki, Sendo. Kèm nguồn."
    # A packed collect step that is also the terminal: splitting it would mint
    # multiple terminals, so the splitter declines.
    terminal_collect = _task_from([{**_step("research"), "needs_web": True}])
    assert fanout_split(brief, terminal_collect) is None
    # Two dep-less collects: the gap would not have fired; nothing to split.
    already_fanned = _task_from([
        {**_step("r1"), "needs_web": True},
        {**_step("r2"), "needs_web": True},
        _step("finalize", deps=["r1", "r2"]),
    ])
    assert fanout_split(brief, already_fanned) is None
    # The only needs_web step has deps — not the shape the gap describes.
    dependent_collect = _task_from([
        _step("outline"),
        {**_step("research", deps=["outline"]), "needs_web": True},
        _step("finalize", deps=["research"]),
    ])
    assert fanout_split(brief, dependent_collect) is None
    # Under 4 entities: fan-out never applies.
    packed = _task_from([
        {**_step("research"), "needs_web": True},
        _step("finalize", deps=["research"]),
    ])
    assert fanout_split("So sánh Shopee với Lazada.", packed) is None


def test_fanout_split_output_survives_validation_and_hashing():
    """The split plan must pass the same gate a model plan does, and its hash must be
    recomputable from the flags it carries — a fanned plan that later stalls on
    `plan_hash mismatch` would be worse than no fan-out at all."""
    from my_crew.agent.task_decomposition import (
        decomposition_content_hash,
        fanout_split,
        validate_decomposition,
    )

    brief = "So sánh 5 sàn: Shopee, Lazada, TikTok Shop, Tiki, Sendo. Kèm nguồn."
    packed = _task_from([
        {**_step("research"), "needs_web": True},
        _step("finalize", deps=["research"]),
    ])
    split = fanout_split(brief, packed)
    validated = validate_decomposition(split, staff_ids={"agent-a"})
    # Hash over the split steps is stable and reflects needs_web on every sub.
    assert decomposition_content_hash(validated) == decomposition_content_hash(split)
    no_flag = split.model_copy(update={"steps": tuple(
        s.model_copy(update={"needs_web": False}) for s in split.steps
    )})
    assert decomposition_content_hash(no_flag) != decomposition_content_hash(split)


def test_amend_prompt_pins_flags_in_example_schema():
    """Bài học lặp 2 lần (decompose 112033f, replan 260809): flag định tuyến phải nằm
    trong SCHEMA VÍ DỤ — model mirror ví dụ, mô tả bằng văn xuôi không đủ. Đường amend
    là đường mint bước mới thứ ba (decompose, split, amend) và từng thiếu toàn bộ."""
    from my_crew.agent.team_task_amend_prompt import _AMEND_SYSTEM

    assert '"needs_web":false' in _AMEND_SYSTEM
    assert '"needs_shell":false' in _AMEND_SYSTEM
    assert '"external_write":false' in _AMEND_SYSTEM
    assert '"acceptance"' in _AMEND_SYSTEM


def test_find_terminals_reads_the_plan_shape():
    from my_crew.agent.task_decomposition import TeamStepPlan, find_terminals

    linear = (
        TeamStepPlan(step_id="a", title="t", assigned_to="x"),
        TeamStepPlan(step_id="b", title="t", assigned_to="x", deps=("a",)),
    )
    assert [s.step_id for s in find_terminals(linear)] == ["b"]
    # diamond: two branches fanning back into one final step
    diamond = (
        TeamStepPlan(step_id="root", title="t", assigned_to="x"),
        TeamStepPlan(step_id="l", title="t", assigned_to="x", deps=("root",)),
        TeamStepPlan(step_id="r", title="t", assigned_to="x", deps=("root",)),
        TeamStepPlan(step_id="end", title="t", assigned_to="x", deps=("l", "r")),
    )
    assert [s.step_id for s in find_terminals(diamond)] == ["end"]
    # parallel branches that never join leave several terminals
    split = (
        TeamStepPlan(step_id="one", title="t", assigned_to="x"),
        TeamStepPlan(step_id="two", title="t", assigned_to="x"),
    )
    assert {s.step_id for s in find_terminals(split)} == {"one", "two"}


# --- boundary declaration + structural fold (graph-engineering, v93) ---------------


def test_boundary_parses_normalized_and_defaults_empty():
    task = _task_from([
        {**_step("a"), "boundary": "  Specialization "},
        _step("b", deps=["a"]),
    ])
    assert task.steps[0].boundary == "specialization"
    assert task.steps[1].boundary == ""  # every pre-v93 plan parses unchanged


def test_boundary_unknown_label_is_kept_not_rejected():
    # Observational field: a light model inventing a label must not burn a retry.
    task = _task_from([{**_step("a"), "boundary": "vibes"}])
    assert task.steps[0].boundary == "vibes"


def test_hash_ignores_boundary_labels_entirely():
    # Back-compat pin: a labeled DAG hashes byte-identical to the same DAG unlabeled,
    # exactly like `acceptance` — pre-v93 confirm flows must keep verifying.
    plain = _task_from([_step("a"), _step("b", deps=["a"])])
    labeled = _task_from([
        {**_step("a"), "boundary": "concurrency"},
        {**_step("b", deps=["a"]), "boundary": "dependency"},
    ])
    assert decomposition_content_hash(plain) == decomposition_content_hash(labeled)


def test_boundary_label_counts_buckets_none_and_other():
    from my_crew.agent.task_decomposition import boundary_label_counts

    task = _task_from([
        {**_step("a"), "boundary": "permission"},
        {**_step("b", deps=["a"]), "boundary": "vibes"},
        _step("c", deps=["b"]),
    ])
    assert boundary_label_counts(task) == {"permission": 1, "other": 1, "none": 1}


def _fold(steps: list[dict]):
    from my_crew.agent.task_decomposition import fold_unjustified_steps

    return fold_unjustified_steps(_task_from(steps))


def test_fold_collapses_same_person_linear_chain_to_one_step():
    folded, count = _fold([
        {**_step("research"), "acceptance": "- nguồn kèm link"},
        {**_step("draft", deps=["research"]), "acceptance": "- đủ 3 mục"},
        {**_step("polish", deps=["draft"]), "acceptance": "- đủ 3 mục"},
    ])
    assert count == 2
    assert len(folded.steps) == 1
    only = folded.steps[0]
    assert only.step_id == "research"
    assert "title-draft" in only.title and "title-polish" in only.title
    # acceptance lines merged verbatim, deduped
    assert only.acceptance.splitlines() == ["- nguồn kèm link", "- đủ 3 mục"]


def test_fold_ors_needs_web_so_the_merged_step_keeps_its_tier():
    folded, count = _fold([
        {**_step("research"), "needs_web": True},
        _step("draft", deps=["research"]),
    ])
    assert count == 1
    assert folded.steps[0].needs_web is True


def test_fold_skips_different_assignee():
    # A change of person IS a specialization boundary — structural, label-free.
    task, count = _fold([
        _step("research", assigned_to="agent-a"),
        _step("draft", assigned_to="agent-b", deps=["research"]),
    ])
    assert count == 0
    assert len(task.steps) == 2


def test_fold_skips_permission_flagged_steps():
    for flag in ("needs_shell", "external_write"):
        task, count = _fold([
            _step("prep"),
            {**_step("run", deps=["prep"]), flag: True},
        ])
        assert count == 0, flag
        assert len(task.steps) == 2, flag


def test_fold_skips_depless_and_multi_dep_steps():
    # Dep-less parallel collects (the `fanout_split` shape) and join steps both
    # have real boundaries (concurrency / dependency-on-many) — never folded.
    task, count = _fold([
        _step("r1"),
        _step("r2"),
        _step("join", deps=["r1", "r2"]),
    ])
    assert count == 0
    assert len(task.steps) == 3


def test_fold_rewires_dependents_to_the_absorbing_predecessor():
    folded, count = _fold([
        _step("research", assigned_to="agent-a"),
        _step("draft", deps=["research"], assigned_to="agent-a"),
        _step("review", deps=["draft", "research"], assigned_to="agent-b"),
    ])
    assert count == 1
    review = next(s for s in folded.steps if s.step_id == "review")
    assert review.deps == ("research",)  # B→A rewire deduped against existing A dep


def test_fold_ignores_declared_labels_when_structure_disagrees():
    # A model inventing a boundary label gains nothing: the fold is structural.
    folded, count = _fold([
        _step("research"),
        {**_step("draft", deps=["research"]), "boundary": "specialization"},
    ])
    assert count == 1
    assert len(folded.steps) == 1


def test_folded_chain_then_downgrades_to_sprint():
    # Composition pin: a 4-step same-person linear chain — the measured chain-death
    # shape — folds to 1 step, which the UNCHANGED downgrade_to_sprint then catches.
    from my_crew.agent.sprint_intake import downgrade_to_sprint
    from my_crew.agent.task_decomposition import fold_unjustified_steps

    chain = _task_from([
        {**_step("s1"), "acceptance": "- mục 1"},
        {**_step("s2", deps=["s1"]), "acceptance": "- mục 2"},
        {**_step("s3", deps=["s2"]), "acceptance": "- mục 3"},
        {**_step("s4", deps=["s3"]), "acceptance": "- mục 4"},
    ])
    folded, count = fold_unjustified_steps(chain)
    assert count == 3 and len(folded.steps) == 1
    plan = downgrade_to_sprint("Viết báo cáo ngắn về X.", folded)
    assert plan is not None
    assert plan.assigned_to == "agent-a"
    for line in ("- mục 1", "- mục 4"):
        assert line in plan.acceptance


def test_decompose_prompt_pins_boundary_rule():
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert '"boundary"' in _DECOMPOSE_SYSTEM
    assert "QUY TẮC RANH GIỚI" in _DECOMPOSE_SYSTEM
    for kind in ("dependency", "concurrency", "specialization", "permission",
                 "human_gate"):
        assert kind in _DECOMPOSE_SYSTEM


def test_the_live_mail_brief_still_reaches_the_team_lane():
    """Premise guard for the live mail cases, kept OFFLINE on purpose.

    `tests/fullflow_live/test_live_mail_capability_gate.py` drives a mail-shaped brief
    through a real fleet to prove the v92 gate holds end to end. That only tests anything
    if the brief reaches the TEAM lane: `classify_brief` is pure code that defaults to
    SPRINT, and the sprint lane has no `needs_mail` concept at all, so a brief that routes
    there bypasses the gate entirely and both live cases pass while asserting nothing.

    This assertion cannot live beside those cases: `fullflow_live/conftest.py` marks every
    test in that package `live`, so it would be deselected by the default `-m "not live"`
    and skipped on any machine without a key — silent in exactly the situation it exists
    for. Here it runs on every plain `pytest`, and an innocuous reword of the brief fails
    fast and free instead of after a paid run.
    """
    from my_crew.agent.sprint_intake import classify_brief
    from tests.fullflow_live.test_live_mail_capability_gate import BRIEF

    is_sprint, reason = classify_brief(BRIEF)
    assert not is_sprint, (
        f"the live mail BRIEF now routes to the SPRINT lane ({reason!r}), which has no "
        "needs_mail concept — the live cases would bypass the v92 gate and pass while "
        "testing nothing. Restore the multi-stage phrasing that keeps it on the team lane."
    )


def test_the_live_cost_cap_brief_still_reaches_the_team_lane():
    """The same premise guard for the live per-step cost-cap cases, and it is not theory.

    Measured: the first version of that brief read as a lookup, so `classify_brief`
    returned `(True, "dạng 'tra cứu', không có dấu hiệu cần đội")` and the fleet planned a
    single `step_type='sprint'` row. Sprint mode deliberately keeps the model on the fast
    native tier, so `thin_tool_loop` — and with it the whole cost ceiling — never ran, and
    the live case failed after a 443s paid run with no work orders at all.

    Offline for the reason the mail guard above records: beside the live cases this would
    be deselected by the default `-m "not live"`. Here a reword fails in milliseconds.
    """
    from my_crew.agent.sprint_intake import classify_brief
    from tests.fullflow_live.test_live_runtime_cost_cap import BRIEF

    is_sprint, reason = classify_brief(BRIEF)
    assert not is_sprint, (
        f"the live cost-cap BRIEF now routes to the SPRINT lane ({reason!r}). Sprint steps "
        "run on the native tier, which never consults cost_cap_usd, so L1/L1b would assert "
        "against a loop that never executed. Restore the multi-stage phrasing."
    )


def test_the_live_tool_audit_brief_still_reaches_the_team_lane():
    """Same premise guard for the live tool-audit/stats cases.

    Sprint mode keeps the model on the native tier, which binds no read toolset at all — so
    the policy shim never runs and the audit trail stays empty. The live cases would then
    fail on "no rows" and look like a Phase 3 regression when the real cause is routing.
    """
    from my_crew.agent.sprint_intake import classify_brief
    from tests.fullflow_live.test_live_tool_audit_and_stats import BRIEF

    is_sprint, reason = classify_brief(BRIEF)
    assert not is_sprint, (
        f"the live tool-audit BRIEF now routes to the SPRINT lane ({reason!r}). The native "
        "tier binds no read toolset, so no shim runs and no audit row is written. Restore "
        "the multi-stage phrasing."
    )


def test_the_live_output_guard_brief_still_reaches_the_team_lane():
    """Same premise guard for the live dep-cap case, which needs a step that HAS deps.

    A sprint runs as a single step, and a step with no deps reads no handoff — so the
    per-dep cap has nothing to bound and the live case would fail on "no step with deps"
    while Phase 2 was working perfectly.
    """
    from my_crew.agent.sprint_intake import classify_brief
    from tests.fullflow_live.test_live_output_guards import BRIEF

    is_sprint, reason = classify_brief(BRIEF)
    assert not is_sprint, (
        f"the live output-guard BRIEF now routes to the SPRINT lane ({reason!r}). A sprint "
        "is one step with no deps, so no handoff is ever read and the per-dep cap cannot "
        "engage. Restore the multi-stage phrasing."
    )


def test_the_live_cost_cap_brief_still_tells_its_step_not_to_split():
    """The cost-cap brief must stay indivisible, and this too was learned by paying for it.

    Reaching the team lane is necessary but not sufficient. The pre-work propose call runs
    BEFORE the tool loop, and `_PROPOSE_SPLIT_ADDENDUM` invites any step made of "2-4 PHẦN
    ĐỘC LẬP CÙNG DẠNG" to hand its work to sub-steps instead — stating outright that such a
    step "sẽ KHÔNG tự làm nữa". Measured: a brief phrased as two techniques plus two more
    split onto `secretary` and `writer`, neither on the tools tier nor carrying a cap. The
    capped step's work order still recorded `effective_runtime=ToolCallingRuntime`, so the
    live case's anti-vacuity check passed while `run_thin_loop` never executed a single
    round — the most expensive kind of false premise, because it looks like a real failure
    of Phase 1.

    Whether the model splits is a model judgement no offline test can pin. What IS pinnable
    is that the brief still carries the explicit instruction not to, which is the only lever
    the case has over that judgement.
    """
    from tests.fullflow_live.test_live_runtime_cost_cap import BRIEF

    assert "KHÔNG chia nhỏ" in BRIEF and "KHÔNG giao cho người khác" in BRIEF, (
        "the live cost-cap BRIEF lost its explicit no-split instruction. Without it the "
        "propose call may fan the step out to uncapped agents, and L1 then measures a step "
        f"that never ran the thin loop at all. brief={BRIEF!r}"
    )
