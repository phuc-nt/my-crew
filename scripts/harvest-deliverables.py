#!/usr/bin/env python3
"""Collect one deliverable file per task, for `run-sprint-benchmark.py judge`.

Judge mode compares two DIRECTORIES of deliverables, matching cases by filename stem.
Producing those directories is what this script does: given a data root and a mapping
from case name to task id, it writes `<case>.md` holding that task's final answer.

**Which artifact is the answer.** A finished task's directory holds one artifact per
step plus one per review round, and the previous benchmark round picked between them
with a heuristic — longest file, latest mtime, that sort of thing. It picked wrong, and
a quality comparison fed the wrong text is worse than no comparison, because it still
prints a winner. So this reads `final_deliverable` off the step row instead: the flag
the plan itself set on its one terminal step at confirm time.

**Unmarked is reported, never guessed.** A task planned before the column existed, or
one whose DAG had several terminals, has no marked step. Those are listed as skipped and
no file is written — `load_deliverables` only compares cases present on BOTH sides, so a
skipped case drops out of the judging honestly instead of scoring a phantom.

    .venv/bin/python scripts/harvest-deliverables.py \
        --data-root .data --out /tmp/deliverables-candidate \
        --case streaming_services=6c45ef2318a9 --case note_taking=37ae87a32fd4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _deliverable_text(payload: dict) -> str:
    """The prose of a step artifact.

    Prefers `result_text`, which the graph's `deliver` node writes, but falls back to
    concatenating every string value: the same artifact is written by several call sites
    with different payload shapes (the worker's fallback and the stall path spell it
    differently), and a harvest that reads one field name goes silently empty on the
    others. Empty output would look like a terse answer rather than a failed read.
    """
    text = payload.get("result_text")
    if isinstance(text, str) and text.strip():
        return text

    def strings(node: object) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [s for v in node.values() for s in strings(v)]
        if isinstance(node, list):
            return [s for v in node for s in strings(v)]
        return []

    return "\n".join(s for s in strings(payload) if s.strip())


def _terminal_steps(steps: list) -> list:
    """The steps nothing depends on, derived from `deps` alone.

    Exists for the baseline side of an A/B. `final_deliverable` is stored at confirm time,
    so a task planned by a revision that predates the column carries no flag and every
    case would skip — leaving nothing to judge, which is not the same as a fair comparison.

    This is NOT a heuristic and not the thing the flag replaced: it is the same rule the
    product applies (`task_decomposition.find_terminals` — "a step no other step depends
    on"), recomputed from the `deps` the store already holds. The heuristic that picked
    wrong before guessed by file size and mtime; this reads the DAG. Where both are
    available they agree by construction, which `--derive-terminal` is checked against
    before being trusted on the side that has no flag.
    """
    depended_on = {dep for s in steps for dep in (s.deps or ())}
    return [s for s in steps if s.step_id not in depended_on]


def harvest_one(data_root: Path, task_id: str, *,
                derive_terminal: bool = False) -> tuple[str | None, str]:
    """`(text, note)` for one task. `text` is None when nothing can be harvested."""
    from my_crew.agent.team_task_artifact import step_artifact_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(data_root / "team_tasks.sqlite3")
    task = store.get(task_id)
    if task is None:
        return None, "no such task in the store"

    marked = [s for s in task.steps if getattr(s, "final_deliverable", False)]
    how = "flag"
    if not marked and derive_terminal:
        marked = _terminal_steps(task.steps)
        how = "derived"
        if len(marked) > 1:
            # Same refusal the flag makes: several terminals means the DAG does not name
            # one answer, and picking among them is the guess this script exists to avoid.
            return None, (
                f"{len(marked)} terminal steps ({[s.step_id for s in marked]!r}) — the DAG "
                "names no single answer, so there is nothing to harvest without guessing"
            )
    if not marked:
        return None, (
            f"no step carries `final_deliverable` among {len(task.steps)} steps — either "
            "the plan predates the flag, or its DAG had several terminals and the plan "
            "declined to guess which one is the answer"
        )
    if len(marked) > 1:
        # Cannot happen through `replace_steps`, which marks at most one. Reported rather
        # than resolved: if it ever does happen the store is telling us something.
        return None, f"{len(marked)} steps carry the flag: {[s.step_id for s in marked]!r}"

    step = marked[0]
    path = step_artifact_path(data_root, task_id, step.seq)
    if not path.exists():
        return None, f"step {step.step_id!r} is marked but wrote no artifact at {path.name}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name} unreadable: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, f"{path.name} is not a JSON object"

    text = _deliverable_text(payload)
    if not text.strip():
        return None, f"step {step.step_id!r} artifact carries no prose"
    return text, f"step {step.step_id!r} (seq {step.seq}, {len(text)} chars, via {how})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="the SHARED data root holding team_tasks.sqlite3 + artifacts/")
    parser.add_argument("--out", type=Path, required=True,
                        help="directory to write <case>.md into (created if absent)")
    parser.add_argument("--case", action="append", default=[], metavar="NAME=TASK_ID",
                        help="repeatable: the case name to file this task's answer under")
    parser.add_argument(
        "--derive-terminal", action="store_true",
        help="when a task carries no `final_deliverable` flag, fall back to the step "
             "nothing depends on (same rule the flag stores). For the BASELINE side of an "
             "A/B, whose revision predates the column; still refuses a multi-terminal DAG.",
    )
    args = parser.parse_args()

    pairs: list[tuple[str, str]] = []
    for item in args.case:
        name, sep, task_id = item.partition("=")
        if not sep or not name.strip() or not task_id.strip():
            print(f"--case must be NAME=TASK_ID, got {item!r}", file=sys.stderr)
            return 2
        pairs.append((name.strip(), task_id.strip()))
    if not pairs:
        print("nothing to harvest: pass at least one --case NAME=TASK_ID", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []
    for name, task_id in pairs:
        text, note = harvest_one(args.data_root, task_id,
                                 derive_terminal=args.derive_terminal)
        if text is None:
            skipped.append(f"{name} ({task_id}): {note}")
            print(f"skip  {name:<24} {note}")
            continue
        (args.out / f"{name}.md").write_text(text, encoding="utf-8")
        written += 1
        print(f"write {name:<24} {note}")

    print(f"\n{written} written to {args.out}, {len(skipped)} skipped")
    if skipped:
        # Loud, because a silently thin directory is how a judging run ends up comparing
        # two cases and calling it a verdict.
        print("skipped cases will NOT be judged (a case must exist on both sides):")
        for line in skipped:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
