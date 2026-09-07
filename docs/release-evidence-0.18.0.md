# Release evidence — 0.18.0

2026-09-06 → 09-07 · tag `v0.18.0`

What was measured before cutting 0.18.0, and what was *not*. Working notes live in the
gitignored `plans/reports/bench-260905-*` report and the journals
`docs/journals/260905-deepseek-single-model-role-scorecard.md`; this file is the part that
has to survive in the repo. The previous cut's evidence is
[release-evidence-0.17.0.md](release-evidence-0.17.0.md).

The release question this time was not "is the new code better" but "which of the seven
model roles is the one fleet model good at", because every role now runs on
`~deepseek/deepseek-v4-flash-latest` under the per-role reasoning policy.

## Gate results

| Gate | Result |
|---|---|
| BE pytest | 4821 passed / 1 skipped (live deselected), at the release commit |
| FE vitest | 417 passed / 59 files |
| ruff | clean |
| tsc | exit 0 |
| Playwright mocked smoke | 44 passed (desktop + mobile projects) |
| cold-start smoke `--browser` | 6/6 steps on wheel `my_crew-0.18.0-py3-none-any.whl` (97 `_shipped/` files, 26 FE dist) + Playwright 2/2 |
| routing bench vs `v0.17.0` worktree | no differences across compared axes |
| release bench vs `v0.17.0` worktree | no differences across compared axes |

Every gate in this table was re-run after the LAST round of fixes below, on a wheel
rebuilt from the release tree — not on a wheel an earlier round produced.

## Role scorecard (`scripts/run-sprint-benchmark.py roles`)

Each of the seven roles is driven through its real prompt builder and real parser and
scored deterministically; every replay records the OpenRouter upstream that served it.
All runs on the same model and the same `role_reasoning` policy, `provider_ignore` unset.

| Run | plan | review | util | content / aggregate / advisor / sprint_low |
|---|---|---|---|---|
| baseline `c93c4bc`, k=3 (`bench/role_baseline_0.17.0.json`) | 35/36 good | 47/51 (0.92) good | 17/18 good | all 1.00 good |
| HEAD `783c75c`, k=3 | 33/36 (0.92) good | 42/51 (0.82) **watch** | 18/18 good | all 1.00 good |
| HEAD, review only, thinking OFF, k=6 | — | 91/102 (0.89) watch | — | — |

Read with the upstream column:

- **The HEAD review drop is a routing episode, not a code regression.** Its 9 failures sit
  on two upstreams (DigitalOcean 5 — thinking burned the 16k cap 4/4 times; OpenInference
  4 — prose instead of JSON); the 19 review calls served by eight other upstreams had 0
  failures. The code diff between the two runs (slot parser, intake retry, refutation
  filter, cap-burn re-ask, `provider_ignore` knob) cannot produce a cap burn or prose. The
  baseline therefore stays at `c93c4bc`; a recut is due when routing settles.
- **Review keeps thinking on.** Thinking off makes review 8× faster (6.8 s vs 58 s) and
  cheaper, but the H4 tallies move the wrong way: catch rate on planted defects 98/144
  (0.68) against 61/63 (0.97) with thinking on; false fails 4/46 vs 1/24. The parse rate
  alone (0.89) would have hidden that.
- **util 17/18 → 18/18** is the one measured code win: the slot-extraction prompt now
  demands one of the allowed codes.
- **plan 0.97 → 0.92** is three replays: one intent misread, one decomposition parse, and
  one intake where the model wrote a full report instead of JSON twice in a row; the new
  intake retry fired both times and the second garbage reply fell open as designed.

## Cap burn → thinking-off re-ask (the measurement behind the `Fixed` entry)

| Question | Measured |
|---|---|
| Does repeating the same request after a cap burn help? | hit the cap again 5/6 |
| Do `reasoning.effort=low` / `max_tokens=2048` bound the thinking? | no: 10,833/15,746 and 10,210/16,030 reasoning tokens |
| Is a thinking-off review self-check usable? | 24/24 parseable, 23/24 correct, 1–23 s (fresh run) |
| Same re-ask on the upstream that just burned | 0/4 useful (rambled to the cap, misjudged) |

Hence: re-ask once with thinking off **and** skip the burning upstream; a request that
already ran with thinking off is returned as-is.

## Live fullflow against the real fleet

