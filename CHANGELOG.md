# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: semver.
Development history at finer grain lives in [docs/journals/](docs/journals/).

## [0.17.0] — 2026-09-03

What was measured before this cut, and what could not be: [docs/release-evidence-0.17.0.md](docs/release-evidence-0.17.0.md).

A team task now always ends with a conclusion in the room. Until now a worker that gave
up, a cost-cap breach, or a plan-hash mismatch could leave a task `stalled` with nothing
delivered; every one of those paths now writes a summary of what was and was not done,
delivers it under the ⛔ head, and escalates once. Before giving up at all, the
coordinator skips a dead middle step or does a dead terminal step itself from its
dependencies, and the stuck-step judge can rule that a result which failed its own
self-check actually met the acceptance list.

A crew is only kept when there is a boundary one strong agent cannot cross. A role is
now a capability tuple (tier, web, mail, model); neighbouring steps that would run on
the same tuple fold into one; the router keeps a team plan only as do + independent
review or as a permission chain, and runs everything else as a sprint. The bench that
decided this is in the repo, with its kill lines.

Two defaults change. `cost_cap_usd` is now on for the tool tiers (1.0 USD per step,
native stays uncapped), where 0.16.0 shipped it opt-in. The OpenAlex academic-search
tool is removed; it rate-limited by IP and was never a dependable lookup.

### Added
- **A worker step is briefed like a delegation, not a chat turn.** Every work and rework
  prompt now carries the step's own acceptance rubric verbatim under "TIÊU CHÍ NGHIỆM THU"
  and the titles of the sibling steps under "VIỆC CỦA BƯỚC KHÁC (KHÔNG làm ở đây)" —
  objective, grading rule and scope boundary in one block (`step_delegation_brief.py`).
  Review rows and system-inserted steps are not listed; the list is capped at six titles.
- **Provenance travels with the artifact.** When a step's dependencies left N source URLs,
  the artifact contract for a `draft`/`final` step demands at least one `http` link in the
  body (`ArtifactContract.upstream_sources`); a summary that drops every source fails in
  code before any grader sees it. Counted over dependency artifacts only — links the CEO
  pasted into the brief do not create the demand.
- **Every terminal stall carries one failure mode** (`task_failure_mode.py`): `cost_cap`,
  `plan_mismatch`, `verification_exhausted`, `dead_step`, `step_exhausted`, each in a MAST
  group (spec / verification / system). The escalation stamps `route.failure_mode` once
  (first terminal event wins, `source` untouched); `route_stats` gains a "Kết cục thất bại"
  section counting modes and groups. Step-level rulings that put a step back to pending
  write nothing.
- **Grader calibration verdict (H4)** in `bench/hypothesis_stats.py`: a grader keeps only
  if its false-fail rate on CORRECT artifacts is ≤ 0.25 AND its catch rate on planted
  errors is ≥ 0.50, each side with its own 12-sample floor, Wilson interval on both. Bench
  on Haiku: self-check and peer review both 3/12 false fails, 10/12 caught — keep, exactly
  on the line; all six false fails are one ambiguous rubric line (deposit in a 24-month
  total), and neither grader adds up a budget column.

- **Context-crew: a role is a capability tuple, a hand-off is an artifact, and a crew has one
  of two shapes.** `Capability(tier, web, mail, model)` is derived from the profile; two
  neighbouring plan steps split across agents with the same tuple now fold into one. Every
  content step owes its dependents an artifact by kind (`findings` needs a source URL, `final`
  needs a real body) and is checked by code before the LLM self-check. The router keeps a
  team plan only when it is a do + independent review or a permission chain; any other plan
  runs as a sprint (`route.source="shape"`). Team routes record `route.shape` and three new
  signals (`independent_sources`, `needs_independent_review`, `sensitive_tool`);
  `route_stats` counts shapes.
- **Hypothesis bench for the crew shapes** (`my_crew/bench/hypothesis_stats.py`): fixed kill
  lines (min 4 cases × 3 runs, Wilson interval reported) that decide whether each shape stays
  in the router. The first round (4 briefs × 3 runs, blind 3-vote judge) kept do + review
  (independent reviewer caught 10/12 seeded-error artifacts, 8% run disagreement) and killed
  fan-out/merge: a crew of parallel lookups won 4/12 pairs against one strong agent at 1.5×
  the cost, and a cheap-specialist variant won 4/12 at 0.6×. The fan-out shape was removed
  from the router; the runtime entity fan-out inside an existing crew (v74) is unchanged.
  Live cases `tests/fullflow_live/test_live_crew_shapes.py` pin one brief per surviving
  shape plus a forced-team source-listing brief recorded as `custom`.

### Changed
- **Per-step `cost_cap_usd` is now ON by default for the tool tiers** (`create_agent`,
  `deep_agent`: 1.0 USD, half the task-level default). It was opt-in through 0.16.0. Native
  stays uncapped (one call, no loop); a profile value still overrides.
- **Fewer wasted rounds on a dead step.** Rework is capped at one round (was two); a terminal
  step gets one coordinator intervention before the coordinator does it itself (non-terminal
  steps keep two); a `needs_web` step whose search fails is a tool error retried by the
  machine, not an artifact sent to a grader; a plan with a step nobody can measure is retried
  once and then run as a sprint (`route.source="unmeasurable"`).
- **A work step runs on its assignee's tier, not on the coordinator's guess about the web.**
  The rule that forced every `needs_web=false` work step onto the native runtime is gone: a
  tools-tier role (`create_agent`, `deep_agent`) keeps its loop for its work steps, so a
  "clone and run the tests" step no longer lands on a runtime with no shell. Only review and
  sprint steps, and a work step whose deps were prefetched for it, run native; one
  coordinator ruling on such a step re-arms the assignee's tier.
- **A team tick is fleet-wide exclusive.** A poked tick and the scheduled tick used to run the
  same store concurrently; `run_team_tick` now takes a lock under the team-tasks root and the
  loser returns `tick_in_flight` without touching anything (not counted as a failure, not
  poke-worthy).
- **A refusal outranks an unmeasurable plan.** A brief the sprint intake refused (shell, repo
  clone, writes outside the company) whose team plan cannot be measured is raised to the CEO
  with the rewrite hint instead of being silently downgraded to the sprint it was refused for.
- **Execution outcomes count as measurable.** "test suite passes", "build exits without
  fail", "the command's log shows X" are machine-checkable acceptance anchors, so a shell
  brief no longer plans as unmeasurable.
- **A refused "write outside the company" brief keeps its permission boundary even when the
  planning model drops the flag**: the terminal step is marked `external_write`, so the
  review/gateway path is never skipped by the shape gate.
- **A team task that cannot finish now always ends with a conclusion in the room.** Every
  path that used to leave the task `stalled` with nothing delivered (a step the worker gave
  up on, a cost-cap breach, a plan-hash mismatch after a system-inserted row) now writes a
  `final_summary` naming what was done and what was not, delivers it to the room under the
  ⛔ head, and escalates once. The best completed step artifact is salvaged into that
  summary so partial work still reaches the CEO.
- **The coordinator finishes a dead step itself before giving up.** When a worker fails a
  step for good, the coordinator first skips it (a non-terminal step with live siblings,
  the gap noted in the handoff) or does it itself from the step's deps (a terminal
  work/sprint/rework step, unless the task requires CEO approval). The self-written
  artifact carries `coordinator_fallback`, and the aggregate header says who did the step
  and why. Only when neither rung applies does the task conclude as failed.
- **The coordinator can rule "accept" on a step that failed its own self-check.** Until
  now its only rulings were retry, reassign, or give up, so a result that actually met
  the step's acceptance list (measured live: a cohort analysis carrying every required
  figure, failed twice for "not mentioning" them) could only be retried or redone. The
  judge may now take the result as it stands; the step is done with the worker's own
  artifact, annotated with the reason, and no further attempt is spent.
- **The judge reads the CEO's full request, not the 120-character title.** The stuck-step
  brief used to carry only the task title, which is the request's first paragraph cut at
  120 characters, so a judge could conclude the brief itself was truncated and send the
  worker to "check the original brief" it already had. The brief now includes the
  original request (capped at 2000 characters).
- **A rework round that changes nothing ends the review loop.** The worker compares the
  normalized failure set of the previous self-check with the current one; when nothing was
  cleared, the remaining rework budget is not spent and the step is delivered flagged
  (`self_check_failed`) for the coordinator to decide.

