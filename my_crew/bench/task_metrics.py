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

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

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


def _step_transcript_usage(data_dir: Path, task_id: str, step_id: str) -> dict:
    """Summed LLM usage over ALL of a step's attempt transcripts (a retried step has
    one file per attempt; the store's `cost_usd` is likewise cumulative). Empty dict
    when no transcript parses — best-effort, never raises into the metric load."""
    from my_crew.runtime.step_recorder import transcripts_dir
    from my_crew.runtime.transcript_evidence import summarize_transcript_usage

    totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    try:
        files = sorted(transcripts_dir(data_dir, task_id).glob(f"{step_id}-*.jsonl"))
    except (ValueError, OSError):
        return {}
    found = False
    for path in files:
        usage = summarize_transcript_usage(path)
        if usage is None:
            continue
        found = True
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    return totals if found else {}


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
