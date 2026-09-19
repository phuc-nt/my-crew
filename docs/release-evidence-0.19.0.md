# Release evidence — 0.19.0

2026-09-19 · tag `v0.19.0`

What was measured before cutting 0.19.0, and what was *not*. The previous cut's evidence is
[release-evidence-0.18.0.md](release-evidence-0.18.0.md).

This round had no single release question the way 0.18.0 did ("which roles is the one fleet
model good at"). The work that landed was product work — staff templates that carry
role-appropriate skills, live coverage for each role's business patterns — so the release
question was the ordinary one: does anything regress, and are the baselines still true.

## Gate results

| Gate | Result |
|---|---|
| BE pytest | 4865 passed / 9 skipped / 80 deselected (live), at the release tree |
| FE vitest | 509 passed / 79 files |
| ruff | clean (whole repo) |
| tsc | exit 0 |
| Playwright mocked smoke | 65 passed (desktop + mobile projects) |
| cold-start smoke `--browser` | 6/6 steps on wheel `my_crew-0.19.0-py3-none-any.whl` (100 `_shipped/` files, 27 FE dist) + Playwright 2/2 |
| routing bench vs `v0.18.0` worktree | no differences across compared axes |
| release bench vs `v0.18.0` worktree | no differences across compared axes |
| CI on the release commit | success |

The nine skips are all environmental and were triaged individually: Firecrawl
(`localhost:3002`) unreachable ×3, Docker unavailable ×5, and one test that skips *by design*
when `deepagents` IS installed. Eight of them previously ran only because the venv lacked the
`deep` extra; installing it makes them skip as intended. Not a regression.

## Role scorecard (`scripts/run-sprint-benchmark.py roles`)

k=3, `~deepseek/deepseek-v4-flash-latest`, `provider_ignore` unset (a run with it set is not
comparable). New baseline: `bench/role_baseline_0.19.0.json`, revision `71706d7`.

| Role | 0.17.0 baseline | 0.19.0 | Verdict |
|---|---|---|---|
| content | 1.00 | 1.00 | good |
| review | 0.922 | **1.00** | good (H4 false-fail 0.00, catch 0.99, keep=True) |
| aggregate | 1.00 | 1.00 | good |
| plan | 0.972 | **1.00** | good |
| util | 0.944 | **1.00** | good |
| advisor | 1.00 | 1.00 | good |
| sprint_low | 1.00 | 1.00 | good |

Three roles improved and none regressed. The 0.17.0 baseline was two releases stale — 0.18.0
deliberately did not recut it, because that round's review drop was traced to a routing
episode rather than to code (see the previous evidence file). Routing has since settled: the
four review probes and the one plan probe that were red at 0.17.0 are 3/3 here.

### The advisor probe was measuring the wrong thing

The first 0.19.0 run scored `advisor` at 0.67 **weak**, on two `wrong` failures at one
upstream. That looked like the only regression in the round, so it was chased before the
baseline was cut rather than recorded as variance.

It was not a regression, and it was not variance either. `_parse_verdict` quarantines an
advisor note that drifts out of Vietnamese or runs past `MAX_NOTE_CHARS` — a guard added
after 0.17.0 on a measured 1/8 drift rate, because a corrupted instruction reaches a working
agent's context. The probe read every empty verdict as "silent on a 4x repeated 403 loop",
which scored the guard firing as an advisor defect.

Replaying the probe 8 times with the raw reply captured alongside the parsed verdict:

| Replays | Raw reply | Old score | Correct reading |
|---|---|---|---|
| 5 | a clean Vietnamese concern naming the 403 loop | ok | ok |
| 2 | a concern written in Croatian / Romanian | **wrong** | guard fired — the advisor *did* see the loop |
| 1 | a concern that ran 16,434 chars of one repeated character | **wrong** | guard fired — length cap |

All three empty verdicts were the guard working, on a reply that had correctly named the
loop. The probe now replays the raw reply through the same decoder and passes when the model
named a concern the guard then threw away; a reply that names no concern still fails, so the
guard cannot become a hiding place. The fenced-JSON decode was extracted out of
`_parse_verdict` so the bench and the sweep read a reply exactly the same way.

Three offline tests pin it (drift quarantined, overlong quarantined, genuine silence still
fails). On the recut run both paths appeared live: `sweep/repeated-403` scored 3/3 with one
replay quarantined at `Relace` and two clean concerns at `Morph` and `StreamLake`.

This is a measurement fix, not a behaviour change: `advisor_sweep` itself is untouched apart
from the extracted helper, and the 0.17.0 advisor score of 1.00 was recorded before the
guard existed.

## Journey baseline

9/9 live in 821 s → `bench/journey_baseline_0.19.0.json` (stamped `0.19.0`; the venv was
synced with `uv sync --extra deep` before the cut, so the label is the installed
distribution's, not `pyproject.toml`'s).

| Journey | 0.18.0 | 0.19.0 | Reading |
|---|---|---|---|
| j1 outside caller → settled | `parked:open`, 1 call, $0.000864 | **`done`**, 6 calls, $0.002995, lanes sprint→review(3)→rework(2) | The journey now runs the full loop instead of parking. Not a code change this round — the brief carries no company facts, so whether the self-check refuses invented copy or the rework satisfies it is a model choice. The test pins invariants, not the terminal state |
| j1b stale hash refused | `open`, 0 calls | `open`, 0 calls | unchanged |
| j2 escalation keeps its source | `parked:open`, 1 call | `parked:open`, 1 call | unchanged — escalations park by design |
| j5 hard kill → next fleet finishes | `parked:open`, 1 call, $0.000110 | **`done`**, 2 calls, $0.001195 | as j1: the resumed fleet carried the work to a terminal state this run |

Every journey stayed far under the 0.30 USD ceiling; the whole baseline cost under $0.005.
The two state improvements are recorded as observations, not as wins to defend: both are
model choices on briefs whose outcome legitimately varies, which is exactly why those tests
assert monotone status, cost and the audit chain rather than the terminal state.

## Live fullflow against the real fleet

The full suite was run during the template-skills round that preceded this cut: **66 passed /
6 failed in 3h03 over 72 cases**. All six reds were classified before anything was changed,
and none was a defect in that round's scope:

| Case(s) | What happened | Class | Outcome |
|---|---|---|---|
| ads-weekly (H1) | With no insight rows read, the narrate prompt still received the report date, so the model wrote "(09/09)" into a report whose headline was "THIẾU". To an owner every digit in a no-data report reads as a measured figure | product defect | The prompt now withholds the date entirely and forbids every digit when `available=False`; with rows it still passes the date and the totals. Both branches pinned in `tests/test_ads_pack.py` with a recorded LLM |
| 3 cases | Timed out on the client's own clock — a 180 s delegate POST and a 300 s settle wait, while the fleet was still inside its first attempt and the client still had retry budget left | test-side, not product | `DELEGATE_TIMEOUT_S = 900` and `SETTLE_TIMEOUT_S = 900.0` moved into `tests/fullflow_live/topology.py`, the value the rest of the suite had already adopted locally for the same measured reason |
| `multi_brief_session` | A genuine upstream stall, already at the 900 s bound | upstream | rerun green |
| 1 fast-lane case | Returned a list of commands | model variance | rerun green |

No assertion was loosened. The stall behaviour the reds brushed against is product-side and
already bounded: `my_crew/llm/client.py` carries idle-based stall recovery
(`_STREAM_IDLE_S = 120.0`, `_MAX_STALLED_ATTEMPTS = 2`). The bound is on *idle* time, not wall
clock, so a slow answer is never abandoned and a silent one is.

`docs/releasing.md` said the full suite takes "~12 min", which was stale by an order of
magnitude and would have led someone to start it in the wrong slot. Corrected to ~3h with the
measured 0.19.0 figure and a note that it is dominated by wall-clock waiting on the model, so
a faster machine does not shorten it.

## Known limitation still shipped in 0.19.0

Unchanged from 0.18.0: a worker whose runtime can call tools may split its work to peers whose
runtime cannot, silently turning a lookup into an answer typed from memory. The capability
guard that would have blocked this was rejected by decision and dropped. `l3` and `l5` passing
in a given run does not retire the limitation — whether a split lands on a tool-capable peer
is a model choice that varies run to run.

## Not measured

- **Deliverable quality (blind judge)**: still not at n ≥ 3 per revision. Unchanged since 0.17.0.
- **Reliability (k = 5 replays)**: baseline on file is still `reliability_baseline_0.15.0.json`,
  now four releases stale.
- **Effort / budget honoured upstream**: measured *not* honoured on this model at 0.18.0; not
  re-measured, no product change.
- **A recut of the live fullflow on the exact release commit**: the 3h03 run above was on the
  template-skills tree, and the only commits after it are the version bump, doc edits and the
  advisor probe fix — none of which touch a live path. The quick subset and every gate in the
  first table were re-run on the release tree.
