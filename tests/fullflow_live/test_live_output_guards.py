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

**Why the long dep is supplied rather than requested.** The first version of this case
asked the MODEL to write past 8000 chars ("at least 12 risks, each a full paragraph, plus
a metric and a threshold each"). Measured: the brief that was heavy enough to pass the cap
was also heavy enough to blow the 900s deadline — the run reached 1282s without ever
reaching the assertions, so the guard stayed unverified across the whole release. The
brief had to be "big enough for the cap to engage, small enough to settle", and that
window is a property of how verbosely a given model answers on a given day, not something
a test can pin.

So `oversized_dep_injector` supplies the long text instead: the moment a step's artifact
lands on disk, the watcher rewrites its `result_text` to a deterministic ~9000-char body,
and KEEPS it that way for the rest of the run. Holding it is not belt-and-braces — a step
artifact is not write-once, and run 5 (2026-09-01) failed on exactly that: the injection
landed on `step-1.json`, the run later re-delivered that step, and the case found 2406
chars where it had written 9057. Re-asserting each pass is what makes "the dep is oversized
when a downstream step reads it" true rather than merely likely.
Everything downstream of that write is untouched real product — `_read_deps_handoff`
re-reads the artifact from disk when it builds the next step's prompt (it holds no
in-memory copy), so the cap engages on genuinely oversized input, on a real fleet, with a
real model reading the capped result. What the injector removes is only the model's
freedom to be too terse or too slow, which is precisely the part that was never the
subject under test.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

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
#: with no deps at all, and a step with no deps has no handoff to cap). Pinned offline by
#: `test_the_live_output_guard_brief_still_reaches_the_team_lane`.
#:
#: Deliberately MODEST in volume. The earlier phrasing ("at least 12 risks, each a full
#: paragraph, plus a metric and a threshold each") existed to push a dep past 8000 chars
#: by asking the model to write long, and that is what made the run take 1282s against a
#: 900s deadline. `oversized_dep_injector` now supplies the long text, so this brief only
#: has to do the one thing the injector cannot: produce a multi-step DAG in which some
#: step actually READS an upstream step's artifact.
#:
#: Shaped as a FAN-IN — two independent parts joined by a third — and that shape is the
#: premise, learned on 2026-09-02 by paying for it. The earlier two-stage chain ("liệt kê
#: rủi ro, rồi dựa trên đó tổng hợp") settled as ONE step, `('step1', [])`, on a plan the
#: router had accepted as `mode=team, shape=custom`: `fold_unjustified_steps` now merges a
#: step into its single predecessor whenever the two owners share a capability tuple
#: (`team_task_roster.Capability`: tier, web, mail, model), and every worker in this
#: fixture's stock fleet shares one. Correct product behaviour — a chain across two names
#: with the same tools is one person's work split across two cold starts — but it means
#: NO linear chain can carry a dep edge on this fleet, whoever the model assigns it to.
#: A fan-in edge survives by construction: the fold only ever considers a step with
#: exactly one dep, and the join has two. Measured offline on the live model
#: (claude-haiku-4.5, 3/3): three steps across three workers, the join depending on both
#: parts, zero folds.
BRIEF = (
    "Lập cẩm nang vận hành đội kỹ thuật trong tuần, làm theo ba phần: "
    "(1a) liệt kê 4 rủi ro vận hành thường gặp của một đội phát triển phần mềm, "
    "mỗi rủi ro nêu dấu hiệu nhận biết và cách phòng ngừa; "
    "(1b) độc lập với 1a và do một người khác làm song song, liệt kê 4 thói quen tốt "
    "hằng tuần của đội (họp, review, theo dõi tiến độ), mỗi thói quen nêu lợi ích và "
    "cách duy trì; "
    "(2) chỉ sau khi có cả 1a và 1b, tổng hợp hai danh sách thành bảng cẩm nang ngắn "
    "và đề xuất 3 việc cần làm tuần sau."
)