Quick subset (`-m "live and not live_slow"`), the pre-release gate: **38 passed / 3 failed**
first pass. Each red was classified before anything was rerun:

| Case | What happened | Class | Outcome |
|---|---|---|---|
| A8 (12-entity lookup brief ends as a sprint) | decompose planned web steps, the "shape" route re-planned through the intake and the sprint lost `needs_web`; on the rerun the classifier returned `assign_team_task` with an empty `brief` and the CEO was asked "Mô tả việc cần giao cho đội?" with the extractor's `sprint:`/`team:` rule printed in the question | two product defects | `_carry_web_need`; empty-brief fill on a structured message; slot `prompt` / `hint` split |
| C2 (hard brief scored `high`) | the slot extractor paraphrased the 364-character brief to 104 characters, dropping the contradiction the rubric keys on (356 → `medium` once, 104 → `medium` once, passed once) | paraphrase loss + rubric variance | `_keep_ceo_structure` 60% length rule; effort probe on the full brief k=6: `high` 4, `medium` 1, empty body 1 (all six served by `Sail Research`) — the residual is the rubric's own "when in doubt pick the lower tier" |
| A3/A4 (guarded brief never takes the fast lane) | first pass: model kept `needs_shell` / omitted `pic_id` / used a literal `pic` assignee; green 3/3 on the first rerun; on the fixed-code rerun the external-write case went to a sprint because the slot extractor returned the classifier prompt's own example ("Tổng hợp giá bán lẻ iPhone 17 Pro tại VN") as the brief, so no `sprint_refusal` word was left to read | one defect (example echo, 1/4) + variance | `_keep_ceo_structure` restores the message when the brief lost the refusal words or is mostly words the CEO never typed; decompose slips left as variance, candidate repairs noted below |

Rerun of the three on the fixed code: C2 green, A8 green, A3/A4 shell green, A3/A4
external-write red (the example echo above, 1,200 s for the four); after that fix A3/A4
2/2 green (699 s). Total across the reruns: every red either has a code fix with an
offline test or a measured variance figure; no test was loosened.

Full suite (`-m live`): **27 passed / 1 failed in 5.674 s (1:34:34)**, down from eleven
reds on the pre-fix tree. l3 and l5 both green this run (the split-peer shape the CEO
ordered left unfixed).

The single red was a real product defect, not flake: X2 (`cost_cap`) timed out after
300 s waiting for a task to stall, with `cost_usd=0`. Root-caused from the surviving
pytest home, then reproduced deterministically offline — with `TINY_CAP_USD = 0.001`
and `MAX_STEPS = 7` one step's share is $0.00014286, decompose had already spent
$0.00094916, leaving $0.00005084 of headroom. Too little to dispatch a step, too much
to trip a hard stop that only fires ABOVE the cap. The task could neither spend nor
stop and sat `open` forever. Fixed by `_cost_starved_result`
(`cost_cap_exhausted`), pinned by three offline tests, and the live case now accepts
either budget ending keyed on the stamped failure mode. Verified failing without the
fix (`action='none'`) and passing with it.

A second observation from the same evidence, NOT a code defect: decompose planned three
phases but wrote one step row whose title joined all three with semicolons. Checked —
`TeamStepPlan` rejects a list title outright and `replace_steps` writes exactly what it
is given, so nothing in the code collapses steps. The model itself wrote one step under
an extreme cap. A model-quality observation for the roles bench, not a bug.

## Journey baseline

9/9 live in 380 s → `bench/journey_baseline_0.18.0.json`, compared with
`journey_baseline_0.17.0.json` (cut on `anthropic/claude-haiku-4.5`, so the cost column is a
model-price change first):

| Journey | 0.17.0 | 0.18.0 | Reading |
|---|---|---|---|
| j1 outside caller → settled | `done`, lanes sprint→review→rework, $0.029 | `parked:open` (`needs_decision`), lane sprint, $0.0009, 122 s | The brief ("Viết một đoạn giới thiệu ngắn về công ty") carries no company facts. The writer consulted the analyst, who invented a profile ("AI Agent Testing", "Công ty ABC"); the self-check refused the invented name and field; the rework put the "dữ liệu chưa qua soát" label inside homepage copy and the second self-check refused that too, so the task parks for the CEO. That is the honest outcome for a brief with no source — the 0.17.0 run shipped the invented copy as `done`. The test pins invariants (monotone status, cost > 0, audit chain), not the terminal state. |
| j1b stale hash refused | 2.8 s | 12.9 s | same verdict, slower model |
| j2 escalation keeps its source | `parked:open`, 12.2 s | `parked:open`, 57.5 s | unchanged state |
| j5 hard kill → next fleet finishes | `parked:open`, $0.0117 | `parked:open`, $0.0001 | unchanged state |

