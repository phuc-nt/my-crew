# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: semver.
Development history at finer grain lives in [docs/journals/](docs/journals/).

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