#: What the case actually delegates. The `team:` prefix is load-bearing, and run 3
#: (2026-09-01) is why: that run SETTLED inside the deadline having spent one decompose's
#: worth of tokens ($0.0072) and recorded exactly ONE step, `('research', [])`. No dep
#: edge, so nothing read the injected text forward and the cap had no prompt to bound.
#:
#: The planner was not at fault — 4 offline decompose samples of the brief of the day each
#: produced a 3-step chain across THREE assignees with zero folds. But the assignee split
#: is a model choice, not a property of the brief. On a run where the model puts every
#: step on one person, `downgrade_to_sprint` (`sprint_intake.py`, `len(assignees) != 1`)
#: converts the whole plan into a single sprint step. That is correct product behaviour
#: (a one-person DAG buys only coordination cost) and fatal to a case whose entire subject
#: is a dep edge — so the lane has to be pinned rather than hoped for.
#:
#: `strip_mode_prefix` turns this prefix into `forced_mode="team"`, which
#: `ops_assign_team_task` honours by skipping the downgrade outright ("CEO gõ team: là
#: quyết định của người giao việc, không phải phỏng đoán"). A real product affordance, not
#: a test-only seam — and the brief reaches the planner byte-identical, since
#: `strip_mode_prefix("team: " + BRIEF)` returns exactly `BRIEF`.
#:
#: `BRIEF` itself stays bare so the offline pin
#: `test_the_live_output_guard_brief_still_reaches_the_team_lane` keeps checking the
#: router against the words themselves, rather than against a prefix that would satisfy
#: it trivially.
DELEGATE_BRIEF = "team: " + BRIEF


#: How much oversized text the injector writes. Comfortably past the 8000-char cap so the
#: cut is unambiguous, but not so far past that the capped prompt stops resembling one a
#: real run would build.
INJECTED_DEP_CHARS = 9000

#: Longer than the 900s the rest of the live suite uses, because this case is structurally
#: the longest journey in it — and the number was set by measurement, not by taste.
#:
#: Run 2 (2026-09-01) settled at ~960s and the 900s poll cut it off at ~900s. Nothing about
#: the measurement had failed: the artifacts that run left behind satisfy all four
#: assertions below (dep artifact 9057 chars > cap · cut marker present 4x in the prompt ·
#: work order handoff still 9057 chars and marker-free · prompt copy shorter than the
#: artifact). Only the wait was short.
#:
#: Why the brief is NOT the lever, also measured: 8 decompose samples across the current
#: phrasing and a trimmed one with the research verb removed. Both plan 3-4 steps, and both
#: still request web on 3/4. Dropping "Nghiên cứu" made it WORSE (4 steps instead of 3), so
#: trimming buys no wall time — every other live case settles on one step or an early park,
#: while this one needs a chain of model-driven steps to have a dep edge at all.
#:
#: Raising this does not weaken any assertion; it only stops the poll from ending a run
#: that was still progressing. Kept as a named constant so the next retune is a deliberate
#: edit with this note attached.
SETTLE_TIMEOUT_S = 1500