Every journey stayed under the 0.30 USD ceiling. One thing worth a look next round, not a
gate: the memory-extraction util call on j1 answered with an English translation of the
paragraph instead of project facts (upstream `OpenInference`); `foreign_letters` guards the
advisor note only.

## Defaults that changed, and what that means for the numbers

- **One model for every role.** The coordinator advisor no longer pins Haiku. Journey and
  role costs are now on `deepseek-v4-flash` throughout; the 0.17.0 journey baseline was cut
  on `anthropic/claude-haiku-4.5`, so per-journey cost deltas against it are a model-price
  change first.
- **`max_tokens` = 16,384 on every request.** A runaway stream the idle guard could not see
  (903 s / 107 KB) is now cut; a thinking model can spend the whole cap thinking, which is
  what the cap-burn re-ask handles.
- **`provider_ignore` is opt-in and unset in shipped profiles.** The measured evidence
  (Sail Research empty 3/6 on util k=6; DigitalOcean cap burn 4/4 on review k=3) is two
  small samples, not enough to pin routing for every install. A bench run with it set is
  not comparable to one without.

## Candidate repairs not made (variance, not defect)

- A decomposition whose final step is handed to a literal `pic` assignee could be repaired
  in code like `repair_terminal_assignee` is. Seen 1/4 on A3/A4; the re-prompt recovers it.
  (The sibling case — `pic_id` missing while the terminal step names one person — stopped
  being variance when the full live suite showed it burning all four attempts, and now has
  a repair: see the second round below.)

## Second round: what the FULL live suite added

The quick subset above is a pre-release gate, not the whole story. Running `-m live` end to
end turned up eleven reds. Each was traced to a cause before anything was changed, and the
eleven collapsed into seven distinct defects plus two left unfixed by decision:

| Case(s) | Root cause found | Fix |
|---|---|---|
| a1, a6, a7, a8 | The classifier invents its own slot key names (`description`, `task`, `request`, `task_description`, `query`, `summary` — 6/6 on a6), so a brief the CEO had already typed read as missing and was asked for again; a `team:` prefix was downgraded to `sprint:` | `_adopt_aliased_slots` moves the stray value onto the real slot when exactly one known slot is missing and exactly one unknown string key arrived; `_restore_mode_prefix` now lets the CEO's own prefix win over one the model wrote |
| d1 (3/6) | A question about this company's own headcount was routed out as a delegated lookup. The prompt contradicted itself: "who holds which position" was always a command, while "internal data" was a question | The external-lookup rule is scoped to *another company*, with an explicit paragraph that in-house questions are answered here. The boundary is where the data lives, not whether it changes over time |
| a3/a4 (shell) | Decompose answered `test\_suite`; JSON forbids that escape, and all four attempts died on the same unparseable body | `repair_invalid_escapes` + one retry in `parse_decomposed_task`; a genuinely broken answer still raises the original error |
| l1 | A valid single-owner plan with a blank `pic_id` burned all four attempts on "thiếu pic_id" | `repair_missing_pic` fills it from the sole terminal step's assignee when that assignee is on staff; two terminals or an unknown assignee is left alone |
| l1b | `research_gap` fired on an internal-history brief whose listed "entities" were the phases of the job itself, forcing a pointless web step | At least one listed item must contain a named thing out in the world |
| x2b | Spend before a clarify pause was invisible to the cost cap. The cap reads `sum_cost` (the step rows), not `cost_usd_total`; a step paused on a CEO question had spent real money and the cap saw zero for the whole wait | `mark_waiting_clarify(cost_usd=…)` writes it on the step row via `charge_task_total=False`; the terminal write still charges the task total exactly once |
| l3, l5 | A tools-tier analyst split its lookup out to native-tier peers (secretary, writer), so the task recorded zero tool calls and the audit/stats assertions found nothing | **Not fixed.** A split-peer capability guard was proposed and the CEO rejected it, then ordered it dropped entirely. Recorded as a known limitation below |

