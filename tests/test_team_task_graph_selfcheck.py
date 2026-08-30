"""The step graph's self-check / rework loop (`team_task_graph.py`'s
`self_check`/`rework` nodes + `route_after_check`).

Load-bearing:
- fail-then-pass: `work` runs exactly once, `rework` runs exactly once, `deliver`
  receives `self_check_failed=False`.
- fail-fail (budget exhausted at `max_rework=2`): `rework` runs exactly twice,
  `rework_count==2` at delivery, `deliver` receives `self_check_failed=True` — a
  stuck self-check must still deliver (R5: never loop forever), just flagged.
- pass-immediately: `deliver` runs with no `rework` call at all.
- keep-best on exhaustion: reworks can REGRESS a draft; when the budget runs out,
  `deliver` receives the failing non-blank draft with the FEWEST failures, not the
  latest one. Ties keep the newer draft; a blank draft never qualifies as best.
- No checkpoint-resume test: this graph compiles with `checkpointer=None` by design
  (Decision B) — a crash mid-attempt is not resumable, the next tick spawns a FRESH
  attempt_id and re-runs from `perceive`, so there is no phantom-resume path to test.
"""

from __future__ import annotations

from my_crew.agent.team_task_graph import (
    GUIDANCE_HEADER,
    WAKE_CONTEXT_PREFIX,
    TeamTaskDeps,
    _strip_guidance,
    build_team_task_graph,
)


def _make_deps(*, verdicts: list[tuple[bool, list[str], float]]):
    """`verdicts` is consumed in order, one per `run_self_check` call — the Nth call
    (0-indexed) returns `verdicts[min(n, len(verdicts) - 1)]` so a test can express
    "fail, fail, then keep failing" with a short list."""
    calls: dict[str, object] = {"work_calls": 0, "rework_calls": 0, "deliver_args": None}
    check_calls = {"n": 0}

    def read_handoff() -> str:
        return ""

    def run_work(title, handoff, hook):
        calls["work_calls"] = int(calls["work_calls"]) + 1
        return "draft v0", 0.01

    def run_self_check(result_text, acceptance):
        n = check_calls["n"]
        check_calls["n"] = n + 1
        idx = min(n, len(verdicts) - 1)
        return verdicts[idx]

    def run_rework(title, prior_output, failures):
        calls["rework_calls"] = int(calls["rework_calls"]) + 1
        return f"{prior_output}+fix{calls['rework_calls']}", 0.02

    def deliver_step(text, version, self_check_failed):
        calls["deliver_args"] = (text, version, self_check_failed)
        return True, f"[done] {text}"

    deps = TeamTaskDeps(
        read_handoff=read_handoff, run_work=run_work, run_self_check=run_self_check,
        run_rework=run_rework, deliver_step=deliver_step,
    )
    return deps, calls