### Removed
- **The OpenAlex academic-search tool is gone**, along with the `academic_search:` profile
  flag that armed it, its "tra cứu paper" template chip, and the "no key needed" mention
  on the connections page. It was keyless, which made it easy to attach, but it rate-limits
  by IP and returned HTTP 429 on every attempt to benchmark it, so an agent relying on it
  had no dependable lookup at all. Agents that need to look things up should use web search
  (`web_search: true` plus a Tavily or Brave key) or web scrape (Firecrawl).
- The `researcher` template is now `version: 2`. Agents created from v1 carry a stale
  `academic_search` key in their config baseline; both runtimes still accept and ignore it,
  so those profiles keep loading, and the upgrade preview simply stops reporting the field.

### Fixed
- **The coordinator's own write over a stuck step dropped the CEO's cross-check.** On a
  plan routed as do+review, a worker that gave up made the coordinator write the step
  itself, and that fallback cleared the review flag: no reviewer was ever minted and the
  task closed "after cross-check" with nobody having read it. The stuck-judge accept path
  already kept the flag on that shape; the self-do path now shares the same rule
  (`keeps_planned_review`). Measured live before the fix.
- **The deterministic step gate read an amount as an item count.** "cộng đúng 90 triệu"
  in a rubric became "at least 90 list items" and sent a correct five-week event plan to
  rework on every calibration run. A unit or decimal right after the digits (tr, triệu,
  tỷ, %, k, đ, vnd, usd, `1,5`) no longer counts as a quantity demand.
- **A stalled provider can no longer hold an LLM call open indefinitely.** OpenRouter keeps a stalled socket busy with keep-alive bytes, so the client's 60s read timeout never fired; measured live, one decompose sat past 900s and the synchronous delegate never answered. Every completion now streams and is bounded by idle time (`_STREAM_IDLE_S`, 120s without a chunk): a silent call is abandoned on its worker thread, counted as transient and retried; a second silent attempt in a row gives the model up for that call so the chain (or the caller's own retry) moves on instead of burning five attempts on silence. A slow answer is never cut — the same evening the live model ran at ~23 tokens/s and a legitimate review took 190s, which the wall-clock ceiling first tried in its place would have killed. Usage and OpenRouter's `cost` still arrive on the final streamed chunk, so cost accounting is unchanged.
- **Two workers starting together no longer crash on the once-only `.data/` migration.** Both passed the guard before either created the target, the first rename won, and the second died in `main()` over a store that was already safely under `agents/default/`. The sibling's move is now recognised and skipped.
- **The live harness now serves the fleet on the model it declares.** `boot()` inherited the developer's `OPENROUTER_MODEL` and the child's own `.env` could not override it, and the per-role models were written under a key the config never reads; every live run had declared haiku and served the default model. `serve_env()` sets both explicitly, guarded offline by `tests/test_live_topology_fleet_model.py`.
- **The live harness's stop condition recognises a task parked behind a CEO question.** A `pending` step whose dependency is parked (transitively) cannot move on its own; polling on waited the full 900s and failed a case whose assertions all held.
- **A mail brief no longer stalls on `plan_hash mismatch` before its first step.** The
  confirm-time hash has carried `needs_mail` since v92, but the assign path persisted the
  step rows without it, so the ticker's dispatch-time recheck failed on every tick and the
  task stalled with nothing spawned (measured live: "Rà soát hộp thư..." → both steps
  pending forever). The row now carries the flag; the recheck passes.
- **Accepting a stuck step on a do+review plan keeps the planned reviewer.** The stuck
  judge's accept dropped the review flag ("the judge's reading was the review"), so on a
  plan the CEO shaped as do+review no review row was ever minted and the task closed
  "sau soát chéo" with nobody having cross-checked anything. On that shape the flag now
  survives the accept and the reviewer row is minted as planned; every other route keeps
  the old drop.
- **A reviewer that answers with nothing no longer kills the task.** The review step
  parses the grader's JSON verdict strictly; a cheap reviewer model was measured live
  returning an empty completion, the parse failed, and the whole task stalled as a
  "dead step" for the CEO to sort out. The review step now re-asks the same prompt once
  before failing (both calls are billed and recorded), the same machine retry the
  runtime already applies to tool errors.
- **"Rà soát rồi lập báo cáo" no longer conscripts a second reviewer.** Bare "rà soát"
  was counted as a request for an independent review, so a brief asking the author to
  read the material and then write got an unasked-for review step appended (and, above,
  a stall when that step died). Only "rà soát lại" / "soát chéo" / "nhờ người khác"
  phrasings now raise the independent-review signal.
- **`cost_cap_usd: 0` is now rejected instead of silently emptying every step.** The
  ceiling is checked before a step's first provider call, so a zero cap ended every
  tools-tier step at round zero — no model call, no work, only the "incomplete" note.
  Leaving the key unset is still how you say "no ceiling"; zero now fails at config-parse
  time with the reason. No shipped configuration set it, so nothing in a running fleet
  changes.
- **A cost-capped draft is delivered for a decision, never reworked.** A tools-tier step
  that hit its `cost_cap_usd` returned a capped draft with the incomplete note, the LLM
  self-check failed it (correctly: an intention, not a result), and the rework ran under
  the same ceiling — one call, a bare refusal, and the note the CEO needed was overwritten.
  A draft carrying the cap note is now terminal on its first failed check: no rework, the
  capped text is the artifact, the step parks `needs_decision`.
- **The self-check grades the step, not the whole brief.** A step whose acceptance covered
  only part (1a) of a three-part brief was failed for not delivering (1b) and (2) — the
  sibling steps' work — and the one rework it had left was spent on a refusal, so the
  dependent step never ran. The shared ceiling rule now says a step is ONE part of the
  brief and the parts its criteria do not name belong to other steps.
- **The deterministic item count reads "liệt kê đúng N" and states its direction.** "Liệt
  kê đúng 4 rủi ro" was not read as a demand for four items, and the fact line handed to the
  grader — "kết quả có 28 mục (tiêu chí đòi 2)" — was cited by it as a failure. The count
  regex accepts `đúng`, and the fact reads "không ít hơn con số tối thiểu N … nhiều dòng hơn
  KHÔNG phải lỗi".
- **The planner sees which agent has tools.** The decompose and sprint-intake rosters listed
  agents by domain only, so a "tra lịch sử làm việc nội bộ" step was assigned to the native
  secretary (no history tool) one live run in four. Each roster line now carries a
  capability hint derived from the role tuple ("có công cụ tra lịch sử …; tra được web" /
  "không có công cụ — chỉ viết/suy luận"), and both prompts carry the rule to route
  tool steps by it (`planning_roster()`).

### Verification
Gates: 4660 BE passed / 1 skipped, 417 vitest, ruff and tsc clean, cold-start smoke
`--browser` 6/6 on the built wheel. Routing and release benches against a `v0.16.0`
worktree show no route or spend deltas (the routing rows differ only by three new signal
keys). Live: 66 fullflow cases on a real fleet, 63 green first pass; the three reds
reran green, the one red found on a second pass was a real bug (the coordinator's own
write dropping a planned review) and is fixed above. A journey baseline was cut on a
real fleet after the bump (`bench/journey_baseline_0.17.0.json`, 9 passed); it is the
first one actually on the model the harness declares, so it is the first baseline the
next release can compare cost against.

## [0.16.0] — 2026-09-01

What was measured before this cut, and what could not be: [docs/release-evidence-0.16.0.md](docs/release-evidence-0.16.0.md).

A long tool result no longer costs its size on every round that follows it, and a long
step no longer pushes the next step's prompt past what the model can use. Both were
paid for silently: the thin loop re-sends its whole message list each round, so one big
search result was billed again and again, and a dependency's full text went into the
next prompt whole no matter how long it ran.

Two bounds now sit in the way. A tool result over 12,000 characters keeps its full text
in a per-task artifact and hands the loop a preview stating the real size and where the
rest went. Each dependency contributes at most 8,000 characters to the next step's
prompt, with a marker saying how much was cut and which artifact holds the whole thing.
The artifact and the work order always keep the full text — a run has to stay replayable,
and a reviewer has to see what the graded step was actually given.

Every read a worker makes now leaves an audit row, so "which tool keeps failing" is a
question the trail can answer.

`cost_cap_usd` is opt-in and stays off unless you set it. It is a per-step ceiling
enforced only by the thin tool loop; the react loop and the deep-agent tier do not read
it. The task-level ceiling remains `company.team_task_cap_usd`, which is unchanged.

### Added
- **Oversized tool results move to an artifact.** Over 12,000 characters, the loop gets a
  preview with the true size and the artifact path instead of the body. Truncation is
  also detected by shape when the provider reports no `finish_reason`: a body that opened
  a JSON structure and never closed it is a cut-off write, not a malformed one, so it
  stops taking the retry that asks the model to rewrite the same too-long plan.
