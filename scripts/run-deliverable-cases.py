#!/usr/bin/env python3
"""Run the axis-5 judging briefs on ONE revision, then harvest their deliverables.

Axis 5 asks the only question the counting benchmarks cannot: do the budget and output
caps make the delivered WORK worse? Answering it needs real deliverables from both
revisions, produced the same way, then judged blind.

**Why these briefs and not `brief_suite`'s.** The bench suite's cases are commercial
lookups (streaming prices, e-commerce fees) that need a live web provider. The previous
round ran them on a fleet without one and 7 of 8 tasks ended in a refusal, so the judge
was scoring which revision declines more gracefully — a real verdict about nothing. These
briefs ask for the same SHAPE of work (compare N subjects on M criteria, cite sources)
against literature that OpenAlex can actually reach, and OpenAlex is keyless, so the run
arms identically on any machine.

**Why the fleet is on the tools tier.** `academic_search` rides with `agent_runtime:
create_agent` (see `topology._tools_tier_lines`), and that is also the tier the caps under
test actually live on — a native fleet would exercise neither. Deliberately NOT
`web_search: true`: with a provider key that makes the launcher prefetch a `needs_web`
step, and a non-empty bundle sends the step back to the native tier, silently undoing the
tier this run depends on.

    .venv/bin/python scripts/run-deliverable-cases.py --out /tmp/deliverables-candidate
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

#: Case name → brief. Names are the filenames the judge matches on, so the two revisions
#: MUST be run with the same mapping or `load_deliverables` pairs nothing.
#:
#: `team:` prefixed for the same reason the live dep-cap case is: without it a plan the
#: model happens to put on one assignee is downgraded to a single sprint step, and the two
#: revisions would then be judged on structurally different work depending on a coin flip.
CASES: dict[str, str] = {
    "eval_methods": (
        "team: So sánh hai phương pháp đánh giá chất lượng mô hình ngôn ngữ: "
        "đánh giá tự động bằng chỉ số và đánh giá bằng người chấm. "
        "Với mỗi phương pháp nêu: nguyên lý, điểm mạnh, điểm yếu đã được nghiên cứu "
        "chỉ ra. Nêu rõ nguồn tham khảo."
    ),
    "retrieval_augmentation": (
        "team: Tổng hợp về kỹ thuật truy hồi tăng cường (retrieval-augmented generation): "
        "nó giải quyết vấn đề gì của mô hình ngôn ngữ, các biến thể chính, "
        "và những hạn chế mà nghiên cứu đã ghi nhận. Nêu rõ nguồn tham khảo."
    ),
    "model_compression": (
        "team: So sánh ba hướng nén mô hình học sâu: lượng tử hoá (quantization), "
        "tỉa bớt (pruning) và chưng cất tri thức (knowledge distillation). "
        "Mỗi hướng nêu nguyên lý, mức đánh đổi giữa kích thước và chất lượng. "
        "Nêu rõ nguồn tham khảo."
    ),
    "prompt_robustness": (
        "team: Nghiên cứu cho biết gì về độ ổn định của mô hình ngôn ngữ trước cách "
        "diễn đạt câu lệnh khác nhau: hiện tượng được ghi nhận ra sao, nguyên nhân "
        "được đề xuất, và các cách giảm thiểu. Nêu rõ nguồn tham khảo."
    ),
}


def _run_one(server, brief: str, timeout_s: float) -> tuple[str | None, str]:
    """Delegate one brief and wait for it to settle. `(task_id, note)`."""
    from tests.fullflow_live.topology import wait_until_settled

    code, body = server.post(
        "/api/control-plane/delegate", {"brief": brief, "confirm": True}, timeout=900
    )
    if code != 200:
        return None, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    if not task_id:
        return None, f"delegate returned no task_id: {body!r}"
    try:
        status = wait_until_settled(server, task_id, timeout_s=timeout_s)
    except AssertionError as exc:
        # Reported, not raised: one brief that overruns must not discard the deliverables
        # the other three already produced and paid for.
        return task_id, f"did not settle: {exc}"
    state = (status.get("state") or {}).get("status")
    cost = (status.get("cost") or {}).get("total_cost_usd") or 0.0
    return task_id, f"settled state={state!r} cost=${cost:.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True,
                        help="directory to harvest <case>.md into")
    parser.add_argument("--home", type=Path, default=None,
                        help="fleet home to build (default: a temp dir beside --out)")
    parser.add_argument("--timeout-s", type=float, default=1500.0,
                        help="per-brief settle deadline; matches the live suite's long cases")
    parser.add_argument("--case", action="append", default=[],
                        help="repeatable: run only these case names (default: all)")
    args = parser.parse_args()

    import os

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("needs OPENROUTER_API_KEY — this mode runs real journeys", file=sys.stderr)
        return 2

    from tests.fullflow.cast import WORKERS
    from tests.fullflow_live.topology import boot, seed_home

    selected = {k: v for k, v in CASES.items() if not args.case or k in set(args.case)}
    if not selected:
        print(f"no case matched {args.case!r}; known: {sorted(CASES)}", file=sys.stderr)
        return 2

    home = args.home or (args.out.parent / f"{args.out.name}-home")
    home.mkdir(parents=True, exist_ok=True)
    # Every worker on the tools tier: that is where `academic_search` and the caps under
    # test both live. No `cost_cap_usd` — the shipped default is no ceiling, and this run
    # measures the DEFAULT posture rather than a configuration nobody has.
    seed_home(home, api_key=api_key, tools_tier={a for a, _ in WORKERS})
    server = boot(home, api_key=api_key, seed=False)

    results: dict[str, str] = {}
    try:
        for name, brief in selected.items():
            started = time.monotonic()
            task_id, note = _run_one(server, brief, args.timeout_s)
            print(f"{name:<24} {task_id or '-':<14} {note}  ({time.monotonic()-started:.0f}s)",
                  flush=True)
            if task_id:
                results[name] = task_id
    finally:
        server.stop()

    if not results:
        print("no task produced — nothing to harvest", file=sys.stderr)
        return 1

    harvest = [
        sys.executable, str(Path(__file__).with_name("harvest-deliverables.py")),
        "--data-root", str(home / ".data"), "--out", str(args.out),
    ]
    for name, task_id in results.items():
        harvest += ["--case", f"{name}={task_id}"]
    print("\n--- harvest ---", flush=True)
    return subprocess.call(harvest)


if __name__ == "__main__":
    raise SystemExit(main())
