"""L1/L1b — the per-step spend ceiling really stops a live loop, and only when set.

Phase 1 added `cost_cap_usd` enforcement to `thin_tool_loop`, pinned offline by
`tests/test_runtime_cost_cap_hard_stop.py` (14 cases, injected costs). Those prove the
arithmetic. What they cannot answer is the question v92 taught this suite to ask: does the
mechanism bear load on a real fleet — profile YAML → loader → `resolve_step_runtime` →
`ToolCallingRuntime` → `run_thin_loop` → the note reaching an artifact a human would read?
Every link there is real code that the offline cases stub past.

**The fleet had to change for this to be measurable at all.** Measured while writing these
cases: a profile with no `agent_runtime:` block loads as `kind="native"`, so
`resolve_step_runtime` returned `NativeGraphRuntime` for every step of every pre-existing
live case — `thin_tool_loop` had never executed ONCE in this suite. A case seeded the
ordinary way could assert on the cap all day and stay green in a world where Phase 1 was
deleted. Hence `seed_home(tools_tier=..., cost_cap_usd=...)`, and hence the
`effective_runtime` assertion below, which is what makes the rest non-vacuous.

**Why the assertion is the note's text and not the step status.** `run_thin_loop` returns
`(text, cost)`; it does not set a status. The capped text then goes through `self_check`,
which grades it against the acceptance criteria and may land the step on `done`,
`done_with_gaps` or `needs_decision` depending on how the model reads a partial answer.
That is a model judgement, so pinning it would buy flakiness. `COST_CAP_GAP_NOTE` is
emitted by code, with no model in the path, and it is the thing a human actually sees.

**Why not the log.** Nothing about the cap is logged — the guard breaks the loop and
appends to the returned text, and no `logger` call exists anywhere in
`loop_cost_guard.py`. An assertion on `serve.log` would fail for a working product.
"""

from __future__ import annotations

import pytest

from tests.fullflow_live.topology import (
    boot,
    seed_home,
    step_texts,
    wait_until_settled,
    work_orders,
)

#: The one agent moved onto the tool-calling tier. A single agent rather than the whole
#: fleet keeps the blast radius small: the coordinator and reviewer stay native, so what
#: these cases measure is one work step's loop and not a fleet-wide behaviour change.
CAPPED_AGENT = "analyst"

#: The literal, model-independent half of `COST_CAP_GAP_NOTE`. Kept as a prefix rather
#: than importing and formatting the constant: the numbers in it are the real spend, which
#: is by definition unknown before the run. Deliberately NOT imported and `.split()`-ed
#: either — a copy here means renaming the constant does not silently make this case pass
#: against a string it no longer emits; the offline suite owns the exact-format assertion.
CAP_NOTE_PREFIX = "[Kết quả CHƯA hoàn chỉnh — bước đã chạm trần chi phí $"

#: Low enough that the FIRST between-rounds check trips: `over_cost_cap` uses `>=`, so any
#: real round of ~$0.001+ on the pinned model exceeds it immediately. Not zero — zero would
#: trip before the loop ever called the model, which tests the arithmetic rather than the
#: integration, and offline already owns the arithmetic.
TIGHT_CAP_USD = 0.0005

