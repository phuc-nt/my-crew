"""Read what a finished task actually cost, from the live store.

Every number here comes from rows the runtime wrote while doing the work. Nothing is
re-simulated, so a benchmark row can be traced back to a task id the CEO can open.

Wall-clock deserves a note. `team_tasks.created_at` is when the CEO's brief landed,
and the last step's `last_seen` is when the final step stopped working — so the span
between them includes the queue wait before the first worker spawned. That is
deliberate: the CEO waits through that gap too, and v77's claim is about how long the
answer takes to ARRIVE, not about how busy the workers were once they started.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

#: Steps that carry the work itself. `review` steps are counted separately because a
#: mode that produces work needing more review rounds is paying a real cost, and
#: folding both into one number would hide exactly that.
_CONTENT_STEP_TYPES = ("work", "sprint", "rework")


@dataclass(frozen=True)
class StepMetric:
    """One row of `team_steps`, reduced to what a benchmark compares.

    The `llm_calls`/`prompt_tokens`/`completion_tokens` fields (v80 P5) come from the
    step's transcript files, not the store — zero when no transcript exists (recorder
    off / pre-v80 task). The store's `cost_usd` stays the accounting source of truth;
    transcript usage only decomposes it. Deep-tier transcripts carry one AGGREGATE
    `llm_response` per loop, so `llm_calls` is per-attempt granularity there.
    """

    seq: int
    step_type: str
    status: str
    cost_usd: float
    seconds: float | None
    step_id: str = ""
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    tool_error_kinds: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TaskMetric:
    """Everything a benchmark row needs about one finished task."""

    task_id: str
    title: str
    status: str
    mode: str
    wall_clock_seconds: float | None
    cost_usd: float
    step_count: int
    content_steps: int
    review_steps: int
    rework_steps: int
    steps: list[StepMetric] = field(default_factory=list)

    @property
    def wall_clock_text(self) -> str:
        """`3m19s` — the form the reports and the plan already use."""
        if self.wall_clock_seconds is None:
            return "n/a"
        total = int(round(self.wall_clock_seconds))
        return f"{total // 60}m{total % 60:02d}s"

    @property
    def llm_calls(self) -> int:
        return sum(s.llm_calls for s in self.steps)

    @property
    def tool_calls(self) -> int:
        return sum(s.tool_calls for s in self.steps)

    @property
    def tool_errors(self) -> int:
        return sum(s.tool_errors for s in self.steps)

    @property
    def tool_error_kinds(self) -> dict:
        merged: dict[str, int] = {}
        for step in self.steps:
            for kind, count in step.tool_error_kinds.items():
                merged[kind] = merged.get(kind, 0) + count
        return merged


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _span(start: str | None, end: str | None) -> float | None:
    a, b = _parse(start), _parse(end)
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def _step_transcript_files(data_dir: Path, task_id: str, step_id: str) -> list[Path]:
    """A step's attempt transcripts, looked up like review evidence is: the shared
    root first, then every agent jail under `<data_dir>/agents/` — a spawned worker
    records into its OWN data dir, and the bench must not lose those steps."""
    from my_crew.runtime.step_recorder import transcripts_dir

    roots = [data_dir, *sorted((data_dir / "agents").glob("*/"))]
    files: list[Path] = []
    for root in roots:
        try:
            files.extend(sorted(transcripts_dir(root, task_id).glob(f"{step_id}-*.jsonl")))
        except (ValueError, OSError):
            continue
    return files


def _step_transcript_usage(data_dir: Path, task_id: str, step_id: str) -> dict:
    """Summed LLM usage + tool-call error counts over ALL of a step's attempt
    transcripts (a retried step has one file per attempt; the store's `cost_usd` is
    likewise cumulative). Empty dict when no transcript parses — best-effort, never
    raises into the metric load."""
    from my_crew.runtime.transcript_evidence import (
        summarize_tool_errors,
        summarize_transcript_usage,
    )

    totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "tool_calls": 0, "tool_errors": 0}
    kinds: dict[str, int] = {}
    found = False
    for path in _step_transcript_files(data_dir, task_id, step_id):
        usage = summarize_transcript_usage(path)
        if usage is not None:
            found = True
            for key in ("llm_calls", "prompt_tokens", "completion_tokens"):
                totals[key] += int(usage.get(key) or 0)
        errors = summarize_tool_errors(path)
        if errors is not None:
            found = True
            totals["tool_calls"] += int(errors.get("tool_calls") or 0)
            totals["tool_errors"] += int(errors.get("tool_errors") or 0)
            for kind, count in (errors.get("kinds") or {}).items():
                kinds[kind] = kinds.get(kind, 0) + int(count)
    if not found:
        return {}
    return totals | {"kinds": kinds}


def load_task_metric(
    db_path: Path | str, task_id: str, *, data_dir: Path | None = None
) -> TaskMetric | None:
    """Return measurements for `task_id`, or None when the task is not in this store.

    `data_dir` (v80 P5, optional): when given, each step also carries LLM usage
    decomposed from its attempt transcripts. Omitted ⇒ store-only metrics, exactly
    the pre-v80 behavior.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        task = conn.execute(
            "SELECT id, title, status, created_at, cost_usd_total FROM team_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            return None
        rows = conn.execute(
            "SELECT seq, step_id, step_type, status, cost_usd, spawned_at, last_seen "
            "FROM team_steps WHERE task_id = ? ORDER BY seq",
            (task_id,),
        ).fetchall()
    finally:
        conn.close()

    steps = []
    for r in rows:
        step_id = str(r["step_id"] or "")
        usage = (
            _step_transcript_usage(data_dir, task_id, step_id)
            if data_dir is not None and step_id
            else {}
        )
        steps.append(
            StepMetric(
                seq=int(r["seq"]),
                step_type=str(r["step_type"] or ""),
                status=str(r["status"] or ""),
                cost_usd=float(r["cost_usd"] or 0.0),
                seconds=_span(r["spawned_at"], r["last_seen"]),
                step_id=step_id,
                llm_calls=int(usage.get("llm_calls") or 0),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                tool_calls=int(usage.get("tool_calls") or 0),
                tool_errors=int(usage.get("tool_errors") or 0),
                tool_error_kinds=dict(usage.get("kinds") or {}),
            )
        )

    # The task ends at the LATEST `last_seen`, which is not the highest `seq`: a review
    # row is minted when its work row is dispatched, so on a fanned-out team task the
    # review carries a higher seq while finishing minutes before the work it reviews.
    # Reading the final row instead of the latest timestamp cut ~9 minutes off a real
    # 31-minute team run and understated its wall-clock by a third.
    finished_at = max(
        (r["last_seen"] for r in rows if r["last_seen"]),
        default=None,
    )

    return TaskMetric(
        task_id=str(task["id"]),
        title=str(task["title"] or ""),
        status=str(task["status"] or ""),
        mode="sprint" if any(s.step_type == "sprint" for s in steps) else "team",
        wall_clock_seconds=_span(task["created_at"], finished_at),
        cost_usd=float(task["cost_usd_total"] or 0.0),
        step_count=len(steps),
        content_steps=sum(1 for s in steps if s.step_type in _CONTENT_STEP_TYPES),
        review_steps=sum(1 for s in steps if s.step_type == "review"),
        rework_steps=sum(1 for s in steps if s.step_type == "rework"),
        steps=steps,
    )


def compare(baseline: TaskMetric, candidate: TaskMetric) -> dict[str, float | None]:
    """Speed-up and cost ratio of `candidate` against `baseline`.

    Returns ratios, not deltas: "3.6× faster" survives a change of model pricing or a
    slower search provider, where "saved 22 minutes" does not.
    """

    def _ratio(base: float | None, cand: float | None) -> float | None:
        if not base or not cand:
            return None
        return round(base / cand, 2)

    return {
        "speedup": _ratio(baseline.wall_clock_seconds, candidate.wall_clock_seconds),
        "cost_ratio": _ratio(baseline.cost_usd, candidate.cost_usd),
        "baseline_seconds": baseline.wall_clock_seconds,
        "candidate_seconds": candidate.wall_clock_seconds,
    }


# --- fleet-wide, per-lane -------------------------------------------------------------
#
# Everything above measures ONE task against ONE other task — the right shape for
# "did this change make this run faster". It is the wrong shape for the question a
# release actually asks: across everything the fleet ran, is the router sending work to
# the lane that serves it best, and how often does it guess wrong. That needs the route
# record, which the per-task reader above deliberately does not touch.


@dataclass(frozen=True)
class LaneStats:
    """What one lane cost the fleet over a window of tasks."""

    lane: str
    tasks: int
    delivered: int
    cost_usd: float
    median_seconds: float | None
    #: `route_json.source` counts — how each task ARRIVED on this lane.
    sources: dict[str, int]
    #: `route_json.effort` counts. Sprint-only in practice; empty on the team lane.
    efforts: dict[str, int]

    @property
    def delivery_rate(self) -> float | None:
        return round(self.delivered / self.tasks, 2) if self.tasks else None

    @property
    def cost_per_task(self) -> float | None:
        return round(self.cost_usd / self.tasks, 4) if self.tasks else None


def _median(values: list[float]) -> float | None:
    """Median, not mean: one 40-minute stall would drag a mean far enough to hide a
    real improvement in every other run."""
    ordered = sorted(v for v in values if v)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def load_lane_stats(db_path: Path | str, *, limit: int = 500) -> dict[str, Any]:
    """Per-lane aggregate over the most recent `limit` tasks in a store.

    Read-only and store-only: no transcripts, no model calls, so it is safe to point at
    a live store at any time. Tasks with no route record (anything created before v77)
    are counted under lane "unknown" rather than guessed at — a lane inferred from step
    shape would silently fold old team tasks into the new numbers.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, status, delivery_status, created_at, cost_usd_total, route_json "
            "FROM team_tasks ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        spans: dict[str, float | None] = {}
        for r in rows:
            last = conn.execute(
                "SELECT MAX(last_seen) AS f FROM team_steps WHERE task_id = ?",
                (r["id"],),
            ).fetchone()
            spans[str(r["id"])] = _span(r["created_at"], last["f"] if last else None)
    finally:
        conn.close()

    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            route = json.loads(r["route_json"]) if r["route_json"] else {}
        except (ValueError, TypeError):
            route = {}
        lane = str(route.get("mode") or "unknown")
        bucket = buckets.setdefault(lane, {
            "tasks": 0, "delivered": 0, "cost": 0.0, "spans": [],
            "sources": {}, "efforts": {},
        })
        bucket["tasks"] += 1
        if str(r["delivery_status"] or "") == "delivered":
            bucket["delivered"] += 1
        bucket["cost"] += float(r["cost_usd_total"] or 0.0)
        span = spans.get(str(r["id"]))
        if span:
            bucket["spans"].append(span)
        # `dead_end` is a separate boolean flag on the route (not a `source` value —
        # overwriting `source` with the literal "dead_end" destroyed the ORIGINAL
        # routing/escalation source a stalled task needed for attribution; see the
        # `_mark_route_dead_end` fix in `team_tick_collaborators.py`). Bucket it under
        # its own pseudo-source name here so `counted["dead_end"]` below still works
        # without resurrecting that overwrite.
        source = "dead_end" if route.get("dead_end") is True else str(
            route.get("source") or "unknown"
        )
        bucket["sources"][source] = bucket["sources"].get(source, 0) + 1
        effort = str(route.get("effort") or "")
        if effort:
            bucket["efforts"][effort] = bucket["efforts"].get(effort, 0) + 1

    lanes = {
        name: LaneStats(
            lane=name, tasks=b["tasks"], delivered=b["delivered"],
            cost_usd=round(b["cost"], 4), median_seconds=_median(b["spans"]),
            sources=dict(sorted(b["sources"].items())),
            efforts=dict(sorted(b["efforts"].items())),
        )
        for name, b in sorted(buckets.items())
    }

    # The three rates worth a release's attention, each naming a different mistake:
    # a dead end is the router picking sprint for work sprint could not finish; a
    # downgrade is the heuristic over-calling team and the safety net catching it; an
    # upgrade is a dead end that someone then paid a second time to redo as a team task.
    total = sum(la.tasks for la in lanes.values())
    counted: dict[str, int] = {}
    for la in lanes.values():
        for source, n in la.sources.items():
            counted[source] = counted.get(source, 0) + n

    # Mẫu số là số việc CÓ ĐỊNH TUYẾN, không phải mọi việc trong store. Việc từ trước
    # v77 không có `route_json` nên nằm ở lane `unknown`; router chưa từng quyết định gì
    # về chúng, tính vào mẫu số thì mọi tỷ lệ đều bị pha loãng theo bề dày lịch sử của
    # store chứ không theo chất lượng định tuyến. Một store có 1 dead-end trên 1 việc
    # định tuyến sẽ báo 0.5 chỉ vì cạnh đó còn một việc cũ.
    routed = total - lanes["unknown"].tasks if "unknown" in lanes else total
    return {
        "total_tasks": total,
        "routed_tasks": routed,
        "lanes": lanes,
        "rates": {
            key: (round(counted.get(key, 0) / routed, 3) if routed else None)
            for key in ("dead_end", "downgrade", "upgrade")
        },
    }
