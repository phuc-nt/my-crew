#!/usr/bin/env python3
"""Print the v77 benchmark table, either from live tasks or from the offline briefs.

Two modes, because the two things worth measuring fail differently:

    # what the code decides to spend — offline, deterministic, no daemon needed
    .venv/bin/python scripts/run-sprint-benchmark.py pipeline

    # what a real pair of runs actually cost — reads the live store
    .venv/bin/python scripts/run-sprint-benchmark.py tasks --baseline <id> --candidate <id>

The `tasks` mode never starts work. It only reads rows the runtime already wrote, so
running it is safe at any time and its numbers are the same ones the CEO experienced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DEFAULT_DB = REPO / ".data" / "team_tasks.sqlite3"


def _pipeline(_args: argparse.Namespace) -> int:
    """Run every standing brief through the pipeline with a scripted model."""
    import pytest

    from my_crew.bench.brief_suite import ALL_CASES
    from my_crew.bench.pipeline_bench import planned_queries, run_case
    from my_crew.runtime.sprint_runner import resolve_entities

    print(f"{'brief':<24} {'entities':>8} {'searches':>9} {'llm':>4}  {'verdict'}")
    print("-" * 62)
    failures = 0
    for case in ALL_CASES:
        entities = resolve_entities(case.goal, case.acceptance) or ["tổng quan"]
        draft = "| Mục | Thông tin | Nguồn |\n" + "\n".join(
            f"| {e} | dữ liệu | https://example.com/{i} |" for i, e in enumerate(entities)
        )
        with pytest.MonkeyPatch.context() as mp:
            result = run_case(case, draft=draft, monkeypatch=mp)
        problems = result.violations(case)
        failures += bool(problems)
        verdict = "OK" if not problems else "; ".join(problems)
        print(
            f"{case.name:<24} {len(result.entities):>8} {result.searches:>9} "
            f"{result.llm_calls:>4}  {verdict}"
        )

    print("\nplanned queries per brief:")
    for case in ALL_CASES:
        for q in planned_queries(case):
            print(f"  {case.name}: {q}")
    return 1 if failures else 0


def _tasks(args: argparse.Namespace) -> int:
    """Compare two finished tasks straight out of the store."""
    from my_crew.bench.task_metrics import compare, load_task_metric

    db = Path(args.db)
    if not db.exists():
        print(f"store not found: {db}", file=sys.stderr)
        return 2

    rows = []
    for label, task_id in (("baseline", args.baseline), ("candidate", args.candidate)):
        metric = load_task_metric(db, task_id)
        if metric is None:
            print(f"{label} task {task_id} not in {db}", file=sys.stderr)
            return 2
        rows.append((label, metric))

    print(f"{'':<11} {'task':<14} {'mode':<7} {'wall':>8} {'cost $':>9} {'steps':>6} {'rework':>7}")
    for label, m in rows:
        print(
            f"{label:<11} {m.task_id:<14} {m.mode:<7} {m.wall_clock_text:>8} "
            f"{m.cost_usd:>9.4f} {m.step_count:>6} {m.rework_steps:>7}"
        )

    ratios = compare(rows[0][1], rows[1][1])
    speed = ratios["speedup"]
    cost = ratios["cost_ratio"]
    print(
        f"\nspeedup: {speed if speed else 'n/a'}×    "
        f"cost ratio: {cost if cost else 'n/a'}×"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pipeline", help="offline: what the code decides to spend")

    live = sub.add_parser("tasks", help="live store: what two real runs cost")
    live.add_argument("--baseline", required=True, help="task id of the slower/reference run")
    live.add_argument("--candidate", required=True, help="task id of the run being judged")
    live.add_argument("--db", default=str(DEFAULT_DB), help=f"store path (default {DEFAULT_DB})")

    args = parser.parse_args()
    return _pipeline(args) if args.cmd == "pipeline" else _tasks(args)


if __name__ == "__main__":
    raise SystemExit(main())
