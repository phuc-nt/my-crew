# Release evidence — 0.17.0

2026-09-03 · tag `v0.17.0`

What was measured before cutting 0.17.0, and what was *not*. Working notes live in the
gitignored `plans/2609*` directories; this file is the part that has to survive in the repo.
The previous cut's evidence is [release-evidence-0.16.0.md](release-evidence-0.16.0.md).

## Gate results

| Gate | Result |
|---|---|
| BE pytest | 4660 passed / 1 skipped (live deselected) |
| FE vitest | 417 passed / 59 files |
| ruff | clean |
| tsc | exit 0 |
| cold-start smoke `--browser` | 6/6 — wheel `my_crew-0.17.0-py3-none-any.whl`, `/health` 200, Playwright 2/2 |
| routing bench vs `v0.16.0` worktree | 0 route deltas; the only rows are `signals` dicts gaining three keys (`independent_sources`, `needs_independent_review`, `sensitive_tool`) |
| release bench vs `v0.16.0` worktree | no differences across compared axes |

## Live fullflow against a real fleet

66 cases in `tests/fullflow_live/` plus the two standalone live files (`create_agent`
recursion, ops-intent delegation), fleet on `anthropic/claude-haiku-4.5`, run sequentially.

| Run | Result |
|---|---|
| First pass, 66 cases | 63 passed / 3 failed |
| Rerun of the 3 (L2 plan without dep, A3/A4 provider stream error, A8 planner dropped `needs_web`) | 4/4 passed |
| Standalone live (recursion + ops-intent) | 8/8 passed |
| S2 (do + review shape) on a second pass | **failed** — planner merged three jobs into one step, the worker gave up, the coordinator wrote the step itself and the self-do path cleared the review flag, so the task closed "after cross-check" with no reviewer |
| S2 after the fix (`keeps_planned_review`, shared by self-do and judge-accept) | 1/1 passed |

The three first-pass reds reproduced as model/provider variance, not product defects. The
S2 red was a real bug and is the last `Fixed` entry of this release; a unit test pins it.

## Grader calibration (H4)

Both graders were measured on Haiku against 12 correct artifacts and 12 with a planted
error (Wilson interval on each side). Self-check and peer review each produced 3/12
false fails and caught 10/12 planted errors — kept, exactly on the 0.25 / 0.50 lines. All
six false fails trace to one ambiguous rubric line (a deposit folded into a 24-month
total); the deterministic gate that read "đúng 90 triệu" as "90 items" is fixed in this
release.

## Journey baseline

`bench/journey_baseline_0.17.0.json`, cut from a live run after the version bump
(`my-crew --version` → 0.17.0), compared with the 0.16.0 baseline through
`scripts/run-sprint-benchmark.py journey --compare`.

9 passed / 0 failed, 159s wall for the whole selection.

| Journey | Cost | Wall | Calls | Terminal | Lanes |
|---|---|---|---|---|---|
| j1b stale plan hash | $0.002252 | 2.8s | 0 | open | sprint |
| j2 escalation | $0.0 | 12.2s | 1 | parked:open | work |
| j5 hard kill | $0.011739 | 35.5s | 1 | parked:open | sprint |
| j1 outside caller | $0.029002 | 66.6s | 4 | done | sprint + 2 review + rework |

Every journey stays an order of magnitude under the 0.30 USD per-journey ceiling. The
delta rows against 0.16.0 need reading with care, and are recorded rather than smoothed:

- **Costs are not on the same model.** The 0.16.0 baseline was cut by a harness that
  declared haiku but served the default fleet model (fixed in this release, see `Fixed`:
  "the live harness now serves the fleet on the model it declares"); this baseline
  actually ran on `anthropic/claude-haiku-4.5`. The 10–40× per-journey cost rise
  (j1 $0.0008 → $0.029, j5 $0.0013 → $0.012) is the model price, not more work per call.
  From 0.17.0 on, journey costs are comparable cut to cut.
- **j1 gained a rework lane** (1 → 4 calls): the reviewer failed the first draft once and
  the rework loop ran, then passed. The journey does not pin how the crew gets to
  settled; this is the review path doing its job.
- **j5 ends `parked:open` where 0.16.0 recorded `done`**, on fewer calls and a third of
  the wall. The test asserts that work survives the kill and the next fleet picks it up;
  it deliberately does not pin the terminal state, same as j1 in the 0.16.0 cut.
- **j2 still records zero cost against one call** — the pre-existing escalation
  accounting noted in 0.16.0, unchanged.

## Defaults that changed, and what that means for the numbers

- **`cost_cap_usd` is now on by default** for `create_agent` and `deep_agent` (1.0 USD per
  step, half the task-level default). 0.16.0 shipped it opt-in, so every tools-tier step in
  this cut ran under a ceiling the 0.16.0 baseline did not have. Native stays uncapped.
- **The OpenAlex academic-search tool is removed.** The 0.16.0 quality axis was scored on
  academic-lookup briefs and could not reach a sample because OpenAlex returned 429 by IP;
  that axis cannot be rerun on the same briefs.

## Not measured

- **Deliverable quality (blind judge)**: still not at n ≥ 3 per revision. The H4 grader
  calibration above is evidence about the graders, not about the deliverables. Recorded as
  insufficient sample, not as "no degradation".
- **Reliability (k = 5 replays)**: the baseline on file is still `reliability_baseline_0.15.0.json`;
  no new cut this release.