- **A per-dependency cap on the prompt path.** 8,000 characters per dep, cut on a
  delimiter boundary so a search-result block is never left unclosed, with a marker
  naming the dropped character count and the artifact holding the full text. Artifacts
  and work orders are deliberately exempt.
- **An audit row for every read-tool call** — actor, task, step, elapsed time, and
  whether the body succeeded, kept separate from the policy verdict so a served read and
  a failed one are distinguishable. Arguments are not recorded.
- **Per-tool call statistics** aggregated from that trail.
- **`cost_cap_usd` per step (opt-in).** Default `None` on all three tiers; only the thin
  tool loop enforces it.

### Changed
- **Default fleet model is now `~deepseek/deepseek-v4-flash-latest`.** The leading `~`
  is part of the model ID; stripping it yields a 400.

### Fixed
- **A dropped step's cost-cap note survives.** It was being swallowed by the drop branch,
  so the one message explaining why the work stopped never reached the reader.
- **Degrade-and-continue.** A non-terminal `give_up` becomes a skip-with-gap instead of
  ending the run, dropped review and rework rows end their chain correctly, and a review
  is never minted over a step that was already dropped.

### Verification
The dependency cap was measured live, not just offline: two journeys on a real fleet,
both green, at \$0.0065 / 502s and \$0.0123 / 1030s — each an order of magnitude under
the 0.30 USD per-journey ceiling. The case proves all four properties at once (a dep
really exceeded the cap, the marker appeared downstream, the work order kept full text,
and the marker's own dropped count reconciles against the artifact on disk).

## [0.15.0] — 2026-08-30

The crew can now be reached from outside the app, escalate past its own authority, hold
service credentials without leaving them in plaintext, and staff two new kinds of work.

A script or a CLI can hand the crew a job and poll it through a stable HTTP contract
instead of driving the web app. Work that exceeds an agent's authority no longer
dead-ends: it becomes a task for the manager agent, with three guards so it cannot turn
into a storm — an escalated task can never escalate again, a per-source daily cap holds
the volume, and a manager who cannot be assigned degrades to telling the operator
directly. Service tokens move into a per-account encrypted file; the only secret left in
`.env` is the master key, which the store writes itself and no HTTP route can set or
overwrite. Two worker packs — accounting and Meta Ads — read their sources for insight,
with any write still held by the gateway.

The Zalo channel and the customer-facing assistant are deliberately not in this release;
they wait on an approved Zalo OA.

Two of the fixes come from running the whole flow against a real model rather than a
stub, which is the only place they were visible: the assistant was answering questions
about prices and rates from its own stale memory instead of sending someone to look, and
a request touching the outside world — send this mail, clone this repo and run the tests
— came back as a list of commands instead of becoming work, worst on the admin catalog
where it missed four times in five.

### Added
- **A stable HTTP contract for callers outside the app.** `delegate_work`, unified task
  status, and a fleet overview, wrapping the same assign and store APIs the web app
  uses. A confirm must carry a current plan hash, so a stale or missing hash is refused
  rather than acting on a plan the caller never saw.
- **Escalation to the manager agent.** A request past an agent's authority mints a
  single-step manager task instead of dead-ending, and the owner is told where it came
  from. `company.yaml` gains `manager_id` and `escalation_daily_cap`; no UI writes them
  yet, so every save path preserves a hand-set value.
- **Encrypted at-rest credentials.** Per-account Fernet-encrypted `credentials.enc`
  replaces plaintext service tokens, with the master key written by the store itself on
  first use. The egress secret filter learns both Fernet shapes, so neither a ciphertext
  blob nor the key can leave in a log line or an outbound message.
- **Accounting and Meta Ads worker packs**, read-insight for now, with profile templates
  for each. Agents get a durable media dir the hygiene sweep never touches, distinct
  from the disposable tmp dir it now sweeps on a short window.
- **`my-crew agent purge-data`** for an orphaned data dir whose profile is already gone
  — the one case that has no profile to load, so it is handled before the load gate.

### Fixed
- **A question that needs a source becomes work instead of a guess.** Anything that
  changes over time — a price, a rate, the news — was answered from the model's own
  stale memory and no task was ever created. Such a question now goes to whoever can
  look it up. `unsupported` now means work nobody can be given, which is rare: a request
  touching the outside world goes to the team, where the gateway already holds it for
  approval.
- **A stalled sprint no longer erases its own routing source.** Marking a sprint a dead
  end overwrote the route's `source` with the literal `"dead_end"`, destroying the
  original source an escalated task needs to tell the owner where the work came from.
  The mark is its own flag now, counted separately in route stats and bench metrics.
- **The dead-sprint upgrade really does carry the unfinished work forward.** Its test
  seeded the handoff artifact in a shape the reader could not use, so the partial draft
  never reached the new plan and the case had never tested what it claimed to.

### Verification
33 full-flow cases against a real model (\$0.19, 19 min, no case above a quarter of its
cost ceiling); 4212 offline tests; the offline release and routing benches show no
change against 0.14.0 across 16 and 8 cases.

## [0.14.0] — 2026-08-30

Work now picks its own lane. Simple jobs run as a one-process sprint and finish in
minutes for cents; jobs that need the crew get the crew — and a sprint that hits a wall
can be handed to the crew mid-flight instead of being retyped from scratch. On the real
fleet the fast lane delivers 97% of its tasks at half the cost and a sixth of the wall
time of the crew lane.

A second model also rides along with running work and can flag a problem mid-step, and a
fleet is no longer confined to one vendor — chains can route per-role to any
OpenAI-compatible endpoint. Both are configurable from the agent page rather than by
hand-editing YAML.

The fixes come from two sources that CI cannot reach: a cold-start UAT (four defects that
only appear on a fresh install) and a new suite that runs the whole flow against the real
model, which caught the CEO's own lane instruction being silently discarded.

The crew lane then went through seven rounds of blind-judged benchmarking against the
sprint lane, and the theme of every round was the same: the crew rarely lost on the
quality of what it wrote, it lost by dying halfway through. A step that gave up killed
the whole task; a failed draft was thrown away; a review budget ran out and held a
finished task hostage; and a fix round was handed the coordinator's stale note over and
over, told to fix what it had just fixed. Each of those is now a degrade-and-continue
path with the gap declared honestly rather than a dead end. Re-running the four tasks
that died in round six: three now finish clean where none did, and the crew lane's cost
fell by 60% — the wasted rounds were the expense.

### Added
- **A step that gives up no longer kills the task.** A non-terminal step that honestly
  cannot finish becomes a *skip with a declared gap*: downstream steps run, and every
  prompt layer carries one shared rule for what a gap means — a result built on missing
  input must say so, in the deliverable, rather than inventing the missing piece. The
  failed draft is no longer discarded either: it travels forward under a
  `BẢN NHÁP CHƯA ĐẠT SOÁT` marker, and a downstream step may use it only if it labels
  the material as unreviewed. Verified on a real run where two steps died and the final
  deliverable came back complete and labelled.
- **Running out of review rounds delivers instead of stalling.** When the cross-review
  cap is spent, the chain ends quietly and the task delivers itself with a code-written
  header quoting the reviewer's remaining objections. Before, a task whose content was
  100% done could sit stalled waiting for a review round that would never come.
- **The crew stops splitting work that does not need splitting.** Decompose must now
  declare *why* each step deserves to be its own node (five boundary kinds, recorded but
  never trusted on their own), and a structural fold merges any step with exactly one
  dependency, the same assignee and the same permissions — inferred from the graph, so
  declaring a boundary that isn't there gains nothing. A three-step single-assignee
  linear plan folds all the way back to a sprint. The crew lane now runs 1–3 steps at
  roughly sprint cost, where earlier rounds cost three to four times as much.
- **Code checks the countable things before the model does.** Entity coverage and item
  counts are measured in code ahead of the LLM grader; a gap found this way fails
  immediately at full confidence without spending a call. Sprint keeps its own
  `coverage_gaps` path, which understands that a source refusing to publish a number is
  not a gap the writer can close.
- **Two lanes, and a way out when the wrong one was picked.** Simple work runs as a
  `sprint` (one process, one degenerate step); work that needs the crew runs as a
  `team`. A sprint that hits a wall mid-flight is no longer a dead end the CEO has to
  retype: `upgrade_to_team` rebuilds it as a crew task carrying the dead run's draft
  along as *reference* — the crew decides its own plan rather than inheriting a failed
  one. Measured on the real fleet: the fast lane delivers 97% of its tasks at half the
  cost and a sixth of the wall time of the crew lane.
- **Effort tier at intake.** The intake call already reads the brief, so it now also
  scores the work `low`/`medium`/`high` at no extra model call. Only `low` changes
  behaviour — a cheaper model role, a trimmed search budget, at most one revise round.
  `medium` is the previous behaviour untouched and the fail-open target of every broken
  path, so a garbage tier costs nothing. `high` is measured but not yet acted on.
- **The lane no longer depends on where you press Enter.** Three tasks written as three
  lines routed to the crew; the same three written inline as "(1) … (2) … (3) …" routed
  to a sprint. Inline enumeration now counts the same. It deliberately ignores a bare
  "N." mid-sentence, which in Vietnamese is nearly always a numbered noun — "Điều 1.
  Điều 2." is one job, not three, and used to be billed as three.
- **Benchmarks for release decisions.** `scripts/run-sprint-benchmark.py` gains four
  modes: `routing` and `release` compare two builds with zero model calls (so one can
  run inside a worktree at the previous tag), `tasks` reads the live store for what the
  fleet actually paid per lane, and `judge` blind-scores deliverable quality. The two
  comparing modes refuse to diff reports of differing `format_version` rather than
  silently mismatching them.
- **Router miss rates.** `dead_end`, `downgrade` and `upgrade` are measured over tasks
  that actually carry a route record; tasks predating routing are reported as lane
  `unknown` rather than folded into the denominator.
- **Advisor ride-along review.** Each team tick, a second model reads the transcript
  delta a running step just wrote and either stays silent (the default) or leaves one
  note — `nit` lands in the office room, `concern` becomes guidance for the step's next
  attempt. So a step going wrong can be caught while it runs, not at the end. Emission
  is guarded by dedupe, one note per step per sweep, and a cooldown, so a talkative
  model cannot flood the room. The advisor is its own entry in `MODEL_ROLES`, so it can
  point at a different provider than the workers — a team all running one model gains
  nothing from that model reviewing itself. The note travels the office feed as a new
  `advisor` event kind through the same per-kind allowlist as every other kind.
- **Multi-provider model chains** via a `provider::model` prefix. Providers are declared
  under `providers:` in company.yaml/profile.yaml (or `MY_CREW_PROVIDERS`) as
  `{name: {base_url, api_key_env}}` — only the env var NAME is stored, never key
  material, so a YAML carrying the registry stays safe to read and share. Chain fallback
  crosses vendors: a failing entry degrades to the next whoever serves it, and
  `fallback_from` keeps the full prefixed entry so cost stays attributable. A bare model
  id resolves through OpenRouter exactly as before, so configs with no `providers:` key
  are unchanged.
- **Per-role models and the advisor toggle in the profile form.** `role_models` and
  `runtime.advisor_enabled` were reachable only by hand-editing profile.yaml; both now
  round-trip through `GET`/`PATCH /api/agents/{id}/profile-settings` and the Hồ sơ tab.
  `role_models` is a whole-mapping replace rather than a leaf-merge, so a role dropped
  from the form actually disappears from YAML instead of silently continuing to bill.
  The `runtime` whitelist stays narrowed to the advisor flag, keeping
  checkpointer/store/postgres_dsn unreachable from the web.

### Fixed
- **A fix round was told to fix what it had just fixed.** The coordinator's note is
  written once per attempt, but the step re-read it on every rework round — so round two
  was handed round one's instruction, redid work already done, exhausted its budget and
  dropped. Only the first rework round of an attempt consumes the note now; later rounds
  strip it while keeping the standing wake-context line, which is the step's situation
  rather than a stale instruction. Re-running the four tasks that died in the previous
  benchmark round: three finish clean where none did (drops 2→0, salvages 2→0), and the
  crew lane's cost fell 60% because the wasted rounds were what it was paying for. Two
  further defects in the same strip were caught in review before release: the standing
  wake line was being deleted along with the note, and the anchor matched the first
  occurrence of the header, so a draft quoting the header truncated its own handoff.
- **A dropped step still spawned reviews of nothing.** A review row could be minted over
  a step that had already been dropped, and a dropped review or rework row left its
  chain open forever. Both now end the chain.
- **The stuck judge could not see its own previous guidance,** so it repeated the same
  advice at a step that had already followed it. It now reads its prior notes and is
  held to the step's acceptance criteria rather than raising the bar each round.
- **Graders demanded evidence nobody asked for.** Three prompt-level rules landed from
  live rounds: a source list frozen into the criteria at plan time cannot be treated as
  the only acceptable sources; a grader may not invent a metric the CEO never requested;
  and a cell honestly marked "not published", with the sources checked, is a passing
  cell rather than a blank. The last one turned a canary task from an empty table into a
  complete one.
- **The worker prompt was not anchored to today's date** while both its graders were, so
  a step could be marked as inventing data that was simply newer than its training. The
  same source-metadata rule the sprint intake follows is now also in the crew's decompose
  prompt.
- **Web search results never reached the step transcript,** so a reviewer reading the
  transcript concluded a step had fabricated what it had actually looked up.
- **A harmless phrase in a draft quarantined the entire artifact.** A salvaged draft
  containing wording that resembled an injection marker caused the whole handoff to be
  isolated. Fixed at the writing side by scanning markers when the draft is stored,
  rather than by loosening the quarantine.
- **A re-review graded the wrong draft.** A re-minted verdict pointed at the original
  step rather than the rework that replaced it, so round two of review scored round
  one's text.
- **A fix round never saw what the reviewer asked it to fix.** A rework step read its
  predecessor's artifact by the review row's own sequence number, but a review writes
  only `step-<graded_seq>-review-<round>.json` — so the read missed, the handoff came
  back empty, and the step redrafted from nothing but its own title. Measured across the
  live fleet the defect list reached 0 of 87 rework rows; it now reaches 87 of 87. The
  same row that read 0 characters at runtime yields 1296 with the failure list when
  replayed against the fixed code. Rework rounds that previously stalled on the same
  missing cells now pass review.
- **The reviewer's findings lost to the draft they rejected.** The search query is capped
  at 44 words (Brave rejects more with HTTP 422 and the step sees zero results), and the
  prior draft sat ahead of the defect list in the brief — so a fix round spent its whole
  budget re-searching the text that had just failed. The defect list now leads the query.
  It only helps where the step title leaves room: titles longer than the budget still
  crowd it out, tracked separately.
- **The blind judge pointed at a model the provider had removed.** `google/gemini-3-flash`
  returned HTTP 400 on the first vote, failing every judging run. `judge` is the only
  benchmark mode that spends money and only runs by hand, so no test covered the
  constant and the breakage surfaced only on a real run.
- **The routing lane the CEO explicitly asked for was silently discarded.** A message
  opening with `sprint:` or `team:` is a direct instruction, but the slot extractor read
  the brief as narration and dropped the prefix before it reached assignment — so the
  one surface built to let the CEO force a lane had no effect, and the guesser re-decided
  anyway. Found by the live suite; invisible to every offline test.
- **A correct classification was thrown away whenever the model added a sentence.**
  `json.loads` requires the entire response to be JSON, so a valid object followed by
  "I'll assign this to the team" raised `Extra data`, and both classification attempts
  failed into `question` — the CEO's delegation answered with chat instead of becoming
  work. Now reads the leading object and ignores trailing prose; genuinely malformed
  output still fails safe.
- **Miss rates were diluted by tasks that were never routed.** Dividing by every task in
  the store meant the rates improved on their own as history grew. Over the real fleet
  the corrected denominator moves the dead-end rate from 0.033 to 0.098 — the same
  failures, previously reported three times better than they were.
- **The live test suite's safety gate had never run.** A `pytestmark` declared in
  `conftest.py` is ignored by pytest silently — no error, no warning — so the `live`
  marker reached none of the 18 cases: a machine without an API key would fail with auth
  errors instead of skipping, and a machine with one would spend real money on a plain
  `pytest`. The marker is now applied in `pytest_collection_modifyitems`, and `addopts`
  deselects `live` by default so running the suite is a deliberate choice.
- **The quality judge randomised presentation order per vote**, which left roughly a
  quarter of three-vote runs sharing a single order — precisely the case where "position
  bias averages out" is false. Order now alternates deterministically.
- **Benchmark routing decisions drifted from the real path** by not stripping the
  `@agent` prefix before measuring, so its brief-length signal disagreed with production.
- **MCP integrations died on any fresh install.** `langchain-mcp-adapters` imports
  `mcp.shared.context.RequestContext` and declares no upper bound; mcp 2.0.0 removed
  that symbol, so a clean resolve took 2.0.0 and Jira, Confluence and Slack all failed
  at import. Found by running `my-crew doctor` in a cold-start venv, where the Slack
  probe reported an ImportError while advising the operator to go set Slack tokens —
  remediation that could never fix the cause. Now pinned `mcp<2`, with a test that
  asserts the declared constraint rather than the installed version, since the installed
  version is precisely the evidence that cannot see this class of bug.
- **Finishing the wizard could kill an unrelated running fleet.** The finish step
  kickstarted the `com.mpm.web` launchd job whenever the label existed, without checking
  the label referred to *this* process. Since the label names one installation, a second
  server on the same machine would finish its wizard and restart the installed service
  instead. Now compares the pid launchd reports against this process's parent chain; a
  hand-run server declines and returns a hint naming the manual path.
- **Binding a Telegram bot left team assignment still blocked.** Assigning work
  hard-blocks unless `telegram.ops_operator_id` is set and present in `chat_ids`, and
  the refusal told the operator to bind a bot — but the bind route never wrote that
  field, so following the instruction changed nothing and only hand-editing
  profile.yaml would clear it. Bind now defaults it to the first designated chat; an
  explicit value already in the profile still wins.
- **Saving a profile from the web scrambled its example comments.** ruamel folds a
  comment block directly following a `key: {}` line into that key's own token, so
  filling the key from the form rendered the new children *below* those lines and the
  commented-out `# inbox:` example read as if nested under `schedule`. The file still
  parsed identically, which is why no value-level test caught it — the damage was only
  to the human reading it. Tests now assert on rendered text, and a guard checks the
  shipped template for any patchable key followed by a comment line.
- **Self-check and peer review graded against drifted copies of the evidence rules.**
  Peer review was missing the countable-requirement rule and the original-ask ceiling,
  so it would pass a result whose criterion demanded a URL when the text only said
  "nguồn: X", and fail a result for missing something the CEO never asked for. The four
  rules now live in one constant both graders compose, with tests pinning the parity.
- **vitest was collecting Playwright specs.** The exclude list named e2e directories
  one by one, so each new one was silently collected until someone extended the list;
  it now matches by prefix. The advisor toggle had also borrowed the dry-run toggle's
  test-hook classname, making two specs strict-mode ambiguous — it has its own now.

## [0.13.0] — 2026-08-23

Everything the v88 web app could show but not touch is now actionable: a stalled task
can be unstuck from the board, an agent's profile and safety settings edited from its
page, and connections/company set up without hand-editing YAML. A live UAT of the ops
chat then surfaced three operational defects, all fixed here — including one that could
strand a task in a state no recovery action could clear.

### Added
- **One-click unstick for stalled tasks** (REST + UI): Retry / Accept / Drop on the
  dead step, plus Cancel for any live task, from both the Work board and the task
  detail page. A stuck task no longer has to detour through the coordinator chat.
  Drop and Cancel go through a confirm step; the backend's own message is surfaced
  verbatim rather than a canned string.
- **Agent profile and safety config forms**: edit `profile.yaml`, SOUL.md and
  PROJECT.md from the agent page. Writes are a comment-preserving round-trip patch
  (ruamel.yaml), so hand-written keys and comments in a profile survive a save that
  touches an unrelated field. MEMORY.md stays read-only — the agent writes it.
- **Connections, company and setup routes**: first-run configuration through the web
  app instead of hand-edited YAML, plus a cold-start integrity check.

### Fixed
- **A stalled task could hold a step no recovery action could clear.** When the
  coordinator retried a step and then gave up on it in the same decision sequence, the
  retry released the step's attempt lease while the give-up still guarded on it — so
  the terminal write silently matched no row and vanished. The task went `stalled`
  while its step stayed `pending`, a hybrid `retry_stalled_step` cannot rescue (it only
  looks for `failed`/`timeout` steps), leaving cancel as the only exit. Give-up now
  repairs the miss by terminating the step on its actual `pending` status.
- **Terminal step writes that match no row are now logged.** Every `mark_done` /
  `mark_failed` / `mark_needs_decision` / `mark_timeout` returns whether it updated a
  row, and that boolean was dropped at every call site — which is why the bug above
  went unnoticed. A write that concludes a step and silently hits nothing now warns.
- **History search returned nothing for ordinary multi-word questions.** A query whose
  words do not all co-occur now falls back to matching any word, with the results
  flagged as approximate. Asking "what did the team do last week" returned nothing
  before this and returns flagged results now.
- **Terminal-PIC repair and stall age**: a task whose PIC sits on an already-finished
  step is repaired in code rather than left for the coordinator to rediscover, and
  stall age is reported.
- **The frontend typecheck gate was checking nothing.** `tsc --noEmit` reads the empty
  root `tsconfig.json`, so it passed while `tsc -b` (what the build actually runs)
  failed on 15 errors. The gate is restored and the errors fixed; the shipped bundle,
  which had drifted 38 source files behind the committed dist, was rebuilt.

## [0.12.0] — 2026-08-19

The web app rebuilt around five hubs (v88): chat is now the home screen and the way
work gets assigned, the 3D office became an observation deck rather than the entry
point, and work/team/system each expose backend capability that previously had no
surface. Every pre-redesign URL still resolves. Backend changes are additive — a
fleet-wide approvals index, event provenance, and workroom read cursors — plus the
cold-start fixes an audit of a first-run install surfaced.

### Added
- **Five-hub web app** (v88): `Trò chuyện` (home) · `Văn phòng` · `Công việc` ·
  `Đội ngũ` · `Hệ thống`. Chat carries the conversation list, a folded event thread,
  a pending pane for approvals and agent questions, an on-demand artifact drawer with
  step transcripts, markdown milestone rendering, and the ops assistant as just
  another conversation. Work adds a task board with a detail funnel, schedule, and a
  shared approvals queue; Team adds inline hiring and an eight-tab agent page; System
  gathers settings, connections, company, metrics, and the audit log. Tab state lives
  in the URL, and ~21 redirects keep every pre-redesign URL working.
- **Cmd+K palette** over navigation, ops commands, and history search.
- **Phone layout** for the shell and the chat thread: a five-hub bottom bar, chrome
  folded into a `⋯` menu, and chat as two screens (list → conversation) with Back.
- **Fleet-wide pending-approvals index** (`GET /api/approvals/pending`): one call for
  every agent's queue, each row tagged with its owning agent. The queue is shown on
  more than one surface, which previously cost a per-agent fan-out per surface. One
  unreadable profile is skipped rather than blanking the whole queue.
- **Event provenance and read cursors**: office events carry `source_room_id`, and
  the workroom list joins each room's `last_seq` so a client can compute unread
  without a second round trip.
- **Operator escalation over email and webhook**: escalation tries Telegram, then SMTP
  (`OPERATOR_EMAIL`), then a webhook (`OPERATOR_WEBHOOK_URL`), and stops at the first
  channel that delivers. An agent with no channel configured is skipped rather than
  treated as a failure, so the caller keeps walking its list of agents instead of
  giving up on the first silent one. Measured on a real fleet before this change,
  7 of 11 agents could not be reached at all.
- **Web password change** from System → Settings. Changing the password also rotates
  `WEB_SESSION_SECRET`, which signs out every session including the one making the
  change — the point of changing a password you think someone else knows. Minimum
  6 characters, and it must differ from the current one.
- **Discarding a draft from the task board**: a previewed-but-unconfirmed plan can now
  be dismissed from its card in the planning column. Previously the only way to cancel
  one was the assign screen that created it, so a draft abandoned there was stranded.
- **Cold-start smoke script**: `scripts/cold-start-smoke.sh` builds the wheel, installs
  it into a clean environment, seeds an empty home, and serves it; `--browser` adds a
  real-browser pass over the login screen. It replaces the partial install check in CI.
- **Fleet-wide approvals ordering**: `GET /api/approvals/pending` returns oldest first
  across all agents. It previously followed the registry walk, which sorted by agent
  name — meaningless for a view whose only question is what has been waiting longest.

### Changed
- Advanced mode ("Chế độ nâng cao") no longer unlocks separate technical routes —
  every hub is always reachable. It now reveals technical detail inside a hub: the
  office health strip, the roster status column, and the artifact process tab.
- Chart.js loads on demand instead of riding in the entry bundle.

### Fixed
- **The first hire is reachable on a cold start.** A fresh install could reach a
  state where hiring was the necessary next step and no path led to it.
- **Resuming an agent clears the profile gate too.** Template hires are created
  `enabled: false` so tokens land in `.env` first; resume used to flip only the
  registry, leaving a button whose only remedy was hand-editing YAML.
- **A broken profile degrades instead of 500-ing.** The roster renders the agent id
  where a name would go (it used to render the exception text, putting an absolute
  filesystem path where a staff member belongs), and the detail route answers 200
  with `profile_error`. This now covers a `profile.yaml` that will not parse at all,
  not only one that parses into the wrong shape.
- **The assign block names the screen that unblocks it.** With no escalation route
  configured, assigning is refused with the path to fix it (Đội ngũ → coordinator →
  tab Kênh) instead of backend vocabulary.
- Internal links point at their real hub tab rather than bouncing through a redirect.

## [0.11.0] — 2026-08-18

Observability and engine sovereignty (v80–v86): every team-step attempt now leaves a
full transcript that review, the office feed, reflection, and the bench all read from
— and the react work tier runs on a self-owned thin tool loop that matches the
LangChain baseline's pass-rate at 3.5× fewer prompt tokens, 1.6× faster wall, with
exact (not estimated) cost. Verified by a 100%-thin stress across 5 hard live briefs:
blind judge PASS 10/10 answers, and the one real bug it surfaced (malformed provider
body killing a step) was fixed and pinned by test before this release.

### Added
- **Thin tool loop** (v86): self-owned tool-calling loop on the OpenAI SDK replaces
  LangChain `create_agent` as the react-tier default. Typed snake_case tool specs
  with a generic fallback so no tool in the map is ever dropped; wire rules for
  reasoning passback, empty-content, and invented-args (drop + echo); guards for
  truncated and verbatim-repeated tool batches; cost EXACT from OpenRouter usage
  extras. `loop_engine: langchain` in the profile keeps the old path as an A/B
  baseline — no profile migration needed.
- **Step transcripts + replay** (v80): per-attempt JSONL transcript (secret-scrubbed
  at write, best-effort — never kills a step), work-order artifact, and a
  `step-replay` CLI to re-run one step outside the pipeline. Four consumers on the
  same data: review grades process evidence (tools called, sources opened, usage),
  the office feed shows live step activity through a hard field allowlist,
  reflection receives tool names + counts only, and the bench decomposes usage
  per-step while the ledger stays the accounting source of truth.
- **Source integrity in review** (v83–v85): transcript evidence carries actual page
  content, and a source label must trace to a page the agent really opened; sprint
  opens the official pages between prefetch and draft.
- **Sprint prose lookup v2 + 4-axis release bench** (v81): prose entity extraction
  with angle rotation and dedup, query budget scaled to the brief; a release
  benchmark comparing candidate vs released on pass-rate, wall, cost, and tokens.
- **Tool-error accounting** (v86): five error classes (guard, invented tool, bad
  args, repeated batch, truncated batch) counted from transcripts — each tool result
  at most one class — and surfaced in bench task metrics.
- **Web UI** (v82): lazy data layer, sprint surfaces on the office UI, SSE cold-tail
  replay and collapsed repeat rows in the activity feed; assigned-tasks board retired.

### Changed
- Rework steps get fresh search context, the best draft survives retry exhaustion,
  and an unreachable reassign degrades to a guided retry instead of dead-ending.

### Fixed
- A provider returning HTTP 200 with a malformed JSON body no longer kills the step:
  the parse error is retried with backoff, and on exhaustion advances the model
  fallback chain like any other provider fault.
- Review evidence is no longer trimmed to tool-result size, and transcript evidence
  resolves from the graded assignee's agent jail instead of the top-level path.

## [0.10.0] — 2026-08-16

Sprint mode and the routing funnel (v76–v79): a one-person brief no longer pays the
multi-agent tax. The router defaults to a single code-paced agent and only escalates
to a team on structural signals — measured 3.6–7× faster and ~4× cheaper on the same
briefs, winning 4 of 5 blind-graded pairs. Cost caps became a real brake (running
steps halt on breach), autonomy got per-agent bands with a closed metrics loop, and
the release gate ran live end-to-end: 4/4 delta behaviors verified on real models and
real Telegram, with both cosmetic findings fixed before tagging.

### Added
- **Sprint mode** (v77): one-person briefs run as a single code-paced agent —
  prefetch (code picks queries) → draft (LLM) → coverage check (code) → targeted
  revise (≤2 rounds). A degenerate team task, so review/clarify/escalate/delivery
  are inherited, not reimplemented. `sprint:` / `team:` prefixes override the router;
  external writes, shell, multi-person, and long-running briefs cannot be forced into
  sprint. Benchmarked 3.6–7× faster, 4.1× cheaper, blind-graded 28 vs 8 on the
  flagship pair.
- **Routing funnel, 6 layers** (v78): default is sprint; structural signals push to
  team (>1200 chars, >10 entities, ≥3 separate asks) — keywords are not trusted.
  After decompose, a degenerate plan (≤2 steps, 1 person, linear, no shell/egress)
  is pulled back to sprint at zero extra model calls; a sprint that dead-ends flips
  to team with the original ruling preserved. Every branch logs `route_json`
  (mode/source/reason/signals — metrics only, never the brief text).
- **Three-tier model config** (v79): fleet → per-agent → per-role (`role_models`);
  fleet default is now `deepseek/deepseek-v4-pro-0813`.
- **Review budget + in-flight brake** (v78–79): per-task review/rework cap (2× content
  steps, floor 5) — on breach the task stalls and escalates instead of burning money;
  the cost cap now halts steps already running (v78 measured cancel leaking ~$0.05:
  it flipped status but never stopped spawned workers). Sprint always mints exactly
  one review in every trust band — the zero-eyes path is closed.
- **Autonomy bands + honest metrics** (v76): per-agent trusted/normal/supervised
  bands driven by a closed loop over asymmetric metrics (a false "done" costs more
  than a false stall); audit log hash-chain, gateway fail-mode contract, and
  break-glass procedure.
- **Full-flow test harness**: the whole intake→decompose→work→review→aggregate
  pipeline runs in-process against a scripted LLM; 8 real-user scenarios including
  clarify, autopilot, and sprint paths, mutation-verified
  (`docs/fullflow-testing-guide.md`).
- **Repeatable speed benchmark** for sprint vs team modes (`scripts`-level tooling
  behind the v77/v78 numbers).

### Changed
- Web-bound steps must carry a data-freshness acceptance criterion: prefer the newest
  figures found, note the source's own stated data date when it is old — but never
  reject old figures when no newer source exists (snippet-compatible on purpose).
- The terminal step's artifact is delivered verbatim to the CEO — no 500-char
  summary, no rewrite layer; single-terminal plans deliver the artifact itself.
- Terminal steps are identified from content-step dependencies only, so a
  dynamically inserted review row is never mistaken for the deliverable artifact.

### Fixed
- A tool-less sprint (`needs_web=false`) no longer runs its doomed prefetch and no
  longer ships a "could not search the web" disclaimer about a lookup it never needed.
- Peer review traces figures back to the step's actual input instead of grading
  blind; a passed verdict hands the prior output on untouched (no rework-appendix
  leaking into user-facing text).
- Post-completion Telegram flood stopped: done is announced once, direct delivery
  and the milestone mirror can no longer both fire.
- Rework steps inherit the web grant of the step they redo.
- Runtime split after a stuck reassign re-stamps the plan hash with the conditional
  flags, so confirmed plans stay confirmable.

## [0.9.0] — 2026-08-09

Speed and proactive coordination (v70–v75): the same multi-agent survey task that took
~40 minutes now finishes in 11–16 at a third of the cost, and a stalled task no longer
just waits for the human — the coordinator retries, proposes a DIFFERENT plan through
the amendment flow, then falls back to accept/drop, all bounded and audited. Verified
across 12 live end-to-end rounds (real web data, real Telegram) with the honesty chain
intact: no fabricated numbers, gaps reported as THIẾU with the correct reason.

### Added
- **Personal assistant pong** (v70–v71): a second personal-pack agent with its own
  Telegram bot — morning briefing (07:00) and Sunday weekly review (08:00) reading
  Goodreads RSS + Google Tasks; profile-only `goodreads_user_id` (deliberately no env
  fallback — a bookshelf belongs to one person). Quick-build crew templates.
- **Per-step tier routing `needs_web`** (v74): the decomposer marks which steps need
  live web lookup; tool-less work (grading, synthesis, rework briefs) runs the
  one-shot native tier instead of a heavy tool loop — measured 64% of wall-clock
  before the change. A wrong hint self-heals after the first coordinator ruling. The
  flag is carried by all three step-minting paths (decompose, runtime split, amend)
  and conditionally hash-bound like `needs_shell`.
- **Event-driven dispatch** (v74): team-step workers, door-opening tick actions, task
  confirm, and row minting all touch a poke file; the service sleeps in 5s slices and
  runs the next coordinator tick early. Dispatch gaps fell from ~253s per task to
  0–8s per step; the 60s cadence stays as the fallback, so a lost poke costs latency,
  never work.
- **Entity fan-out, code-enforced** (v74–75): a brief listing 4+ same-kind entities
  must split collection into parallel dep-less steps — first a prompt rule, then a
  validator (`fanout_gap`) feeding the existing decompose retry loop, fail-open on
  the last attempt so a slow plan still beats a failed assign.
- **Goal-directed replan** (v75): autopilot ladder rung 2 — a stalled task whose plan
  is the problem gets ONE amend-LLM proposal for a different approach on the pending
  tail, through the exact CEO amendment flow (frozen prefix, hash-guarded confirm).
  Fail-closed: model failure or an identity proposal refuses and the stall stands.
- **Hybrid collect launcher** (v75): code prefetches 1–3 searches (per-entity query
  variants, no LLM) and injects the bundle so collect steps run native — measured
  119s vs 199–425s on the tool loop. Fail-open to the old path.
- **Search 3-path sentinels** (v75): "the web says nothing" and "we never reached the
  web" are now different answers on both tiers (`web_search_outcome`); a watcher tick
  where every poll failed reports `all_polls_failed`, never `no_change`.
- **Transcript salvage** (v74.1): a tool loop that exhausts its budget synthesizes an
  honest answer from the partial transcript (gaps marked THIẾU) instead of returning
  empty.

### Changed
- Fleet default model → `qwen/qwen3.7-plus`; graders are date-anchored and capped by
  the CEO's original ask (inflated acceptance criteria no longer fail honest work).
- First stuck ruling always retries with guidance before any reassign; reassignment
  and dead-step resets check actual tool capability (web flag + sandbox network).
- All CEO-facing Telegram messages route to the assigning bot's chat (coordinator-
  first), with the admin bot as fallback only; task-done sends once with a workroom
  link (`MPM_WEB_BASE_URL`).
