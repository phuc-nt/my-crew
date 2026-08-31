"""L2 — a dep's contribution to the next step's PROMPT is bounded, its artifact is not.

Phase 2 capped each dep at `HANDOFF_DEP_CHAR_CAP` chars when building a step's prompt,
appending a pointer to the artifact that still holds the whole thing. `tests/
test_fanout_result_cap.py` pins the function offline against hand-built text. What it
cannot show is that the cap sits on the PROMPT path and only there — the same
`_read_deps_handoff` also feeds the work-order writer and the reviewer's context, and
Phase 2's central claim is that those two keep the FULL text while the prompt gets the
bounded copy. Proving that needs both readers observing one real run.

**Why this case needs no fleet seam.** Unlike the cost-cap and audit cases, the dep cap
lives in the graph, not in a runtime tier: it applies to any step that has deps,
whichever tier that step resolved onto. So this runs on a stock fleet, which also makes
it the one live case whose subject is exercised by the fleet users actually ship.

**The measurement is a comparison, not a threshold.** Asserting "the prompt is under
8000 chars" would pass on a fleet where the model simply wrote a short first step and the
cap never engaged — green for the wrong reason, exactly the vacuity v92 taught this suite
to design against. So the case first finds a dep whose stored artifact EXCEEDS the cap
(without one, there is nothing to bound and the case skips rather than lies), then checks
the three things that follow: the prompt carries the cut marker, the work order still
carries the full text, and the prompt is genuinely shorter than the artifact.
"""

from __future__ import annotations

import pytest

from tests.fullflow_live.topology import (
    boot,
    seed_home,
    step_texts,
    transcript_events,
    wait_until_settled,
    work_orders,
)

#: The literal, model-independent half of the pointer `_cap_dep_text` appends. Copied
#: rather than imported for the reason L1 copies its note prefix: an import would make
#: this case follow a rename into a string the product no longer emits, and pass.
CUT_MARKER = "…[đã cắt "

#: Named for the failure message only. The assertions compare the prompt against the
#: stored artifact rather than against this number, so a future retune of the cap does
#: not silently invalidate the case — see the module docstring.
DEP_CHAR_CAP = 8000

#: Multi-stage so it reaches the team lane (a lookup-shaped brief runs as one sprint step
#: with no deps at all, and a step with no deps has no handoff to cap). Each stage asks
#: for enumerated detail WITH per-item explanation, because the cap only engages once a
#: dep's stored text passes 8000 chars — roughly 2000 tokens, which a terse three-bullet
#: answer will not reach. Pinned offline by
#: `test_the_live_output_guard_brief_still_reaches_the_team_lane`.
BRIEF = (
    "Nghiên cứu rồi lập cẩm nang vận hành đội kỹ thuật trong tuần: "
    "(1) liệt kê ÍT NHẤT 12 rủi ro vận hành thường gặp của một đội phát triển phần mềm, "
    "mỗi rủi ro viết một đoạn đầy đủ gồm dấu hiệu nhận biết, hậu quả, và cách phòng ngừa, "
    "(2) với mỗi rủi ro ở bước 1, nêu một chỉ số đo lường cụ thể và ngưỡng cảnh báo, "
    "(3) tổng hợp tất cả thành bảng cẩm nang và đề xuất 3 việc cần làm tuần sau."
)


@pytest.fixture
def stock_fleet(tmp_path, live_api_key):
    """A default-seeded fleet — no runtime seam, because the dep cap is tier-agnostic."""
    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key)
    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


def _prompt_text(events: list[dict]) -> str:
    """Every `llm_request` message body of one attempt, concatenated.

    `llm_client` records the messages verbatim on the transcript, which is the only place
    the assembled prompt is observable — the work order deliberately stores the step-level
    input instead, and that difference is exactly what this case measures.
    """
    out: list[str] = []
    for event in events:
        if event.get("t") != "llm_request":
            continue
        for message in event.get("messages") or []:
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                out.append(content)
    return "\n".join(out)


@pytest.mark.live_slow
def test_l2_a_long_dep_reaches_the_next_prompt_cut_but_its_artifact_stays_whole(
    stock_fleet, journey_budget,
):
    """The next step is shown a bounded copy; the full text stays on disk and in replay.

    Four assertions, each closing a different way the feature could be broken while the
    others still passed:

    - some dep artifact exceeds the cap — without this there is nothing to bound, and the
      remaining assertions would be vacuous (the case skips instead of pretending);
    - a downstream prompt carries the cut marker — the cap engaged on the prompt path;
    - that step's work order still carries text longer than the cap — Phase 2's explicit
      carve-out, since a truncated work order would no longer replay the run it records;
    - the prompt's copy is shorter than the artifact — proof the marker accompanies a real
      cut rather than being appended to text that was passed through whole.
    """
    code, body = stock_fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=900
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    status = wait_until_settled(stock_fleet, task_id, timeout_s=900)
    journey_budget.note_cost(
        (status.get("cost") or {}).get("total_cost_usd") or 0.0, status
    )

    home = stock_fleet.home
    texts = step_texts(home, task_id)
    long_artifacts = {name: t for name, t in texts.items() if len(t) > DEP_CHAR_CAP}
    if not long_artifacts:
        pytest.skip(
            "no step of this run produced more than "
            f"{DEP_CHAR_CAP} chars, so no dep was large enough for the cap to engage. "
            "This is a property of how verbosely the model answered, not a product "
            f"failure. sizes={ {n: len(t) for n, t in texts.items()} !r}"
        )

    orders = work_orders(home, task_id)
    with_deps = [o for o in orders if o.get("deps")]
    assert with_deps, (
        f"task {task_id} produced a >{DEP_CHAR_CAP}-char artifact but no step with deps, "
        "so nothing ever read that text forward and the cap had no prompt to bound. "
        f"steps={[(o.get('step_id'), o.get('deps')) for o in orders]!r}"
    )

    marked = [
        (order, prompt)
        for order in with_deps
        for prompt in [
            _prompt_text(transcript_events(home, task_id, str(order.get("transcript") or "")))
        ]
        if CUT_MARKER in prompt
    ]
    assert marked, (
        f"a dep artifact exceeds {DEP_CHAR_CAP} chars "
        f"({ {n: len(t) for n, t in long_artifacts.items()} !r}) and a downstream step "
        "read it, but no prompt of that step carries the cut marker — the prompt builder "
        "is passing the dep through uncapped. "
        f"dep_steps={[(o.get('step_id'), o.get('deps')) for o in with_deps]!r}"
    )

    order, prompt = marked[0]
    full_handoff = str(order.get("handoff") or "")
    assert len(full_handoff) > DEP_CHAR_CAP, (
        f"step {order.get('step_id')!r} saw a capped prompt but its work order records "
        f"only {len(full_handoff)} chars of handoff. The work order is the replay record "
        "and Phase 2 deliberately leaves it uncapped; a truncated one no longer "
        "reproduces the run it claims to document."
    )

    longest = max(long_artifacts.values(), key=len)
    assert len(prompt) < len(full_handoff), (
        f"the prompt ({len(prompt)} chars) is not shorter than the uncapped handoff "
        f"({len(full_handoff)} chars) even though it carries the cut marker, so the "
        "marker is being appended to text that was never actually cut. "
        f"longest_artifact={len(longest)}"
    )