def test_fail_then_pass_reworks_once_and_delivers_not_failed():
    deps, calls = _make_deps(verdicts=[(False, ["thiếu phần A"], 0.4), (True, [], 0.9)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 1
    assert result["self_check_failed"] is False
    assert result["rework_count"] == 1
    assert calls["deliver_args"][2] is False  # self_check_failed passed to deliver_step
    assert calls["deliver_args"][0] == "draft v0+fix1"


def test_fail_fail_exhausts_rework_budget_and_delivers_flagged():
    deps, calls = _make_deps(verdicts=[(False, ["vẫn thiếu A"], 0.3)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 2  # capped at max_rework=2, never loops forever
    assert result["rework_count"] == 2
    assert result["self_check_failed"] is True
    assert calls["deliver_args"][2] is True
    # Every round failed with the SAME failure count — a keep-best tie, which goes to
    # the newest draft: deliver runs with the LATEST result, not a blank/aborted one.
    assert calls["deliver_args"][0] == "draft v0+fix1+fix2"


def test_pass_immediately_never_reworks():
    deps, calls = _make_deps(verdicts=[(True, [], 1.0)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert calls["work_calls"] == 1
    assert calls["rework_calls"] == 0
    assert result["self_check_failed"] is False
    assert result.get("rework_count", 0) == 0
    assert calls["deliver_args"][0] == "draft v0"


def test_blank_acceptance_skips_check_semantics_but_graph_still_uses_default_deps_open_gate():
    """Not `default_team_task_deps` here (fake deps), but the SHAPE of "acceptance
    blank -> trivially passes" is asserted at the real wiring level in
    `test_team_task_graph.py`'s existing regression coverage; this test only pins
    that a fake `run_self_check` returning passed=True with no acceptance text set
    behaves identically to the "criteria configured and passed" path — no special
    casing inside the graph itself for blank acceptance (that logic lives in
    `default_team_task_deps._run_self_check`, not in the graph's routing)."""
    deps, calls = _make_deps(verdicts=[(True, [], 1.0)])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": ""})

    assert calls["rework_calls"] == 0
    assert result["self_check_failed"] is False


def test_exhaustion_delivers_the_best_draft_when_reworks_regress():
    """A rework round can make the draft WORSE (live shape: the checker demanded data
    the loop could not fetch and the model blanked sourced rows instead of flagging
    the gap). On budget exhaustion, deliver must receive the draft that failed with
    the FEWEST failures — here the middle one — not the latest."""
    deps, calls = _make_deps(verdicts=[
        (False, ["thiếu A", "thiếu B"], 0.3),   # draft v0
        (False, ["thiếu B"], 0.5),              # draft v0+fix1 — best (1 failure)
        (False, ["thiếu A", "thiếu B", "thiếu C"], 0.2),  # draft v0+fix1+fix2 regressed
    ])
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có A và B"})

    assert calls["rework_calls"] == 2
    assert result["self_check_failed"] is True
    assert calls["deliver_args"][2] is True
    assert calls["deliver_args"][0] == "draft v0+fix1"
    assert result["result_text"] == "draft v0+fix1"


def test_a_blank_rework_never_beats_a_real_draft():
    """The empty-result guard grades a blank as exactly ONE failure — without the
    non-blank gate, wiping the table would "improve" on any real draft with two
    failures. The real first draft is what must ship."""
    verdicts = [
        (False, ["thiếu X", "thiếu Y"], 0.4),  # real draft, 2 failures
        (False, ["bước không trả về nội dung nào (kết quả rỗng)"], 1.0),  # blank, 1
    ]
    check_calls = {"n": 0}
    deliver_args: dict = {}

    def run_self_check(result_text, acceptance):
        n = check_calls["n"]
        check_calls["n"] = n + 1
        return verdicts[min(n, len(verdicts) - 1)]

    def deliver_step(text, version, self_check_failed):
        deliver_args["v"] = (text, version, self_check_failed)
        return True, f"[done] {text}"

    deps = TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda title, handoff, hook: ("bảng giá có nguồn", 0.01),
        run_self_check=run_self_check,
        run_rework=lambda title, prior, failures: ("", 0.02),  # model blanks the draft
        deliver_step=deliver_step,
    )
    graph = build_team_task_graph(deps=deps)
    result = graph.invoke({"step_title": "draft", "acceptance": "phải có X và Y"})

    assert result["self_check_failed"] is True
    assert deliver_args["v"][0] == "bảng giá có nguồn"
    assert deliver_args["v"][2] is True


def test_coordinator_guidance_is_consumed_by_the_first_rework_only():
    """The coordinator's "last attempt was rejected" note is advice about the draft
    the PREVIOUS attempt delivered. The first rework acts on it; by the second round
    that draft no longer exists, so replaying the note tells the model to re-fix what
    it just fixed — directly contradicting the fresh `check_failures` of round 2.

    Measured on the vòng-6 bench: the note was byte-identical across both rework rounds
    of every multi-rework attempt while the failures had moved on. `perceive` runs once
    per attempt and the loop is `rework -> self_check -> rework`, so the handoff (which
    carries the note) never gets recomputed — the strip has to happen in `rework`.

    The upstream deps' content in the same block must SURVIVE the strip: it is standing
    context, not a one-shot instruction.
    """
    handoff_from_perceive = (
        "KẾT QUẢ BƯỚC TRƯỚC:\nbảng giá 3 công cụ\n\n"
        f"{GUIDANCE_HEADER}\nLần trước thiếu mục B, hãy thêm."
    )
    handoffs: list[str] = []

    def run_rework(title, prior_output, failures, handoff=""):
        handoffs.append(handoff)
        return f"{prior_output}+fix{len(handoffs)}", 0.02

    deps = TeamTaskDeps(
        read_handoff=lambda: handoff_from_perceive,
        run_work=lambda title, handoff, hook: ("draft v0", 0.01),
        run_self_check=lambda text, acceptance: (False, ["vẫn thiếu A"], 0.3),
        run_rework=run_rework,
        deliver_step=lambda text, version, failed: (True, f"[done] {text}"),
    )
    graph = build_team_task_graph(deps=deps)
    graph.invoke({"step_title": "draft", "acceptance": "phải có phần A"})

    assert len(handoffs) == 2, "budget is 2 reworks"
    assert "Lần trước thiếu mục B" in handoffs[0], "first rework still acts on it"
    assert "Lần trước thiếu mục B" not in handoffs[1], (
        "second rework must not replay guidance the first one already consumed"
    )
    assert "bảng giá 3 công cụ" in handoffs[1], "upstream deps' content is not one-shot"


def test_strip_keeps_the_standing_wake_context_line():
    """A cross-review rework row stores NO coordinator guidance, so the runner's wake
    line ("this is fix round N — fix the listed items, don't start over") is the whole
    guidance block. That line describes the attempt, not a draft, so it stays true every
    round — and its "không làm lại từ đầu" constraint matters most on the later rounds,
    the exact rounds the strip runs on. Dropping the block wholesale would lose it.
    """
    wake = f"{WAKE_CONTEXT_PREFIX} đây là vòng SỬA thứ 2 — không làm lại từ đầu."
    only_wake = f"KẾT QUẢ BƯỚC TRƯỚC:\nsố liệu quý 3\n\n{GUIDANCE_HEADER}\n{wake}"

    kept = _strip_guidance(only_wake)

    assert wake in kept, "standing framing survives; it is not about a stale draft"
    assert "số liệu quý 3" in kept

    # With BOTH present the line is kept and only the coordinator's note goes.
    both = f"{GUIDANCE_HEADER}\n{wake}\nLần trước thiếu mục B, hãy thêm."
    kept_both = _strip_guidance(both)
    assert wake in kept_both
    assert "thiếu mục B" not in kept_both


def test_strip_anchors_on_the_last_header_not_an_echoed_one():
    """Deps content is unsanitised model output: an upstream draft that quotes the
    header would, under a first-match search, truncate the handoff there — taking the
    CEO brief, the clarify answers and every deps artifact after it with it. The real
    note is always appended LAST, so anchor on the last occurrence.
    """
    handoff = (
        f"KẾT QUẢ BƯỚC TRƯỚC:\nnháp cũ trích lại '{GUIDANCE_HEADER}' abc\n\n"
        "phần quan trọng\n\n"
        f"{GUIDANCE_HEADER}\nLần trước thiếu mục B."
    )

    kept = _strip_guidance(handoff)

    assert "phần quan trọng" in kept, "content after an echoed header must survive"
    assert "Lần trước thiếu mục B" not in kept, "the real note is still dropped"
