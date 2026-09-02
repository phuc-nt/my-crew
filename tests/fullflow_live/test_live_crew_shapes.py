"""Live: the router picks only the surviving crew shapes, and records which one.

Context-crew says a crew is worth its coordination cost only when the plan has a
boundary one strong agent cannot cross inside its own context: an independent grader
(`do_review`) or a sensitive tool with its own permission boundary
(`permission_chain`). Parallel sources (`fanout`) were a third shape until the bench
killed it — blind-judged, the crew beat a sprint 4/12 times — so a fan-out-shaped plan
now runs as a sprint too. Everything else runs as a sprint. The
scripted fullflow suite pins the rule over stub plans; these cases prove that a REAL
decompose model, given a brief written for each shape, produces a plan the rule
recognises — and that the route row names the shape so the bench can score it.

Each case stops as early as its claim allows: S1/S3/S4 stop at the route (no step
runs), S2 pumps only until the reviewer row exists, because the claim there is about
WHO reviews, which only the runtime decides.
"""

from __future__ import annotations

from tests.fullflow_live.conftest import requires_search
from tests.fullflow_live.test_live_routing import _assign


def _steps(run, task_id: str) -> dict:
    """The stored step rows with their routing flags, keyed by step_id."""
    store = run.h.store()
    try:
        return {row["step_id"]: store.get_step(task_id, row["step_id"])
                for row in run.h.step_rows(task_id)}
    finally:
        store.close()


@requires_search
def test_s1_a_forced_team_on_a_source_listing_brief_is_recorded_as_custom(live_run):
    """Five named platforms → the model still writes ≥2 parallel dep-less web steps,
    but since the fan-out shape was killed that plan matches no surviving shape: a
    CEO-forced `team:` keeps the crew (the prefix is the human's decision) and records
    `shape="custom"`, never `fanout`. The lane is forced so the case measures the
    SHAPE the model writes and the label the router gives it, not the heuristic."""
    run = live_run()
    out = _assign(run, (
        "team: So sánh phí sàn và chính sách vận chuyển của 5 sàn: Shopee, Lazada, "
        "Tiki, Sendo, TikTok Shop — gộp thành bảng so sánh có ghi nguồn từng con số."
    ))
    route = out["route"]
    assert (route.get("mode"), route.get("source")) == ("team", "prefix"), route
    assert route.get("shape") == "custom", route
    assert route.get("signals", {}).get("independent_sources", 0) >= 4, route

    steps = _steps(run, out["task_id"])
    branches = [s for s in steps.values() if s.needs_web and not s.deps]
    assert len(branches) >= 2, (
        f"toả ra phải có ≥2 bước thu thập song song (deps rỗng, needs_web): "
        f"{[(s.step_id, s.deps, s.needs_web) for s in steps.values()]}"
    )


def test_s2_a_brief_asking_for_a_cross_check_gets_an_independent_reviewer(live_run):
    """"soát chéo" is the do+review shape: a small plan stays a crew ONLY to buy a
    grader who is not the author. The route names the shape at assign time; the
    reviewer row is minted by the ticker once the work lands, so the case pumps
    until that row exists and then checks the reviewer is a different agent.

    `auto_confirm`: the work step must actually RUN for the reviewer row to exist, and
    a fleet that holds every team task for CEO confirmation never dispatches it — the
    six ticks all passed over a task waiting on a confirm nobody in a test gives
    (measured: no review row after 6 ticks, every step still pending)."""
    run = live_run(auto_confirm=True)
    out = _assign(run, (
        "team: Viết giúp anh bản mô tả phạm vi 1 trang cho tính năng đăng nhập "
        "(mục tiêu, trong/ngoài phạm vi, tiêu chí nghiệm thu), rồi nhờ người khác "
        "soát chéo trước khi gửi anh."
    ))
    route = out["route"]
    assert (route.get("mode"), route.get("shape")) == ("team", "do_review"), route
    assert route.get("signals", {}).get("needs_independent_review") == 1, route

    task_id = out["task_id"]
    steps = _steps(run, task_id)
    assert len(steps) <= 3, f"làm + soát là kế hoạch NHỎ: {list(steps)}"
    assert any(s.needs_review for s in steps.values()), (
        f"bước cuối phải được cắm cờ soát: {[(k, s.needs_review) for k, s in steps.items()]}"
    )

    review = None
    # Bounded, not "until settled": the claim is about WHO reviews, so the case stops
    # the moment the reviewer row exists rather than paying for the review itself.
    # Twelve ticks covers dispatch + one work round + the mint on a slow model.
    for _ in range(12):
        run.h.pump(ticks=1)
        rows = {r["step_id"]: r for r in run.h.step_rows(task_id)}
        review = next((r for r in rows.values() if r["step_type"] == "review"), None)
        if review is not None:
            break
    assert review is not None, f"chưa có hàng soát sau 12 tick: {run.h.step_rows(task_id)}"
    parent = _steps(run, task_id)[review["step_id"]].parent_step_id
    author = run.h.step_rows(task_id)
    author = next(r["assigned_to"] for r in author if r["step_id"] == parent)
    assert review["assigned_to"] and review["assigned_to"] != author, (
        f"người soát phải khác tác giả: soát={review['assigned_to']!r} tác giả={author!r}"
    )


def test_s3_a_brief_that_writes_outside_the_company_is_a_permission_chain(live_run):
    """"gửi email" is a sensitive tool: the safety refusal keeps the brief off the
    sprint, and the plan MUST carry the write boundary on a step even when the model
    forgot the flag — otherwise the review and the gateway approval the refusal exists
    for would never run. No pump: nothing may leave the company in a test."""
    run = live_run()
    out = _assign(run, (
        "Tổng hợp báo giá 3 gói dịch vụ của mình rồi gửi email cho khách hàng Anh Minh."
    ))
    route = out["route"]
    assert (route.get("mode"), route.get("source")) == ("team", "refusal"), route
    assert route.get("shape") == "permission_chain", route
    assert route.get("signals", {}).get("sensitive_tool") == 1, route

    steps = _steps(run, out["task_id"])
    assert any(s.external_write for s in steps.values()), (
        f"phải có bước mang cờ ghi-ra-ngoài: {[(k, s.external_write) for k, s in steps.items()]}"
    )
    assert all(s.status not in {"running", "done"} for s in steps.values()), steps


def test_s4_a_plain_lookup_is_a_sprint_that_still_records_the_shape_signals(live_run):
    """The three new brief signals ride on EVERY route row, sprint included — that is
    what lets route_stats ask "how often did a brief with a sensitive tool or a review
    ask still end up on the fast lane". A sprint carries no shape."""
    run = live_run()
    out = _assign(run, "Giá vé máy bay khứ hồi Sài Gòn – Hà Nội tuần này khoảng bao nhiêu?")
    route = out["route"]
    assert route.get("mode") == "sprint", route
    assert "shape" not in route, route
    signals = route.get("signals", {})
    assert {"independent_sources", "needs_independent_review", "sensitive_tool"} <= set(
        signals
    ), signals
    assert signals["needs_independent_review"] == 0 and signals["sensitive_tool"] == 0, (
        signals
    )