#: The brief has to satisfy THREE independent routing conditions at once, and a measured
#: failure cost one paid run for each one missed:
#:
#: 1. **Team lane, not sprint.** `classify_brief` is pure code and routes anything that
#:    reads as a lookup to the sprint lane, which by design keeps the model on the fast
#:    native tier (`sprint_runner` docstring) and writes no work orders at all. A first
#:    version of this brief returned `(True, "dạng 'tra cứu', không có dấu hiệu cần đội")`
#:    and produced exactly one `step_type='sprint'` row — the cap was never consulted and
#:    `resolved=[]`. The multi-stage "trong tuần" phrasing is what moves it to the team
#:    lane; `test_the_live_cost_cap_brief_still_reaches_the_team_lane` (in
#:    `tests/test_task_decomposition.py`) pins that offline so a reword cannot
#:    silently send it back.
#: 2. **A `needs_web` work step.** `resolve_step_runtime` gate 2 sends a plain work step to
#:    native regardless of the profile, so without this flag the tools tier is unreachable.
#: 3. **No prefetch.** `web_search` stays FALSE on the fleet: a non-empty prefetch bundle
#:    marks the step prefetched and demotes it back to native. Measured — prefetch returns
#:    0 chars on a `web_search:false` profile even where provider keys are configured.
#:
#: 4. **No runtime fan-out.** Measured, and it cost a paid run: a brief phrased as N
#:    parallel items of the same kind ("hai kỹ thuật X, hai kỹ thuật Y") is exactly the
#:    shape `_PROPOSE_SPLIT_ADDENDUM` invites a step to split on. The pre-work propose call
#:    runs BEFORE the tool loop, and its addendum states plainly that a step proposing a
#:    split "sẽ KHÔNG tự làm nữa" — so the capped agent's step ended `done` after one
#:    tool-free JSON call, and the actual work went to `secretary` and `writer`, neither of
#:    which is on the tools tier or carries a cap. The step reached `ToolCallingRuntime`
#:    and still never entered `run_thin_loop`. Hence a brief describing ONE indivisible
#:    investigation deepened in sequence, rather than a list of independent parts.
#:
#: The agent is not left toolless by (3): `academic_search: true` binds `academic.search`
#: (OpenAlex, keyless) and `web.scrape`, verified against the real `build_read_toolset`. So
#: the loop has genuine work to do across several rounds, which is what gives the ceiling
#: a between-rounds check to fail.
BRIEF = (
    "NGHIÊN CỨU: tra cứu web tìm nguồn và dữ liệu MỚI về lượng tử hoá (quantization) "
    "mô hình ngôn ngữ lớn, rồi trong tuần viết một hồ sơ chuyên sâu về đúng MỘT kỹ "
    "thuật này. Đây là một mạch tra cứu liền, KHÔNG chia nhỏ và KHÔNG giao cho người "
    "khác: tra cứu, đọc nguồn tìm được, rồi tra cứu tiếp dựa trên chính điều vừa đọc "
    "— cơ chế hoạt động, mức tiết kiệm chi phí đã được đo, đánh đổi về chất lượng, và "
    "điều kiện nên hoặc không nên dùng. Mỗi ý kèm nguồn đã tra được trên web."
)


def _capped_fleet(tmp_path, api_key: str, cost_cap_usd: float | None):
    home = tmp_path / "home"
    seed_home(
        home, api_key=api_key, tools_tier={CAPPED_AGENT}, cost_cap_usd=cost_cap_usd
    )
    return boot(home, api_key=api_key, seed=False)


@pytest.fixture
def tight_cap_fleet(tmp_path, live_api_key):
    """`analyst` on the tools tier with a ceiling any single round exceeds."""
    server = _capped_fleet(tmp_path, live_api_key, TIGHT_CAP_USD)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def uncapped_fleet(tmp_path, live_api_key):
    """The same tools-tier fleet with NO ceiling — the shipped default."""
    server = _capped_fleet(tmp_path, live_api_key, None)
    try:
        yield server
    finally:
        server.stop()


def _run(fleet, journey_budget):
    """Drive BRIEF to a settled state; return (task_id, status).

    900s for the same reason `test_live_mail_capability_gate` documents: `confirm: True`
    performs preview AND confirm inside one synchronous request, so a decompose that
    retries is paid before the POST returns.
    """
    code, body = fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=900
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    status = wait_until_settled(fleet, task_id, timeout_s=900)
    journey_budget.note_cost(
        (status.get("cost") or {}).get("total_cost_usd") or 0.0, status
    )
    return task_id, status