def _oversized_dep_text() -> str:
    """~9000 chars of real Vietnamese operations prose, built deterministically.

    Real sentences rather than filler: the step that receives this text still runs its own
    `self_check` against the acceptance criteria, and a wall of lorem would push that step
    toward `needs_decision` for reasons unrelated to the cap. The assertions do not depend
    on the step's terminal status, but a run that derails is a run that costs money and
    measures nothing.

    Numbered so the truncation is visible by eye in a failure dump: the capped copy ends
    mid-list, and which entry it ends on says exactly how many chars survived.
    """
    entries = [
        "Bàn giao thiếu ngữ cảnh: người nhận phải hỏi lại từ đầu, mỗi lần hỏi mất nửa "
        "ngày. Dấu hiệu là số câu hỏi làm rõ tăng sau mỗi lần chuyển việc. Phòng ngừa "
        "bằng mẫu bàn giao có sẵn ô bối cảnh, ràng buộc và tiêu chí nghiệm thu.",
        "Phụ thuộc chéo không ai theo dõi: hai nhóm cùng chờ nhau, không nhóm nào báo "
        "chậm vì ai cũng nghĩ mình đang chờ chứ không phải đang trễ. Dấu hiệu là việc "
        "đứng yên nhiều ngày mà trạng thái vẫn 'đang làm'.",
        "Ước lượng theo trường hợp thuận lợi: kế hoạch chỉ đúng khi không có gì bất "
        "thường, nên tuần nào cũng trễ. Phòng ngừa bằng cách tách ước lượng phần chắc "
        "chắn và phần rủi ro, rồi theo dõi riêng tỉ lệ hai phần đó.",
        "Kiểm thử chạy sau khi đã gộp mã: lỗi phát hiện muộn thì chi phí sửa nhân lên "
        "vì đã có mã khác xây trên nền hỏng. Dấu hiệu là số lần phải quay đầu tăng dần.",
        "Cảnh báo quá nhiều đến mức không ai đọc: hệ thống báo động liên tục cho việc "
        "không cần hành động, nên khi có sự cố thật thì tín hiệu bị chìm.",
        "Tri thức nằm trong đầu một người: người đó nghỉ là cả luồng việc dừng. Dấu "
        "hiệu là mọi câu hỏi về một mảng đều dồn về đúng một cái tên.",
        "Nợ kỹ thuật không được ghi nhận: mỗi lần vá nhanh đều hợp lý riêng lẻ, nhưng "
        "cộng dồn thì thời gian thêm một tính năng tăng đều mà không ai giải thích được.",
        "Môi trường chạy thử lệch môi trường thật: mã chạy đúng khi thử rồi hỏng khi "
        "phát hành, và mỗi lần điều tra đều tốn công dựng lại hiện trường.",
        "Quyết định không được ghi lại: ba tháng sau không ai nhớ vì sao chọn phương án "
        "này, nên tranh luận cũ lặp lại từ đầu với đúng các lập luận cũ.",
        "Việc gấp chen ngang liên tục: mỗi lần chen là một lần bỏ dở, và chi phí quay "
        "lại mạch cũ lớn hơn nhiều so với thời gian xử lý việc gấp.",
        "Tiêu chí nghiệm thu mơ hồ: 'làm xong cho ổn' nghĩa là mỗi người hiểu một kiểu, "
        "nên việc bị trả lại nhiều vòng mà không bên nào sai.",
        "Giám sát chỉ đo tài nguyên chứ không đo trải nghiệm: máy chủ rảnh, bộ nhớ dư, "
        "mà người dùng vẫn chờ lâu, và không có số liệu nào chỉ ra chỗ nghẽn.",
    ]
    out: list[str] = ["Cẩm nang rủi ro vận hành đội kỹ thuật — bản đầy đủ.\n"]
    index = 0
    # Cycle the entries until past the target: a fixed list long enough to reach 9000
    # chars would be unreadable, and repetition with a running number keeps every char
    # accounted for while staying obviously deterministic.
    while sum(len(part) for part in out) < INJECTED_DEP_CHARS:
        entry = entries[index % len(entries)]
        out.append(f"\n{index + 1}. {entry}")
        index += 1
    return "".join(out)


