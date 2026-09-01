# Release evidence — 0.16.0

2026-09-01 · tag `v0.16.0`

What was measured before cutting 0.16.0, and — just as important — what was *not*. The
working notes live in `plans/260901-0721-release-readiness-gates/` and
`plans/260831-1841-openhuman-borrow-budget-output-guards/reports/`, both gitignored; this
file is the part that has to survive in the repo.

## Gate results

| Gate | Result |
|---|---|
| BE pytest | 4404 passed / 70 skipped |
| FE vitest | 417 passed / 59 files |
| ruff | clean |
| tsc | exit 0 |
| cold-start smoke `--browser` | 6/6 — wheel `my_crew-0.16.0-py3-none-any.whl`, `/health` 200, Playwright 2/2 |

## Guards verified against a live fleet

Both output guards had only ever been asserted offline. The prior round could not reach
their measuring conditions at all, which is the exact shape of risk that produced the
`397fecb` bug — offline green, live broken.

| Case | Result | Numbers |
|---|---|---|
| L2 — dep cap 8000 chars | green, 2 samples, no skip | $0.006516 / 502.1s · $0.012265 / 1029.5s |
| L4 — stash tool result >12k | green, 2 runs | $0.0062 each |

`TOOL_RESULT_STASH_CHARS` stayed at 12,000 and no assertion was loosened; the oversized
input comes from a fixture instead of asking the model to write something long. L2 took
seven rounds to go green, each round fixing a distinct real cause — including one product
bug (`8d58e52`, empty handoff from a wrong data root) and one bug in the measurement
itself (comparing two quantities of different units).

## Journey baseline

`bench/journey_baseline_0.16.0.json`, cut from a live run: 9 passed / 0 failed.

| Journey | Cost | Wall | Calls | Terminal |
|---|---|---|---|---|
| j1b stale plan hash | $0.000217 | 33.6s | 0 | open |
| j2 escalation | $0.0 | 33.4s | 1 | parked:open |
| j5 hard kill | $0.001304 | 101.1s | 2 | done |
| j1 outside caller | $0.000752 | 192.6s | 1 | done |

Two numbers need reading with care, and are recorded rather than smoothed over:

- **j1 ends `done` where 0.15.0 recorded `parked:open`**, and gained a review lane. The
  journey test deliberately does not pin terminal state — how the crew chooses to do the
  work is a model choice — so this is variance the suite tolerates by design.
- **j2 records zero cost against one model call.** `total_cost_usd` comes from the step
  ledger the cost cap enforces against; an escalation is a one-step vehicle whose call
  lands in the capture trail instead. Pre-existing accounting, reproduced across both
  cuts, unchanged by this release.

## Not measured: deliverable quality

The product half landed. Deliverables are now self-marked by a `final_deliverable` flag
derived from DAG shape, replacing a heuristic that used to pick the reviewer's critique
as the deliverable. Harvest accepts a flag only when exactly one row carries it, and
refuses rather than guessing when several do. On live data, 4/4 candidate cases harvested
via the flag.

The measurement half did not. Only 2 of 4 cases produced scorable output — the minimum is
3 — and blind judging at n=2 tied 1-1 with a length confound. The cause is environmental:
OpenAlex returns **HTTP 429** after roughly 14 briefs from one IP, confirmed directly with
`curl`, not a regression in 0.16.0.

**This axis is recorded as insufficient sample, not as "no degradation."** Two cases at a
tie does not support the stronger claim. Nothing measured suggests quality got worse;
there is simply not enough of it yet.

Closing this axis needs a different IP or a slower OpenAlex cadence. Note also that it
scores academic-lookup briefs while the other axes score the bench suite's commercial
ones, so the two do not sit side by side.

## Scope of the cost-cap claim

`cost_cap_usd` is **opt-in**: it defaults to `None` on all three tiers and only
`thin_tool_loop` enforces it. The hard ceiling remains the task-level
`company.team_task_cap_usd`. The default-on guards this release are the 12k tool-result
stash and the 8000-char dep cap.
