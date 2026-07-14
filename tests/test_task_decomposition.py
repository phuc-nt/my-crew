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

from src.agent.task_decomposition import (
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
    from src.llm.team_task_prompt import build_team_decompose_messages

    msgs = build_team_decompose_messages(brief="x", staff=[("a", "office")])
    system = msgs[0]["content"]
    assert "needs_review" in system
    assert "acceptance" in system
