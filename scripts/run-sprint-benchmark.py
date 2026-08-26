#!/usr/bin/env python3
"""Print the sprint benchmark tables, from live tasks or from the offline briefs.

Five modes, because the five things worth measuring fail differently:

    # what the ROUTER decides — offline, 0 model calls, runs without a key
    .venv/bin/python scripts/run-sprint-benchmark.py routing --out cand-route.json
    .venv/bin/python scripts/run-sprint-benchmark.py routing --compare base.json cand.json

    # what the code decides to spend — offline, deterministic, no daemon needed
    .venv/bin/python scripts/run-sprint-benchmark.py pipeline

    # what the code manages to DELIVER for that spend, JSON-comparable across revisions
    .venv/bin/python scripts/run-sprint-benchmark.py release --out candidate.json
    .venv/bin/python scripts/run-sprint-benchmark.py release --compare base.json cand.json

    # what a real pair of runs actually cost — reads the live store
    .venv/bin/python scripts/run-sprint-benchmark.py tasks --baseline <id> --candidate <id>

    # which revision DELIVERS better, judged blind by a model of a different family
    .venv/bin/python scripts/run-sprint-benchmark.py judge \
        --baseline-dir base-out/ --candidate-dir cand-out/

`routing` and `release` are how two code revisions are compared: run each once per
revision (a git worktree at the release tag works), save each JSON, then `--compare` the
two. `routing` is the one that runs ANYWHERE — no key, no network, no store — so it is
the cheapest first look when a threshold changed.

The `tasks` mode never starts work. It only reads rows the runtime already wrote, so
running it is safe at any time and its numbers are the same ones the CEO experienced.
`judge` is the only mode that spends money, and it spends it on reading, not running.

Full release procedure: `docs/releasing.md`.
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


def _print_delta(rows: list[dict]) -> int:
    """The one delta table both comparable modes print.

    Shared rather than copied because the two modes are read side by side during a
    release: a column that drifts between them costs the reader a second look every
    time, for no reason at all.
    """
    if not rows:
        print("no differences across compared axes")
        return 0
    print(f"{'case':<24} {'axis':<18} {'baseline':>26} {'candidate':>26}")
    print("-" * 98)
    for row in rows:
        print(
            f"{row['case']:<24} {row['field']:<18} "
            f"{row['baseline']!s:>26} {row['candidate']!s:>26}"
        )
    return 0


def _load_pair(compare: list[str]) -> tuple[dict, dict]:
    base_path, cand_path = (Path(p) for p in compare)
    return json.loads(base_path.read_text()), json.loads(cand_path.read_text())


def _routing(args: argparse.Namespace) -> int:
    """What the router decides for every standing brief — or the delta between two runs.

    Offline and model-free, so this is the only comparable mode that runs unchanged in a
    worktree of an old tag with no key configured.
    """
    from my_crew.bench.brief_suite import ALL_CASES, ROUTING_CASES
    from my_crew.bench.routing_bench import compare_routing, run_suite

    if args.compare:
        return _print_delta(compare_routing(*_load_pair(args.compare)))

    # Both groups: the routing group covers every branch, the spend group is what the
    # rest of the benchmark measures — a threshold change that silently moves THOSE onto
    # the other lane is exactly the regression worth seeing here.
    report = run_suite(ROUTING_CASES + ALL_CASES, repeats=3)
    report["revision"] = _git_revision()
    print(f"{'case':<24} {'mode':<8} {'source':<10} {'reason':<44} signals")
    print("-" * 118)
    for name, d in report["cases"].items():
        sig = " ".join(f"{k}={v}" for k, v in d["signals"].items())
        print(f"{name:<24} {d['mode']:<8} {d['source']:<10} {d['reason'][:44]:<44} {sig}")
    print(f"\nrevision: {report['revision'] or 'unknown'} (stable over 3 repeats)")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"written: {args.out}")
    return 0


def _release(args: argparse.Namespace) -> int:
    """Deliverable-vs-spend table for this revision, or the delta between two JSONs."""
    from my_crew.bench.release_bench import COMPARED_FIELDS, compare_reports, run_suite

    if args.compare:
        return _print_delta(compare_reports(*_load_pair(args.compare)))

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


def _lane_table(db: Path, limit: int) -> int:
    """Fleet-wide per-lane view: what each lane costs and how work ARRIVES on it.

    The pairwise table below answers "was this run better than that run". This answers
    the question a release asks instead — across everything the fleet ran, is the router
    sending work to the lane that serves it best, and how often does it guess wrong.
    """
    from my_crew.bench.task_metrics import load_lane_stats

    report = load_lane_stats(db, limit=limit)
    if not report["total_tasks"]:
        print(f"no tasks in {db}")
        return 0

    print(
        f"{'lane':<10} {'tasks':>6} {'delivered':>10} {'cost $':>9} {'$/task':>8} "
        f"{'median':>8}  sources"
    )
    print("-" * 96)
    for lane in report["lanes"].values():
        sources = ", ".join(f"{k}×{v}" for k, v in lane.sources.items())
        median = f"{lane.median_seconds:.0f}s" if lane.median_seconds else "n/a"
        rate = f"{lane.delivery_rate:.0%}" if lane.delivery_rate is not None else "n/a"
        print(
            f"{lane.lane:<10} {lane.tasks:>6} {rate:>10} {lane.cost_usd:>9.4f} "
            f"{lane.cost_per_task or 0:>8.4f} {median:>8}  {sources}"
        )
    for lane in report["lanes"].values():
        if lane.efforts:
            detail = ", ".join(f"{k}×{v}" for k, v in lane.efforts.items())
            print(f"{lane.lane} effort: {detail}")

    rates = report["rates"]
    print(
        # Mẫu số phải là `routed_tasks`, không phải `total_tasks`: tỉ lệ được TÍNH trên
        # số task có bản ghi định tuyến, nên in kèm tổng số sẽ khiến người đọc chia lại
        # bằng con số sai — đúng thứ mẫu số pha loãng vừa được sửa để tránh.
        f"\nrouter misses over {report['routed_tasks']} routed tasks "
        f"({report['total_tasks']} total) — "
        f"dead end: {rates['dead_end'] if rates['dead_end'] is not None else 'n/a'}  ·  "
        f"downgrade: {rates['downgrade'] if rates['downgrade'] is not None else 'n/a'}  ·  "
        f"upgrade: {rates['upgrade'] if rates['upgrade'] is not None else 'n/a'}"
    )
    return 0


def _tasks(args: argparse.Namespace) -> int:
    """Compare two finished tasks straight out of the store, or aggregate every lane."""
    from my_crew.bench.task_metrics import compare, load_task_metric

    db = Path(args.db)
    if not db.exists():
        print(f"store not found: {db}", file=sys.stderr)
        return 2

    # No pair named ⇒ the fleet-wide view. Both ids or neither: one id alone has nothing
    # to be compared against, and silently showing the aggregate instead would answer a
    # question the caller did not ask.
    if not args.baseline and not args.candidate:
        return _lane_table(db, args.limit)
    if not (args.baseline and args.candidate):
        print("tasks: pass BOTH --baseline and --candidate, or neither", file=sys.stderr)
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


def _judge(args: argparse.Namespace) -> int:
    """Blind A/B on two directories of deliverables. The only mode that spends money.

    Needs a key: unlike every other mode this one calls a model. It fails loudly rather
    than degrading, because a judging run that silently produced no verdict looks exactly
    like a tie and would be read as "no quality change".
    """
    from my_crew.bench.quality_judge import run_judging
    from my_crew.config.config_builders import build_settings_from_env
    from my_crew.llm.client import LlmClient

    settings = build_settings_from_env()
    if not getattr(settings, "openrouter_api_key", ""):
        print("judge mode needs OPENROUTER_API_KEY", file=sys.stderr)
        return 2

    report = run_judging(
        LlmClient(settings), Path(args.baseline_dir), Path(args.candidate_dir),
        votes=args.votes, model=args.model,
    )
    report["revision"] = _git_revision()

    print(f"{'case':<24} {'winner':<10} votes")
    print("-" * 70)
    for case in report["cases"]:
        print(f"{case['case']:<24} {case['winner']:<10} {', '.join(case['votes'])}")
    tally = report["tally"]
    print(
        f"\nbaseline {tally['baseline']}  ·  candidate {tally['candidate']}  ·  "
        f"hoà {tally['hoa']}    (judge: {report['judge_model']}, "
        f"{report['votes_per_case']} phiếu/case)"
    )
    if report["skipped"]:
        print(f"bỏ qua (chỉ có ở một bên): {', '.join(report['skipped'])}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"written: {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pipeline", help="offline: what the code decides to spend")

    routing = sub.add_parser(
        "routing", help="offline, 0 model calls: what the router decides per brief"
    )
    routing.add_argument("--out", help="write the report JSON here as well as printing it")
    routing.add_argument(
        "--compare", nargs=2, metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="print the per-axis delta between two saved reports instead of running",
    )

    release = sub.add_parser(
        "release", help="offline: what the code delivers, JSON-comparable across revisions"
    )
    release.add_argument("--out", help="write the report JSON here as well as printing it")
    release.add_argument(
        "--compare", nargs=2, metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="print the per-axis delta between two saved reports instead of running",
    )

    live = sub.add_parser(
        "tasks", help="live store: what two real runs cost, or per-lane fleet stats"
    )
    live.add_argument("--baseline", default=None, help="task id of the slower/reference run")
    live.add_argument("--candidate", default=None, help="task id of the run being judged")
    live.add_argument(
        "--limit", type=int, default=500,
        help="tasks to aggregate when no pair is given (default 500, newest first)",
    )
    live.add_argument("--db", default=str(DEFAULT_DB), help=f"store path (default {DEFAULT_DB})")
    live.add_argument(
        "--data-dir", default=None,
        help="data root holding transcripts/ and agents/ jails (default: the db's folder)",
    )

    judge = sub.add_parser(
        "judge", help="live model: blind A/B on two directories of deliverables"
    )
    judge.add_argument("--baseline-dir", required=True,
                       help="deliverables from the reference revision")
    judge.add_argument("--candidate-dir", required=True,
                       help="deliverables from the revision being judged")
    judge.add_argument("--out", help="write the verdict JSON here as well as printing it")
    judge.add_argument(
        "--votes", type=int, default=3,
        help="independent votes per case (default 3; order is shuffled per vote)",
    )
    judge.add_argument(
        "--model", default=None,
        help="judge model (default: a different family from the one that ran the tasks)",
    )

    args = parser.parse_args()
    # Explicit table rather than an if-chain ending in a bare `return _tasks(args)`:
    # that fallthrough meant any future subcommand added to the parser but forgotten
    # here would silently run the tasks mode against the wrong arguments.
    handlers = {
        "pipeline": _pipeline, "routing": _routing, "release": _release,
        "tasks": _tasks, "judge": _judge,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