- Weekly review no longer re-greets or repeats the same-morning briefing items.
- `team_task_concurrency` semantics documented (per-task cap, no per-agent
  single-flight); default stays 2, per-install tuning supported.

### Fixed
- Runtime-split subs inherit the parent's `needs_web` (flagless subs were forced onto
  the searchless tier, each burning a coordinator ruling to recover).
- Routing flags must live in every prompt's EXAMPLE schema — prose alone is mirrored
  away by the model; fixed in decompose and amend, pinned by tests.
- Redo/reassign clears the step's checkpoint thread so a retry cannot resume past its
  guidance; duplicate ✅ messages after task completion removed (`delivered_direct`
  survives the PII projection).

## [0.8.0] — 2026-08-05

Disciplined autonomy (v67–v69): 0.7.0 let the AI approve its own work; this release
makes the human's remaining approvals actually reachable. A Lớp B action used to wait
in a web banner nobody had open. Now queuing it pushes a Telegram notice, the CEO
approves or rejects from the same chat, and a standing rule can retire the question —
while the heartbeat keeps naming anyone still blocked.

### Added
- **Approval push**: queuing a Lớp B action DMs the operator with the id, the agent,
  and one identifying line. Content is identity-only — recipients, tool name, argv
  prefix — never subjects or bodies, with newlines collapsed so a crafted value cannot
  paint a fake line beside the confirm prompt.
