"""Review-found regression (v13 M34): a valid amend must NOT stall a task that already
has a done/running review or rework step.

`_verify_plan_hash` recomputes the tick hash over `system_inserted == 0` rows only, so
the amend's `new_plan_hash` must be built from the SAME set. If the frozen prefix folds
a `system_inserted == 1` row (a code-minted review/rework step) into the hash, the bound
hash diverges from the recompute → the task stalls on the next tick after a perfectly
valid amend. This pins the frozen-prefix filter in `amend_with_retries`.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_amend_prompt import _amend_frozen_prefix


def _step(step_id, status, *, system_inserted=0, deps=()):
    return SimpleNamespace(
        step_id=step_id, title=f"t-{step_id}", assigned_to="agent-a",
        deps=tuple(deps), status=status, system_inserted=system_inserted,
    )


def test_frozen_prefix_excludes_system_inserted_rows():
    # A confirmed work step (done) + a code-minted review row (done, system_inserted=1)
    # + a pending tail. The amend frozen prefix must contain ONLY the confirmed done
    # step — the review row is excluded, matching _verify_plan_hash's recompute domain.
    task = SimpleNamespace(steps=[
        _step("s1", "done"),
        _step("s1-review-0", "done", system_inserted=1, deps=["s1"]),
        _step("s2", "pending", deps=["s1"]),
    ])
    frozen = _amend_frozen_prefix(task)
    assert [s.step_id for s in frozen] == ["s1"]

    # The hash over the frozen prefix equals the hash over the confirmed non-pending
    # rows only — i.e. what _verify_plan_hash would compute for the completed portion.
    confirmed_only = SimpleNamespace(steps=[
        SimpleNamespace(step_id="s1", title="t-s1", assigned_to="agent-a", deps=()),
    ])
    assert (
        decomposition_content_hash(SimpleNamespace(steps=list(frozen)))
        == decomposition_content_hash(confirmed_only)
    )


# --- v63 H3 regression: frozen prefix must carry needs_shell/external_write ----------


def test_amend_frozen_prefix_keeps_hash_bound_flags():
    """`needs_shell`/`external_write` are CONDITIONAL plan_hash material — a frozen
    prefix that dropped them would bind an amend hash that `_verify_plan_hash`'s
    recompute over the store rows can never match (guaranteed stall after amending
    any task with a flagged non-pending step)."""
    from types import SimpleNamespace

    from my_crew.agent.team_task_amend_prompt import _amend_frozen_prefix

    task = SimpleNamespace(steps=[
        SimpleNamespace(step_id="s1", title="chạy script", assigned_to="agent-a",
                        deps=(), status="done", system_inserted=0,
                        needs_shell=True, external_write=False),
        SimpleNamespace(step_id="s2", title="gửi email", assigned_to="agent-b",
                        deps=("s1",), status="running", system_inserted=0,
                        needs_shell=False, external_write=True),
        SimpleNamespace(step_id="s3", title="tổng hợp", assigned_to="agent-a",
                        deps=("s2",), status="pending", system_inserted=0,
                        needs_shell=False, external_write=False),
    ])
    frozen = _amend_frozen_prefix(task)
    assert [s.step_id for s in frozen] == ["s1", "s2"]
    assert frozen[0].needs_shell is True and frozen[0].external_write is False
    assert frozen[1].needs_shell is False and frozen[1].external_write is True