class _DepInjector:
    """Watches a task's artifact dir and enlarges every work artifact that lands.

    A thread rather than a post-settle rewrite: the cap is applied while the run is in
    flight, when the graph builds the next step's prompt, so the text has to be on disk
    before that step starts. Rewriting after `wait_until_settled` would change nothing
    the run ever read.

    Rewrites `result_text` in place and leaves every other field alone, so the artifact
    stays exactly the shape `_deliver` wrote — the product is never asked to read a
    payload it would not itself produce.
    """

    def __init__(self, artifact_dir: Path) -> None:
        self._dir = artifact_dir
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        #: The FIRST artifact this injector enlarged, for the case's premise assertion.
        #: A run where nothing was ever injected must fail loudly rather than measure a
        #: cap that never engaged.
        self.injected: str | None = None
        self.injected_chars = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        text = _oversized_dep_text()
        while not self._stop.is_set():
            # Re-asserted every pass, not injected once. Run 5 (2026-09-01) is why: the
            # injector enlarged `step-1.json` to 9057 chars, the run later re-delivered
            # that step, and by the time the case looked the artifact was back to 2406 —
            # so the premise assertion failed on a run where the injection had genuinely
            # happened. A step's artifact is not write-once (a rework round re-delivers
            # it, and a first delivery can land after an early inject), so holding the
            # text oversized for the whole run is the only way the dep is still oversized
            # when a downstream step actually reads it.
            #
            # EVERY work artifact is enlarged, not only the first one seen. An earlier
            # version latched onto the first artifact and left the rest alone, which
            # measured nothing on a fan-out plan: the planner now merges same-tier
            # steps, so the first artifact to land was a sibling the synthesis step
            # read alongside two untouched ones, and the run the case looked at had
            # every dep under the cap. With all of them oversized, whichever dep the
            # downstream step reads is the oversized one. `self.injected` still reports
            # the first artifact enlarged, so the premise assertion has a name.
            for path in sorted(self._dir.glob("step-*.json")):
                # Skip review verdicts: a `step-<n>-review-<r>.json` is read through
                # a different branch of `_read_deps_handoff` and enlarging one would
                # test the reviewer path while claiming to test the work path.
                if "-review-" in path.name:
                    continue
                self._enlarge(path, text)
            self._stop.wait(0.5)

    def _enlarge(self, path: Path, text: str) -> bool:
        """Rewrite one artifact's `result_text`, atomically. Returns whether it happened.

        Tolerant of a torn read for the same reason `read_step_artifact` is: the writer
        renames into place, but this reader races that rename by design and must retry
        rather than crash the thread the case depends on.
        """
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(payload, dict) or not payload.get("result_text"):
            return False  # a status-only fallback artifact — nothing reads it forward
        if payload["result_text"] == text:
            # Already carries the injected text. Returning True keeps the caller's "this
            # is the dep we chose" latch intact without rewriting the file every 0.5s,
            # which would race the product's own writer for no reason.
            return True
        payload["result_text"] = text
        tmp = path.with_suffix(".tmp-injector")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            return False
        if self.injected is None:
            self.injected = path.name
        self.injected_chars = len(text)
        return True


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
      remaining assertions would be vacuous (the case fails instead of pretending, since
      the injector is supposed to guarantee it);
    - a downstream prompt carries the cut marker — the cap engaged on the prompt path;
    - that step's work order still carries text longer than the cap — Phase 2's explicit
      carve-out, since a truncated work order would no longer replay the run it records;
    - the prompt's copy is shorter than the artifact — proof the marker accompanies a real
      cut rather than being appended to text that was passed through whole.
    """
    code, body = stock_fleet.post(
        "/api/control-plane/delegate", {"brief": DELEGATE_BRIEF, "confirm": True},
        timeout=900,
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    home = stock_fleet.home
    # Started only once the task_id is known: the injector watches ONE task's artifact
    # dir, so it cannot enlarge anything a different task wrote.
    injector = _DepInjector(home / ".data" / "artifacts" / "team-tasks" / task_id)
    injector.start()
    try:
        status = wait_until_settled(stock_fleet, task_id, timeout_s=SETTLE_TIMEOUT_S)
    finally:
        injector.stop()
    journey_budget.note_cost(
        (status.get("cost") or {}).get("total_cost_usd") or 0.0, status
    )

    assert injector.injected, (
        "the injector never found a step artifact carrying `result_text` to enlarge, so "
        "no dep was oversized and every assertion below would be vacuous. Either the run "
        "produced no delivered step, or the artifact layout moved. "
        f"artifacts={sorted(step_texts(home, task_id))!r}"
    )

    texts = step_texts(home, task_id)
    long_artifacts = {name: t for name, t in texts.items() if len(t) > DEP_CHAR_CAP}
    assert long_artifacts, (
        f"the injector rewrote {injector.injected!r} to {injector.injected_chars} chars, "
        f"but no artifact now reads longer than {DEP_CHAR_CAP} — something overwrote it "
        "after the injection (a rework round re-delivering the step would do this). "
        f"sizes={ {n: len(t) for n, t in texts.items()} !r}"
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

    # What "actually cut" means, measured against the dep rather than the whole prompt.
    #
    # Run 4 (2026-09-01) is why this is not `len(prompt) < len(full_handoff)`. That
    # comparison read 52235 < 9057 and failed while the cap was working perfectly: the
    # prompt is the WHOLE prompt (role preamble, brief, task context, and the capped dep),
    # while `handoff` is one dep's text alone. They are not commensurable quantities, so
    # the comparison could never detect truncation — it passed in earlier runs only
    # because the surrounding prompt happened to be smaller than the dep.
    #
    # The cap's real promise is per-dep and self-describing: `_cap_dep_text` keeps
    # `HANDOFF_DEP_CHAR_CAP` chars and appends a marker stating how many it dropped. So
    # read the number the product itself wrote and check it against the artifact on disk.
    # That is a claim only a genuinely truncated dep can satisfy, and it stays true no
    # matter how large the rest of the prompt grows.
    dropped = re.search(rf"{re.escape(CUT_MARKER)}(\d+) ký tự", prompt)
    assert dropped, (
        f"the prompt of step {order.get('step_id')!r} carries the cut marker but not the "
        f"dropped-character count that `_cap_dep_text` always writes with it. "
        f"marker_context={prompt[max(0, prompt.find(CUT_MARKER) - 80):][:200]!r}"
    )
    dropped_chars = int(dropped.group(1))
    assert dropped_chars > 0, (
        f"the marker reports {dropped_chars} characters dropped, so nothing was actually "
        "cut and the pointer is decorating an untruncated dep."
    )

    # The dep that got cut is the one whose length the marker's arithmetic reconstructs:
    # kept + dropped == the artifact as stored. Checking against every oversized artifact
    # (not just the longest) keeps this honest when a fan-in step reads more than one.
    reconstructed = DEP_CHAR_CAP + dropped_chars
    assert any(abs(len(t) - reconstructed) <= 200 for t in long_artifacts.values()), (
        f"the marker says {dropped_chars} chars were dropped past a ~{DEP_CHAR_CAP}-char "
        f"head, implying a dep of about {reconstructed} chars, but no artifact of this "
        f"task is that size. The prompt is reporting a cut that does not correspond to "
        f"any stored dep. artifact_sizes={ {n: len(t) for n, t in long_artifacts.items()} !r}"
    )

    # And the whole point of the cap: the dep reached the prompt SHORTER than it is on
    # disk, while the artifact itself stayed whole. `full_handoff` is the uncapped record.
    # Per dep, not per handoff: the reader can be a gather step with several deps
    # (measured: a runtime fan-out split the long step, and the gather's record held
    # 36k chars across its shards while the marker cut one 9k dep), so the tail of the
    # cut artifact is what must be in the record and out of the prompt.
    cut_artifact = next(
        t for t in long_artifacts.values() if abs(len(t) - reconstructed) <= 200
    )
    tail = cut_artifact[-300:]
    assert tail not in prompt, (
        f"step {order.get('step_id')!r} carries the cut marker yet its prompt still ends "
        f"with the tail of the {len(cut_artifact)}-char dep — the marker decorates a dep "
        "that was passed through whole."
    )
    assert len(full_handoff) >= len(cut_artifact), (
        f"step {order.get('step_id')!r} recorded only {len(full_handoff)} chars of handoff "
        f"for a {len(cut_artifact)}-char dep: the replay record is capped too, so a replay "
        "could not re-read what the step was actually given."
    )
