# Daily Operations Guide

> **For Vietnamese operators:** [huong-dan-su-dung.md](huong-dan-su-dung.md) is the day-to-day canonical reference.
>
> Dashboard and team operations for CEO / team leads (no technical knowledge required).
> All work via browser dashboard or Telegram.
> **Updated:** 2026-08-16 (v79 / 0.10.0).

---

## What's new since v57 — the personal secretary & autopilot

Since v57 the primary operating surface is **chatting with a personal secretary agent
on Telegram** (create one via the Assistant: agent role `personal`); the dashboard
becomes the observation room. In one DM you can:

- **Personal work**: morning/weekly briefings, read Gmail/Calendar, send email, create/
  edit/delete calendar events, exact-time reminders ("nhắc anh 15h gọi X" → Telegram
  pings at 15:00), multiple commands in one message.
- **Team work**: assign a brief (decomposed into a validated multi-agent plan you
  confirm), adjust or cancel mid-flight, view the kanban with costs, one-touch stall
  recovery (accept / one retry / drop dead steps).
- **Autopilot** (`company.yaml: autopilot: true`, default false): the AI becomes the
  final approver — plans auto-confirm, stalls auto-resolve, routine Lớp B writes
  auto-approve, each decision reported back and audited. Say "để anh duyệt" when
  assigning to keep a specific task human-gated. Lớp A hard-denies and cost caps
  never change.
- **Team memory** (v66): facts persist in a shared store across restarts and agents;
  the secretary is read-only so your private context never leaks into team output.
- **Secretary heartbeat** (v68, opt-in): secretary checks for stalled tasks, failed deliveries, 
  due reminders, and stuck drafts on a schedule you set. When there's something to report, 
  one Telegram DM arrives; when quiet, nothing sends (zero cost when idle). Configure per-agent 
  via `heartbeat.every: 30m` (or `1h`, `2h`, etc.) in the agent's profile.yaml. Defers if you're 
  mid-conversation or the secretary is already running (no interruption).
- **Approvals in chat** (v69 / 0.8.0): when a guarded action queues, you get a Telegram
  DM immediately (id + agent + one identifying line — never the message body). Approve or
  reject right in the chat, optionally as a standing always/deny rule described in plain
  words. The heartbeat also names every approval still waiting, so a blocked agent can't
  wait unnoticed. Plus: "xem bài học" shows what the coordinator learned from finished
  tasks, and the kanban reports how often a task had to be revived.

- **Personal assistant "pong"** (v70–71 / 0.8.0+): a second personal agent with its own
  Telegram bot — 07:00 morning briefing and Sunday 08:00 weekly review reading your
  Goodreads shelf + Google Tasks. The weekly review summarizes the week and next-week
  priorities without repeating that morning's briefing.