- **Approve/reject from chat** (admin-only — these reach into other agents' stores, so
  they are fleet authority, not orchestration): a third surface on the same gateway
  path, not a second approval road. The `(agent_id, approval_id)` pair binds at preview
  and is never re-resolved, so a push landing mid-conversation cannot move the target.
- **Learned approval rules**: an always/deny rule for the action type, described in
  words translated from the binding actually computed — never as a params hash, since
  consenting to a blind digest is consenting blind. An action chat cannot summarize
  refuses a standing rule outright. Deny rules apply only in `guarded` trust mode.
- **Blocked approvals in the heartbeat digest** (fifth signal): every pending row
  across every enabled agent, reported regardless of age, and exempt from model
  suppression — a pending approval means an agent has stopped, and only this human can
  unblock it.
- **`list_lessons`**: shows the CEO what the coordinator learned from finished work,
  which until now was written and never read back.
- **Task revival count** in `list_team_tasks`: a task the CEO had to retry after a
  stall reported the same step counts as one that ran straight through.

### Changed
- `ApprovalStore` moves to WAL with a 30s busy timeout. With three surfaces writing one
  queue, the default rollback journal raised "database is locked" immediately — worst
  of all in `approve()`'s revert-to-pending after a handler failure, which could strand
  a row in `approved` for an action that never ran. Existing databases upgrade in place.
