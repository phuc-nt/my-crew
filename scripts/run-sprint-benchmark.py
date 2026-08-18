#!/usr/bin/env python3
"""Print the sprint benchmark tables, from live tasks or from the offline briefs.

Three modes, because the three things worth measuring fail differently:

    # what the code decides to spend — offline, deterministic, no daemon needed
    .venv/bin/python scripts/run-sprint-benchmark.py pipeline

    # what the code manages to DELIVER for that spend, JSON-comparable across revisions
    .venv/bin/python scripts/run-sprint-benchmark.py release --out candidate.json
    .venv/bin/python scripts/run-sprint-benchmark.py release --compare base.json cand.json

    # what a real pair of runs actually cost — reads the live store
    .venv/bin/python scripts/run-sprint-benchmark.py tasks --baseline <id> --candidate <id>

The `release` mode is how two code revisions are compared: run it once per revision
(a git worktree at the release tag works), save each JSON, then `--compare` the two.
The `tasks` mode never starts work. It only reads rows the runtime already wrote, so
running it is safe at any time and its numbers are the same ones the CEO experienced.
"""

from __future__ import annotations

import argparse
import json
import subprocess
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


def _git_revision() -> str:
    """Best-effort `<short-sha>[+dirty]` label for the report, "" when not a repo."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"{sha}+dirty" if dirty else sha
    except Exception:  # noqa: BLE001 — a label, never a reason to fail the bench
        return ""


def _release(args: argparse.Namespace) -> int:
    """Deliverable-vs-spend table for this revision, or the delta between two JSONs."""
    from my_crew.bench.release_bench import COMPARED_FIELDS, compare_reports, run_suite

    if args.compare:
        base_path, cand_path = (Path(p) for p in args.compare)
        rows = compare_reports(
            json.loads(base_path.read_text()), json.loads(cand_path.read_text())
        )
        if not rows:
            print("no differences across compared axes")
            return 0
        print(f"{'case':<16} {'axis':<18} {'baseline':>10} {'candidate':>10}")
        print("-" * 58)
        for row in rows:
            print(
                f"{row['case']:<16} {row['field']:<18} "
                f"{row['baseline']!s:>10} {row['candidate']!s:>10}"
            )
        return 0

    report = run_suite(repeats=3)
    report["revision"] = _git_revision()
    header = " ".join(f"{f:>16}" for f in COMPARED_FIELDS)
    print(f"{'case':<16}{header}")
    print("-" * (16 + 17 * len(COMPARED_FIELDS)))
    for name, metric in report["cases"].items():
        cells = " ".join(f"{metric[f]!s:>16}" for f in COMPARED_FIELDS)
        print(f"{name:<16}{cells}")
    print(f"\nrevision: {report['revision'] or 'unknown'} (stable over 3 repeats)")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"written: {args.out}")
    return 0


def _tasks(args: argparse.Namespace) -> int:
    """Compare two finished tasks straight out of the store."""
    from my_crew.bench.task_metrics import compare, load_task_metric

    db = Path(args.db)
    if not db.exists():
        print(f"store not found: {db}", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir) if args.data_dir else db.parent
    rows = []
    for label, task_id in (("baseline", args.baseline), ("candidate", args.candidate)):
        metric = load_task_metric(db, task_id, data_dir=data_dir)
        if metric is None:
            print(f"{label} task {task_id} not in {db}", file=sys.stderr)
            return 2
        rows.append((label, metric))

    print(
        f"{'':<11} {'task':<14} {'mode':<7} {'wall':>8} {'cost $':>9} {'steps':>6} "
        f"{'rework':>7} {'rounds':>7} {'tools':>6} {'t-err':>6}"
    )
    for label, m in rows:
        print(
            f"{label:<11} {m.task_id:<14} {m.mode:<7} {m.wall_clock_text:>8} "
            f"{m.cost_usd:>9.4f} {m.step_count:>6} {m.rework_steps:>7} "
            f"{m.llm_calls:>7} {m.tool_calls:>6} {m.tool_errors:>6}"
        )
    for label, m in rows:
        if m.tool_error_kinds:
            detail = ", ".join(f"{k}×{v}" for k, v in sorted(m.tool_error_kinds.items()))
            print(f"{label} tool errors: {detail}")

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

    release = sub.add_parser(
        "release", help="offline: what the code delivers, JSON-comparable across revisions"
    )
    release.add_argument("--out", help="write the report JSON here as well as printing it")
    release.add_argument(
        "--compare", nargs=2, metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="print the per-axis delta between two saved reports instead of running",
    )

    live = sub.add_parser("tasks", help="live store: what two real runs cost")
    live.add_argument("--baseline", required=True, help="task id of the slower/reference run")
    live.add_argument("--candidate", required=True, help="task id of the run being judged")
    live.add_argument("--db", default=str(DEFAULT_DB), help=f"store path (default {DEFAULT_DB})")
    live.add_argument(
        "--data-dir", default=None,
        help="data root holding transcripts/ and agents/ jails (default: the db's folder)",
    )

    args = parser.parse_args()
    if args.cmd == "pipeline":
        return _pipeline(args)
    if args.cmd == "release":
        return _release(args)
    return _tasks(args)


if __name__ == "__main__":
    raise SystemExit(main())