- **Faster teams, same honesty** (v72–75 / 0.9.0): a 5-6-entity survey brief now
  finishes in ~11–16 minutes (was ~40) at $0.02–0.05 — steps dispatch within seconds
  of the previous one finishing, collection splits into parallel steps automatically,
  and data lookups are pre-fetched by code where possible. Nothing changes in what you
  see except speed; missing data is still reported as THIẾU with the true reason
  (source unreachable vs data doesn't exist are now distinguished).
- **Smarter stall recovery** (v75 / 0.9.0): under autopilot, a stuck task now climbs a
  3-rung ladder — retry, then propose a DIFFERENT plan for the remaining steps (you
  see the diff, every change goes through the same amendment flow), then accept/drop.
  Off autopilot everything still waits for you.
- **Sprint by default + spend guardrails** (v77–79 / 0.10.0): a one-person brief now
  runs as a **sprint** — one agent, single pass, measured 3.6–7× faster and ~4× cheaper
  than the team plan on the same briefs, always with exactly one peer review (see
  Sprint Mode, below). A task that keeps failing review now **stalls and escalates to
  you** instead of burning budget (cap: 2× the number of content steps, floor 5); the
  cost cap now **halts steps already running**, not just future ones; "done" is
  announced **exactly once** per task; and web research carries a **data-freshness
  rule** — newest figures preferred, and when only an older source exists its data
  date is noted next to the figure.

Details (Vietnamese): [huong-dan-su-dung.md — Phần C](huong-dan-su-dung.md).

---

## Opening the Dashboard

After setup, access the web interface at `http://127.0.0.1:8765` (or your deployed URL). Log in with the password set during Setup Wizard.

---

## The 5 Hubs

The navigation bar has 5 primary hubs (plus Settings):

| Hub | URL | Purpose |
|---|---|---|
| **Chat** | `/chat` | HOME: conversation list + message thread. Assign work, chat with the assistant or a workroom (`/chat/:roomId`), view artifacts inline. |
| **Office** | `/office` | Real-time 3D workspace: watch team desks, pending approvals, upcoming schedule, activity feed. |
| **Work** | `/work` | Approvals + clarify queue (always on top) over 4 tabs: board, outputs, schedule, activity. |
| **Team** | `/team` | Agent roster: status, budget, enable/disable/delete. Click agent → 8 tabs (profile, activity, knowledge, skills, channels, budget, memory, advanced). Create new agents. |
| **System** | `/system` | Fleet settings, connections, company info, audit log. Tabs: settings, connections, company, insights, audit. |

---

## Assigning Work to the Team

**Quickest way:** Go to **Chat** (home hub) and type in the message box.

### Three Assignment Styles

**Option 1: Assign to a specific agent (PIC)**

```
@agent-name do this task
```

When you type `@`, a dropdown shows all available agents. The named agent becomes **PIC (Primary in Charge)** and handles the final step; other team members contribute specialist steps as needed.

**Option 2: Let the team choose the PIC**

```
@all write the proposal
```

or just skip the `@` entirely. The system suggests which agent is best suited and shows you the plan before you confirm.

**Option 3: Detailed conversation (via Chat)**

Type your request in **Chat** → answer questions step-by-step → the assistant creates the task, which then shows up on the **Work** board.

### Sprint Mode — One Agent, Start to Finish (v77, default since v78)

Not every task needs the whole team. A research brief like *"compare 5 tools across 3
criteria"* used to be split into 5 steps, each handed to a different agent, each starting
cold — **tens of minutes**. Such a brief now goes to **one agent to finish in a single
pass** (a **sprint**): measured at **3–9 minutes** on briefs that took the team 23–31
minutes, at roughly a quarter of the cost.

Since v78 **sprint is the default**: a brief goes to a full team plan only on
**structural signals** — longer than 1200 characters, more than 10 listed entities, or
3+ separate asks on separate (bulleted/numbered) lines. Routing self-corrects in both
directions: a team plan that turns out to be one person's job is pulled back to sprint,
and a sprint that hits a dead end **automatically re-routes to a team plan** — you never
have to re-assign.

You don't have to do anything — assignment picks the mode for you. To force it:

| Type | Result |
|---|---|
| `sprint: compare 5 note-taking tools…` | force one agent, single pass |
| `team: compare 5 note-taking tools…` | force the usual multi-step team plan |
| (no prefix) | **sprint by default**; team only on the structural signals above |

The prefix chooses the **mode**, not the safety rails. These four kinds of work **always**
go to team mode even with `sprint:`, because they need review rounds a sprint doesn't run:

- writing **outside the company** (sending mail, publishing, updating a website…)
- work that **needs a shell / code execution**
- work you explicitly said **needs several people**
- **long, multi-stage** work

A sprint task still gets its own workroom, **exactly one peer review** (in every trust
band — there is no zero-review path), clarification questions when it hits a dead end,
and the usual Telegram milestones — it just runs in one continuous pass.

### Reviewing the Plan

After you type a task, the system:

1. Breaks it into up to 7 steps.
2. Shows you the **plan** (who does what, in what order, estimated cost).
3. Displays the **PIC** (person responsible for the final handoff).
4. Waits for your **"Confirm"** or **"Cancel"**.

In **Chat**, you see the plan preview. The 3D workspace in **Office** shows the PIC's desk with a **⭐** and **PIC** label. You can refine the plan in **Chat** if needed (see Replan, below).

### Workrooms

Each assigned task opens a **workroom** — a dedicated space for that task. Workrooms are listed in **Office** screen on the right:

- **●** = task in progress
- **⚠** = task stuck
- **✓** = task completed

Click a workroom to enter and view activity + artifacts. You can also chat within the workroom and:

- **Ask for status update** ("how's it going?") — agent responds in real-time (response is not saved to history).
- **Tweak the plan mid-execution** ("drop the final review step" / "add image verification") — see the DIFF before applying.
- **Assign sub-tasks to stay in the same workroom** ("now do X").

---

## Approvals & Trust Modes

### Two Types of Queued Work

**Work hub → top queue** (always visible above kanban)

| Type | Source | Action |
|---|---|---|
| **Actions from guarded agents** | Agent set to `trust_mode: guarded` | Awaits your approval before executing. |
| **Clarification questions** | Task step hit a dead end | Answer in-place, no re-draft needed. |

### Autonomous vs. Guarded

**Autonomous (default):** Actions sent outside the company (post to Slack, merge PR, close Jira ticket) **run immediately** and appear in the audit log. No approval needed.

**Guarded (opt-in per agent):** Same actions **queue for approval**. You click "Approve" or "Reject" in the **Approvals** tab.

> **Hard-deny actions (Lớp A):** Actions that could lose data permanently (delete records, expose secrets) are **never allowed**, even if guarded. See [action-gateway-explainer.md](action-gateway-explainer.md).

**To switch an agent to guarded:**

1. Go to **Team** → click agent name.
2. In the **🔬 Nâng cao** tab, edit YAML and add:
   ```yaml
   safety:
     trust_mode: guarded
   ```
3. Save. Agent becomes guarded immediately on next task.

### Learning Rules from Approvals (v67+)

When you **Approve** or **Reject** a guarded action, you can teach the system to auto-decide the **same action** next time:

**In the Work hub queue:**
- Click **Approve** → optionally check **"Always approve this type"** (or use CLI `--always` flag)
- Click **Reject** → optionally check **"Always reject this type"** (or use CLI `--deny` flag)

**What "this type" means:**
- An action is identified by its tool + destination (e.g. "post to #random channel", "comment on Linear issue ABC-123")
- If the destination changes (different channel, different issue), the system **re-asks** you (no rule mismatch)
- Internal actions (team tasks, scheduling) apply to any parameter (**no destination binding**)

**Important:** Rules **only work in guarded mode**. In autonomous mode, actions always run immediately.

**Via CLI** (for automation or scripting):
```bash
mpm agent approve <agent-id> <approval-id> --always    # learn to auto-approve
mpm agent reject <agent-id> <approval-id> --deny       # learn to auto-deny
mpm agent rules <agent-id>                              # list learned rules (shows rule ID, type, usage count)
mpm agent rules <agent-id> --revoke <rule-id>          # undo (deny rules need --confirm to prevent accidental loosening)
```

### Approving from Telegram (v69+)

Chat is the third surface on the same approval queue — same gateway path as web and CLI,
available only in the **admin agent's** chat (deciding for other agents is fleet
authority, so the personal secretary can't do it).

**You don't have to poll:** the moment a guarded action queues, the operator gets a DM
with the approval id, the agent, and one identifying line (recipients and tool name —
never the subject or body). From there, in natural language:

- *"xem việc chờ duyệt"* — list every pending approval across all agents
- *"duyệt việc #12 của sales-pm"* — preview first, then confirm; answer *"luôn"* to also
  learn an always-approve rule
- *"từ chối #12 của sales-pm"* — answer *"chặn"* to learn a standing deny rule

Two safety properties worth knowing:

- The preview pins the exact `(agent, approval id)` pair — if another notification lands
  mid-conversation, your confirm still targets the row you saw, or tells you it's gone.
- A standing rule is only offered when the action can be described in plain words
  ("always allow posting to #general"). If the system can't describe what the rule would
  cover, it refuses the "always/chặn" option — approving a rule you can't read isn't
  consent. Rule list/revoke stays on CLI/web.

If a pending approval sits unattended, the secretary heartbeat (below) names it on every
configured check-in until someone decides — a blocked agent can't wait unnoticed.

---

## Team Management

### View Team Status

**Team** hub shows all agents with:

- **Status** (idle / working / errored)
- **Budget spent** this cycle
- **Any stuck tasks** (⚠)

Click an agent to see 8 tabs: profile, activity, knowledge, skills, channels, budget, memory, advanced.

### Create a New Agent

**Option 1: One-click templates** (fastest)

Go to **Team** → click **"+ Create virtual agent"** → pick a template card (6 roles: Team Lead, Research, Content, Analytics, Verification, PM-Coordinator) → click **"Create now"** → done. Agents start **disabled**. Enable them after setting up credentials (if needed) in the agent detail page.

Templates auto-load their skills at runtime, so updating a template skill instantly affects all agents using it.

**Option 2: Crew creation** (bulk)

Go to **Team** → click **"+ Create full crew"** → system creates all 5 template agents at once (shows which ones already exist) → confirm → all created independently (if 1 fails, others still created).

**Option 3: Custom via chat**

Go to **Chat** → ask "create an agent that…" → answer questions → assistant creates it and turns it on immediately.

### Manage Agents

**Team** hub has each agent card:

- **Pause an agent** → toggle off (stops receiving new work; in-flight work completes).
- **Delete an agent** → click delete (can recreate from template anytime).
- **Upgrade agent config** — when a template updates:
  1. Agent card shows **"⬆ new vN"** badge.
  2. Click it → see what will change.
  3. **"Upgrade"** applies new config (fields you customized stay yours); **old profile auto-backed up**.

### Secretary Heartbeat (v68+, Optional)

If you use a personal secretary agent, you can enable periodic check-ins to stay informed without constant 
manual polling. The secretary monitors:

- **Stalled team tasks** (awaiting your input to recover)
- **Failed deliveries** (external writes that couldn't send)
- **Reminders coming due** (within 24 hours)
- **Awaiting-confirmation drafts** (overdue for CEO review)
- **Pending approvals** (v69+) — every guarded action still waiting on you, across all
  agents, with no age threshold: a pending approval means an agent has stopped. This
  signal is never silently suppressed.

**To enable:**

Edit your secretary agent's **profile** (in `.data/profiles/<agent-id>/profile.yaml`) and add:

```yaml
heartbeat:
  every: 30m
```

Valid intervals: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `24h`.

**Behavior:**

- When quiet (no issues found) → **0 messages, 0 cost**
- When there's something → **1 concise Telegram DM** (≤300 characters)
- When you're mid-conversation with the secretary → **deferred** (no interruption)
- **3 consecutive heartbeat errors** → auto-stop + one notification to you

---

## Reading Reports & Insights

### Office Display (v54 Cockpit + v87 redesign)

The **Office** main screen is a **3-zone grid** (adapts to single column ≤1100px):

| Zone | Shows |
|---|---|
| **Left rail** (260px) | Action queue: "Chờ anh/chị" (pending approvals + clarify questions, answer in-place with buttons or free text) + "Sắp chạy" (upcoming schedule, 60s refresh). Empty state shows one ✓ check mark. |
| **Center** (canvas + feed) | 3D workspace (collapsible) showing team desks. Below: live activity feed with filter chips [Tất cả \| Bước \| Ra ngoài]. |
| **Right column** (≤300px) | Workroom list (● in-progress / ⚠ stuck / ✓ done), per-room cost chip (lazy-loaded). Outputs (step artifacts). Review tray (click a review line to see per-criterion ✓/✗ + note). |

**3D Workspace:**

- Each agent has a desk with their avatar color.
- **PIC's desk** has a ⭐.
- **✋ waiting-hand** badge on desks with pending approvals/clarifications.
- **×N badge** when ≥2 concurrent steps running on that agent.
- **Translucent ghost figure** shows while a deep_team sandboxed step runs.
- When agents consult each other, avatars walk toward each other.
- Click a desk to open that agent's workroom.

**Activity Feed:**

- Real-time log of step status, milestones, reviews, and external actions (actions sent outside the company).
- Filter chips show "Tất cả" (all events), "Bước" (step events only), or "Ra ngoài" (outbound actions only — no message bodies, just actor/tool/outcome/target).
- Tail shows last 40 events; full history in **Office → Timeline**.

### Activity Log

**Work → Activity** tab shows the full audit trail:

- Every action the team took (posted to Slack, merged PR, wrote report).
- **Actor** (which agent did it, or human who approved it).
- **Sandbox tier** badge (🔒 N = N steps ran in Docker sandbox).
- **Cost per step** (expand to see token breakdown).
- Filterable and paginated.

Also visible to you via **Telegram** (if enabled) as an auto-sent summary.

### Cost View

On any task card (in **Approvals** tab or workroom):

- Click **"Cost"** button → see cost breakdown per step + total.
- Helps track budget and spot expensive tasks.

---

## Self-Checks & Peer Review (v13)

Automatic quality gates with **no CEO approval needed**:

### Self-Check

After completing a step, the agent:

1. Compares the result against acceptance criteria.
2. If not satisfied, reworks it (up to 2 times).
3. Reports completion or escalates to you if it still doesn't meet criteria after 2 attempts.

### Peer Review

After a step is done, a peer (usually Verification / QA if available):

1. Reviews the work.
2. Approves ("meets criteria") or requests changes.
3. If changes requested, original author reworks (up to 2 times).
4. If still not meeting criteria after 2 attempts, escalates to you.

---

## Consulting & Asking for Advice (v13)

**During a task**, an agent may ask a colleague for advice (up to 2 questions per step):

- Agent asks a peer for context/opinion about **their project** (reads peer's SOUL + project file, read-only).
- Takes 1-2 seconds; costs less than a full independent step.
- Shown on the Office screen as a speech bubble between two desks (avatars walk to each other, consult, then return).
- Does **not** count as a rework or escalation.

---

## Replanning Mid-Task (v13)

**If a task is running but you want to change it:**

Go to **Chat** → type:

```
replan task-123: drop the final audit step
```

or

```
replan task-123: add an image verification step
```

The assistant:

1. Shows you the DIFF (what's keeping, dropping, adding).
2. Estimates cost delta.
3. Awaits your confirmation.

**Safe:** Completed steps stay done and cannot change. Only pending/running steps follow the new plan.

---

## Chat with the Executive Assistant

**Chat** hub (home screen) is your command center for ad-hoc requests:

- **"What did the team accomplish this week?"** → summary of activity.
- **"Run the daily report now"** (vs. waiting for the schedule).
- **"Create an agent that…"** (conversational wizard).
- **"Replan task-X: …"** (adjust running tasks).
- **"Enable web search for the Research agent"** (configuration tweaks).

Type a request and **send**. The assistant previews what it will do, asks clarifying questions if needed, and waits for you to confirm before executing.

Type `?` or look for a help button to see available commands with examples.

---

## Two Lenses: Normal vs Technical Mode (dual-lens)

The header has a lens toggle — **👁 Thường** (normal, for the CEO) vs **🔬 Kỹ thuật**
(technical, for the maintainer). It changes what you SEE, never what you MAY do
(permissions are unchanged; advanced pages stay reachable by direct URL).

**Everyone (both modes)** sees on the Office screen: a desk turns **pulsing red with a
⚠ bubble** when that agent's step failed (it clears on the agent's next dispatch), and
a **floor ring flash** after a peer review — green = passed, orange = needs rework.

**Technical mode adds, without leaving the Office:**
- a **health strip**: coordinator heartbeat, integration checks as ✓/✗ chips, and a
  fleet **budget chip** (month spend vs cap; red at 80%, per-agent tooltip);
- **🔒 sandbox badges** on desks/rooms whose task has Docker-sandbox (deep_agent) steps;
- click a desk → the **Inspector drawer**: current step + phase, engine tier, task
  cost so far, links to the agent page and this task's Captures;
- **Captures** (advanced nav): the per-attempt telemetry table — engine, tokens, cost
  (exact/estimated), duration, errors; filter by task or agent;
- a **history search box** in the header (full-text over past work; a result jumps to
  its office room).

## Advanced Features (Optional Settings)

### Theme (Light / Dark / Auto)

Top-right corner button next to language toggle. Saved for next session.

### Advanced Mode

**System → Settings → "Chế độ nâng cao"**. The old advanced *navigation row* is gone —
those pages are now tabs inside the hub that owns them, reachable by anyone. What the
toggle still does is reveal the technical panels **inside** a hub: run/cost detail on the
office floor, per-agent operational numbers on the roster, raw config and artifact
internals. Leave it off for a 4-item interface; turn it on when you want the operator view.

### Language Toggle (VN / EN)

The header (next to the theme toggle) shows a **VN / EN** chip. Click to switch interface language.

**What DOES change:** hub nav labels ("Trò chuyện" → "Chat", "Đội ngũ" → "Team", etc.), settings labels, and all FE-static UI text.

**What STAYS Vietnamese in English mode:**
- Health-check status and error messages (these come from the backend system, not the UI layer).
- LLM-generated content (reports, clarifications, agent reasoning).
- Technical terms (they stay English in both languages for clarity): Captures, Guardrail, PIC, deep_agent, sandbox, engine, tokens, MCP, autonomous, guarded.

Your choice is saved in browser storage, so the dashboard remembers your preference next time you visit.

---

## Demo Mode (Safe Preview for Visitors)

To show the product to stakeholders without exposing real data:

```bash
scripts/demo-mode.sh on
# → generates demo company + 6 template agents + sample running task
# → http://127.0.0.1:8765 still works; can assign real tasks with LLM key

scripts/demo-mode.sh off
# → restores your real data (byte-identical, verified)
```

Real data is moved to `.demo-backup/` while demo is active. Demo agents have `dry_run: true` so they don't write externally.

> Tip: Turn off demo before committing code (registry.yaml changes during demo).

---

## Common Tasks

### Disable an Agent Temporarily

**Team** hub → find agent card → toggle **off**. Agent stops receiving new work; in-flight work finishes.

### Set Per-Agent Web Search (Research Role)

**Team** → click agent → **🔬 Nâng cao** tab → edit YAML and add:

```yaml
academic_search: true
```

Agent can now find papers via OpenAlex (no API key needed).

### Enable Telegram Alerts

**Team** → click agent → **Kênh** (Channels) tab → create a bot with @BotFather, paste token → agent sends alerts + reports to that bot.

### Watch a Project (Wake-up on Changes)

**Team** → click agent → **🔬 Nâng cao** tab → edit YAML and add:

```yaml
watchers:
  - source: jira
    query: "project = SCRUM"
    prompt: "Alert if new high-priority tasks"
```

System checks every 5 minutes (no LLM if content unchanged). When content changes, agent wakes and handles it once. Useful for staying on top of live projects.

### Deep Agent with Sub-Agents (v43)

Some tasks benefit from **multiple specialized sub-agents working inside a sandbox** (no Docker on host, all isolated):

**Team** → click agent → **🔬 Nâng cao** tab → edit YAML and enable:

```yaml
deep_team: true
deep_team_max_calls: 3
```

Now that agent can decompose large tasks into ≤3 sub-tasks and run them in parallel within the sandbox. Useful for research or analysis that splits into independent branches.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Task assigned but not running | Coordinator daemon not running. Check **System → Settings** → "Coordinator" status. Start it: `uv run python -m my_crew.runtime.service` |
| "Agent offline" badge on agent card | Agent crashed or exceeded budget. Check **System** settings + agent's activity tab. Restart coordinator. |
| Cannot chat in Chat hub | Chat hub not loaded. Refresh browser. Check console for errors. |
| Work queue not updating | Refresh browser. Check that coordinator is running. |
| Task shows "🔒 3 sandbox" but deep_agent unconfigured | Agent doesn't have Docker configured. Task will fail. Assign to an agent with `agent_runtime: deep_agent` + `sandbox` config. |
| "Web search not authorized" error | Web search key not set in Setup Wizard. Go to **System → Settings** for instructions. |

---

## FAQ

**Do agents write to Slack/GitHub without asking?**

By default (autonomous mode), **yes** — they write immediately and log it in the audit trail. If you want approval first, switch the agent to guarded mode (in **Team** → click agent → **🔬 Nâng cao**).

**What if an agent makes a mistake?**

Every action is logged immutably (audit log visible in **System → Audit**). Dangerous actions (permanent data loss, exposing secrets) are blocked at the gateway even if you approved it. For mistakes within guardrails, you can manually undo via the source (Jira, Slack, GitHub, etc.).

**Can I see how much budget was spent?**

Yes — **Work** hub shows kanban cards with cost per step. Click **"Cost"** to break it down. **System → Insights** shows the fleet-wide spend table (each agent's spend against its cap, plus the fleet total).

**What if an agent gets stuck (⚠)?**

Go to the workroom in **Office** → click **"Ask for help"** or **"Replan"** → adjust and confirm. If it's a genuine error, check **System → Settings** to see which integration failed.

**Can agents take on Telegram commands from me?**

Yes, if you've enabled Telegram for that agent. You can send "run the weekly report" via Telegram and the agent receives it as a task. See **Team** → click agent → **Kênh** (Channels) tab.

---

## Next Steps

- **For setup troubleshooting:** [deployment-guide.md](deployment-guide.md)
- **To understand the safety model:** [action-gateway-explainer.md](action-gateway-explainer.md)
- **To see architecture & decisions:** [project-overview-pdr.md](project-overview-pdr.md) · [system-architecture.md](system-architecture.md)
- **To track feature history & lessons:** [journals/](journals/)