- The reflection pass tags each lesson at the write site, so lessons can be told apart
  from the ordinary facts that share their namespace and shape. Lessons written before
  the tag do not appear in `list_lessons`; the set refills itself as tasks finish.

### Fixed
- **Reject is now compare-and-set on every surface.** A blind reject could land on a row
  another surface had already approved and executed, leaving the store claiming
  "rejected" for an action that really ran — and teaching a standing deny rule from that
  phantom decision. Each caller now reports the lost race instead of claiming a decision
  it did not make.
- An `approvals.db` holding only the learned-rules table (the rule store creates the
  same file) no longer reads as an error. An agent in that state simply holds no
  approvals; raising took the whole fleet's approvals signal down permanently, across
  both the digest and the chat list that share the reader.
- The reflection cooldown marker is keyed by task generation, so a revived task can be
  reflected on again instead of being permanently silenced by its first attempt.

## [0.7.0] — 2026-08-04

The secretary arc (v57–v66): my-crew grows from "a company you watch work" into "a
company you run from one chat". A personal secretary agent in Telegram becomes the
operating surface for both the CEO's personal work and the whole team — and the final
approver can now be the AI itself.

### Added
- **Personal secretary domain pack** (5th pack, `personal`): instant DM chat, morning
  and weekly briefings, Gmail/Calendar read, multi-recipient email send, calendar
  create/update/delete (a deliberate, narrow Lớp A carve-out), and multi-command
  messages ("gửi mail cho X rồi đặt lịch 3h").