Also fixed in passing: an operator-precedence bug in the classifier's command-catalog line,
where the conditional swallowed its entire left-hand side. It did not misrender in practice;
it is fixed and pinned with a test.

## Third round: three defects found by auditing the second round's own fixes

Neither of these was a live red. Both were found by probing the seams the second round had
just touched, and both were reproduced before being changed.

| Found in | Defect | Fix |
| --- | --- | --- |
| `repair_invalid_escapes` | The scan walked backslash by backslash without consuming valid pairs, so in a legally escaped backslash followed by a bad-escape character (`"C:\\_x"`) it deleted the second half of the valid pair and produced the exact corruption it exists to remove. Reproduced: a document that parsed before the repair failed to parse after it | The pattern now matches a whole escape sequence, valid pair or lone backslash, and only drops the lone one. `test\_suite` is still repaired |
| `mark_awaiting_approval` | The clarify-pause cost fix has a twin the second round missed: an approval gate pauses a step the same way, and its store write recorded no spend, so a step that had spent real money and was waiting on a human reported zero to the cost cap for the whole wait. Reproduced on a scratch store: step cost `None`, `sum_cost` `0.0` | The write records the spend on the step row under the same `charge_task_total=False` contract, leaving `approval_id` pollable and the task total charged once at the terminal write |
| `_restore_mode_prefix` | The second round made the CEO's own mode prefix beat one the model wrote, but only when the CEO had typed a prefix at all. On a brief typed with no prefix, a prefix the model invented survived into `brief`, where the router reads it as an order: it skips `classify_brief` and records the mode as the CEO's own. Reproduced: a bare brief came back under `sprint:` and the router read `forced_mode == "sprint"` | A prefix in the slot with none in the message is dropped, so the router classifies. A prefix the CEO typed still wins. The old test pinned the invented prefix as kept; its own comment said the opposite, so the premise was corrected rather than the assertion loosened |

## Fourth round: the defect the full live suite found

| Seam | What was wrong | Fix |
| --- | --- | --- |
| `_act_on_task` cost guards | The hard stop fires only when spend EXCEEDS the cap; the pre-spawn gate refuses a step it cannot afford and defers it, on the documented assumption that a running step will finish and release headroom. With nothing running that assumption never comes true, so a task with spend under the cap and less than one step estimate left could neither spend nor stop. Measured live (X2 timed out after 300 s, `cost_usd=0`): decompose spent $0.00094916 of a $0.001 cap, leaving $0.00005084 against a $0.00014286 step share. Reproduced deterministically offline before any change | `_cost_starved_result` concludes such a task the way a breached cap does (verdict, salvage, escalation, lesson) under a distinct `cost_cap_exhausted` kind that counts as `cost_cap` in the retro, with a message that says the budget ran out rather than claiming an overshoot. Three offline tests: the dead zone concludes, a task with real headroom still dispatches, and a task whose step is merely dep-blocked is not mistaken for a broke one |

The live case itself asserted an overshoot as the ONLY budget ending, which would now fail
on a fleet that got CHEAPER. Its premise was corrected, not loosened: it accepts either
ending, keyed on the failure mode stamped on the route record, so a stall from any
unrelated cause still fails it.

Offline suite after all four rounds: **4821 passed / 1 skipped**, up from 4802. No assertion
was loosened; every fix carries an offline test that fails without it.

## Known limitation shipped in 0.18.0

A worker whose runtime can call tools may split its work to peers whose runtime cannot,
which silently turns a lookup into an answer typed from memory. The capability guard that
would have blocked this was rejected by decision and the guard was dropped entirely.
Nothing in the product prevents this shape today. Both `l3` and `l5` passed in the final
full live run, which does not retire the limitation: whether a split lands on a
tool-capable peer is a model choice that varies run to run, so those cases can go red
again without any code changing.

## Not measured

- **Deliverable quality (blind judge)**: still not at n ≥ 3 per revision. Unchanged from 0.17.0.
- **Reliability (k = 5 replays)**: baseline on file is still `reliability_baseline_0.15.0.json`.
- **Effort / budget honoured upstream**: measured *not* honoured on this model (table above);
  no product change, recorded so the next release does not re-measure it by accident.
- **Intake "empty" without a fail-open log line** (1 replay): probe counted it as fallback
  while the loader logged no fail-open; possibly a valid JSON whose `goal` copied the brief
  verbatim. Not chased.