def _tools_tier_orders(home, task_id: str) -> list[dict]:
    """Work orders whose step actually resolved onto the tool-calling runtime.

    This is the anti-vacuity check every assertion below leans on. `effective_runtime` is
    written by the step runner before the tier runs and appears nowhere in the HTTP
    projection or the store, so the work order is the only place a case can learn that the
    code it names was reached rather than skipped.
    """
    return [
        o for o in work_orders(home, task_id)
        if o.get("effective_runtime") == "ToolCallingRuntime"
    ]


def _resolved_tiers(home, task_id: str) -> list[tuple]:
    """`(step_id, effective_runtime)` per work order — for failure messages only.

    A case that fails because everything ran native and one that fails because no work
    order was written at all need very different fixes, and an empty list says which.
    """
    return [(o.get("step_id"), o.get("effective_runtime")) for o in work_orders(home, task_id)]


@pytest.mark.live_slow
def test_l1_a_tight_per_step_cap_stops_the_loop_and_says_so_in_the_result(
    tight_cap_fleet, journey_budget,
):
    """With a ceiling below one round's cost, the step returns partial work plus the note.

    Three assertions, and none is redundant:

    - the step reached `ToolCallingRuntime` — without this the rest is vacuous, since a
      native step never consults the cap and would produce no note for reasons that have
      nothing to do with Phase 1 being correct;
    - the note is present in a step artifact — the guard fired end-to-end;
    - the task still cost something — a fleet that spent $0 never called the model at all,
      which would satisfy "the loop stopped" for entirely the wrong reason.
    """
    task_id, status = _run(tight_cap_fleet, journey_budget)
    home = tight_cap_fleet.home

    capped_orders = _tools_tier_orders(home, task_id)
    assert capped_orders, (
        f"no step of task {task_id} resolved onto ToolCallingRuntime, so the thin loop — "
        "and therefore the cost cap — never ran. The plan produced no needs_web work step "
        "on the capped agent, or the profile did not load as kind=create_agent. "
        f"resolved={_resolved_tiers(home, task_id)!r}"
    )

    texts = step_texts(home, task_id)
    noted = {name: t for name, t in texts.items() if CAP_NOTE_PREFIX in t}
    assert noted, (
        f"a step ran on ToolCallingRuntime with cost_cap_usd={TIGHT_CAP_USD} but no step "
        "artifact carries the cost-cap gap note, so the loop never stopped on spend. "
        f"artifacts={sorted(texts)!r} status={status!r}"
    )

    spent = (status.get("cost") or {}).get("total_cost_usd") or 0.0
    assert spent > 0, (
        f"task {task_id} settled having spent ${spent} — the fleet never called the model, "
        "so 'the loop stopped early' is true for a reason unrelated to the cost cap"
    )


@pytest.mark.live_slow
def test_l1b_the_same_brief_without_a_cap_finishes_without_the_note(
    uncapped_fleet, journey_budget,
):
    """L1's control: the note comes from the ceiling, not from the fleet being broken.

    Every L1 assertion is also satisfied by a fleet that cannot complete this brief at all
    — a broken tool, an unreachable provider, a model that always gives up. This case runs
    the identical brief on the identical tools-tier fleet with the ceiling REMOVED. If the
    note appears here too, L1 was measuring a malfunction rather than the guard.

    `cost_cap_usd=None` is the shipped default, so this also pins that Phase 1 is off
    unless configured — the property that makes the feature safe to ship.
    """
    task_id, status = _run(uncapped_fleet, journey_budget)
    home = uncapped_fleet.home

    assert _tools_tier_orders(home, task_id), (
        f"no step of task {task_id} reached ToolCallingRuntime, so this control ran a "
        f"different code path from L1 and cannot control for anything. "
        f"resolved={_resolved_tiers(home, task_id)!r}"
    )

    texts = step_texts(home, task_id)
    noted = {name: t for name, t in texts.items() if CAP_NOTE_PREFIX in t}
    assert not noted, (
        f"the cost-cap gap note appeared on an UNCAPPED fleet: {sorted(noted)!r}. "
        "`over_cost_cap` returns False for cap=None, so either the default stopped being "
        "None or something else emits this note — and L1's green is then meaningless."
    )