- **Timed reminders**: "nhắc anh 15h gọi X" → actor-bound native reminder actions, a
  per-agent reminders store, and a cap-exempt per-minute sweep that DMs Telegram at
  the exact minute; cancel by id.
- **Chat as orchestration gateway**: the secretary dispatches team tasks (LLM
  decomposes, code validates the DAG), adjusts or cancels them mid-flight, and reads
  the team kanban with costs — all in natural Vietnamese over Telegram. The ops
  catalog is domain-scoped: coordination is not fleet admin, so a secretary can
  never see `create_agent`.
- **Autopilot** (`company.yaml::autopilot`): the AI is the final approver — plans
  auto-confirm, stalled tasks auto-resolve on a two-step ladder, Lớp B writes
  auto-approve. Per-task opt-out ("để anh duyệt"). Lớp A and cost caps stay
  human-only (pinned by tests).
- **Cross-agent persistent memory**: the memory store defaults to shared SQLite —
  facts survive restarts and are readable across teammates; `memory_share:
  full|read_only` per profile (the secretary is read-only, so the CEO's private
  context never leaks into team output); 90-day retention in the sweep.
- **Sandboxed real code execution**: `needs_shell` steps run in a hardened Docker
  container (no host mount, tmpfs workdir, scrubbed env, network off unless opted
  in, fail-closed without Docker) — proven exfil-proof by an adversarial UAT round
  that tried to read `.env` through a delegated task.

### Changed
- **Risk-tiered peer review**: only terminal steps and external writes are reviewed
  (small tasks get a waiver) — ends the failure mode where a 5-step task exploded
  into 20+ review rounds and stalled.
- **Fair scheduler**: stateless round-robin across agents each tick; exact-time
  kinds (reminder sweep) are exempt from the per-tick cap.
- **English-only backend identifiers** (ids, keys, functions); Vietnamese remains in
  the user-facing layer. Fleet agents renamed accordingly.
- Backend suite grew 2392 → 2530 tests across the arc.

### Fixed
- Three adversarial UAT rounds of hardening: the ops layer no longer shadows the
  personal catalog (unsupported command-like messages fall through to the agent's
  own commands); reminder synonyms route to `cancel_reminder` instead of the
  team-task cancel; a mid-collection change of mind re-classifies the message
  instead of stuffing the whole sentence into a slot; stalled-task previews
  validate the task id before promising anything; numeric JSON slot values coerce
  to strings; a dropped step's placeholder forbids downstream agents from
  fabricating its data; and the persistent-memory store is actually wired into
  graph compile (machinery existed since v2 but had never carried current — found
  only by live UAT).

## [0.6.0] — 2026-08-01

Hardening round: browser-measured layout tests plus three small usability/hygiene
fixes surfaced by the post-0.5.0 roadmap review.

### Added
- **Playwright smoke suite** (`web/e2e/`, `npm run test:e2e`, CI job `frontend-e2e`):
  8 DOM-measurement tests pin the office cockpit layout (page never scrolls, every
  zone scrolls internally, composer always visible, overlays never push the grid,
  ×N watch-run grouping, filter/search, live results-dot, mobile stack). The whole
  /api surface is mocked inside the browser — secret-free, no backend needed.
- **Assign-time web-search warning**: when the previewed PIC has `web_search: true`
  but the machine has no search-provider key, the plan preview shows a notice that
  the agent will work internal-only (the profile flag is never auto-disabled).
  `/api/office/assign/staff` now carries `web_search_ready` (presence-only) and a
  per-staff `web_search` opt-in flag.
- **Artifact drawer a11y**: a shared focus trap (Tab wraps inside the drawer, focus
  returns to the opener on close) and error lines that show `HTTP <status>` plus the
  backend's `detail` — GET requests now surface backend detail the way writes always did.

### Changed
- The retention sweep now deletes orphan artifact directories (no task row AND older
  than 7 days, confined to the team-tasks artifact root); fresh orphans stay visible
  to the read-only integrity audit as a bug signal.

### Fixed
- The results-tab ● dot no longer lights up from a room's replayed history (it armed
  on old handoffs because the SSE replay lands after the render-time baseline was
  captured, and the overview collided with the baseline's null sentinel — caught by
  real-data UAT, the 4th fix of this dot). "Live" is now the event's own timestamp
  versus room-open time, and the overview never dots.
- The v36 integrity audit's artifact-orphan check scanned a directory nothing writes
  to and has been silently reporting "clean" since v36 — both it and the new sweep
  now share the writers' real path helper.

## [0.5.0] — 2026-08-01

Office cockpit shell: the office screen becomes a single fixed viewport — the CEO never
scrolls the page again.

### Added
- **Assign command bar on top**: the composer moved from the page bottom to directly
  under the header, styled as the screen's primary action (label, filled button). Its
  @-mention dropdown and plan preview render as overlays, so opening them never pushes
  the three columns down.
- **Workroom list controls**: status-filter chips [● running | ⚠ stalled | ✓ done]
  (done off by default — finished rooms are history), a title search that intentionally
  ignores the status filter, and recurring same-title runs (watch tasks) collapsed into
  one expandable "×N" row. Deep-linking `?room=<id>` to a filtered-out or collapsed room
  force-shows it and auto-expands its group.
- **Right-column tabs [Workrooms | Results]**: each tab gets the whole column height;
  a ● dot on the Results tab marks a handoff delivered live while the tab wasn't open.

### Changed
- The whole office screen is one 100dvh cockpit: every zone (action rail, activity feed,
  rooms/results) scrolls internally and the page itself never scrolls. Scoped via CSS
  `:has()` — other views are untouched; browsers without it keep the old document flow.
  The app shell widens to 1600px on this screen (was capped at 1100px).
- The 3D office panel shares the center column height (flex, 140px floor) instead of
  claiming a fixed slice, so the feed keeps a usable window on short screens.
- Architecture model (C4-style) and its drift-check board are committed under `docs/`.

### Fixed
- The Results-tab dot now arms on the first live handoff of a brand-new room (two
  earlier guards swallowed it; caught by live UAT with a real fleet, not by the suite).

## [0.4.0] — 2026-07-19

Office cockpit: the 3D office becomes the place the CEO acts from, not just watches.

### Added
- **Action rail** (left column): pending approvals and clarify questions from the whole
  fleet merge into one "waiting on you" queue — approve/reject and answer questions in
  place, through the existing write paths, without leaving the office. Below it, "Sắp
  chạy" lists the fleet's next scheduled runs (`GET /api/schedule/upcoming`).
- **Outward-action feed**: the activity feed gains a [All | Steps | External] filter;
  "External" surfaces the Action Gateway's real-world writes (agent → tool → outcome),
  bridged from the gateway's single audit choke point — identifier-only targets, never
  message content.
- **Review detail tray**: clicking a review line shows each acceptance criterion with a
  pass/fail mark and note. Per-criterion results are now persisted
  (`captures.criteria_json`, exposed only on the capture detail endpoint).
- **3D desk cues**: a ✋ badge on desks (and the coordinator table) with something waiting
  on you, a ×N badge when an agent runs steps in parallel, and a translucent ghost figure
  while a deep_team step is delegating in its sandbox.
- Per-workroom cost chip (lazy) and a mobile single-column stacking of the cockpit.

## [0.3.0] — 2026-07-19

UI discipline + a Vietnamese/English language mode for the dashboard.

### Added
- **Language toggle (VN/EN)** in the header, next to the theme and lens toggles.
  Every static interface string switches; backend-origin messages (health checks,
  API errors) and LLM-authored content stay Vietnamese, and technical terms
  (Captures, Guardrail, PIC, deep_agent, engine, tokens…) stay English in both. Zero
  external i18n library — a typed dictionary where a missing translation is a compile
  error.
- **Shared UI primitives** (Button, Card, Badge, Input, EmptyState, PageHeader) so
  every screen draws buttons, cards, badges, and headers from one place; the
  stylesheet gained a section structure and a rule against ad-hoc component classes.

### Changed
- One cost format app-wide (4 decimals under $1, 2 from $1) and one timestamp format.

### Fixed
- The office error-state colour now inverts correctly in dark mode (was pinned to a
  literal); mobile header no longer overflows once the language chip is present.

## [0.2.0] — 2026-07-18

Office dual-lens: one office screen serving both the CEO (normal) and the maintainer
(technical) through a header lens toggle.

### Added
- **Failure & review visuals** in the 3D office: a failed step now paints a red desk +
  ⚠ bubble (previously it silently went idle); a peer-review verdict flashes a floor
  ring (green passed / orange needs-rework).
- **Technical mode** (👁/🔬 header toggle): sandbox-tier 🔒 badges, a health strip
  (coordinator heartbeat + integration checks + fleet budget), a Desk Inspector drawer
  (step, engine tier, cost-so-far), a **Captures** telemetry explorer, and a full-text
  **history search** box. Mode is view-layer only — never a permission gate.
- Read-only observability API: `GET /api/budget`, `/api/captures` (+ `/{id}`),
  `/api/search`.

### Fixed
- launchd services now get a PATH that includes Homebrew + Docker dirs, so the
  coordinator's workers, the MCP watchers, and the deep_agent sandbox find
  `node`/`docker`/`gh`/`gws` (regression from the v0.1.0 `src`→`my_crew` rename).
- A superseded worker's late `failed` event no longer paints a false red desk over a
  live retry (the office event now carries its `attempt_id`).

## [0.1.0] — 2026-07-18

First installable release. Everything below existed as a clone-and-run system built
across v1–v50 (see journals); 0.1.0 packages it as a product.

### Added
- `my-crew` console script (PyPI package `my-crew`): `--help`, `--version`, and the
  full command surface — `quickstart`, `crew init`, `serve`, `doctor`, `upgrade`,
  `agent *`, `web hash-password`, `sandbox prepull`.
- `my-crew serve`: foreground web + coordinator supervisor for Docker Compose,
  systemd, or a plain terminal. `deploy/docker/` ships a Dockerfile + compose file.
- `MY_CREW_HOME`: user state (.env, registry, profiles, data) resolves to the env
  var, else the git checkout, else `~/.my-crew`. Shipped starter profiles seed into
  a fresh home on first run.
- The wheel bundles the web dashboard (no Node needed to install) and the shipped
  resources (starter profiles, templates, domain packs, examples).
- GitHub Actions CI (secret-free test suite, ubuntu + macos) and an OIDC-based
  PyPI release pipeline.

### Core (pre-0.1.0, summarized)
- Autonomy-first agent harness on LangGraph: every write flows through the Action
  Gateway — hard-coded red lines (Lớp A), autonomous-vs-guarded trust modes,
  kill-switch, dry-run default, dedup, rate-limit, immutable audit log.
- Multi-agent virtual office: browser dashboard + 3D office, one-click staff
  templates, chat-ops, team tasks with review steps, per-task cost tracking.
- Integrations via MCP: Jira, Confluence, Slack (+ GitHub via `gh`), layered
  memory, budget caps, scheduler with per-agent cron.

### Known limitations
- The `deep` sandbox tier (`pip install my-crew[deep]`) needs a Docker daemon and
  is not available *inside* the provided container image.
- The 3 MCP servers require Node at runtime (prepulled in the Docker image;
  installed by `deploy/install.sh` on native installs).
