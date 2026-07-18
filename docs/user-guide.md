# Daily Operations Guide

> **For Vietnamese operators:** [huong-dan-su-dung.md](huong-dan-su-dung.md) is the day-to-day canonical reference.
>
> Dashboard and team operations for CEO / team leads (no technical knowledge required).
> All work via browser dashboard or Telegram.
> **Updated:** 2026-07-18.

---

## Opening the Dashboard

After setup, access the web interface at `http://127.0.0.1:8765` (or your deployed URL). Log in with the password set during Setup Wizard.

---

## The 4 Main Sections

The navigation bar has 4 primary sections (plus Settings):

| Section | Purpose |
|---|---|
| **Office** | MAIN SCREEN: assign work, watch team in real-time, review deliverables in 3D workspace. |
| **Team** | Roster: view agent status, budget, pause/enable/delete agents, create new ones. |
| **Approvals** | Queue of work awaiting your approval (badge shows count) + kanban board of all tasks. |
| **Assistant** | Chat with the executive assistant: ask questions, create agents via conversation, run one-off commands. |
| **Settings** | System health, theme, advanced mode, auto-confirm rules. |

---

## Assigning Work to the Team

**Quickest way:** Go to **Office** and type in the task box at the bottom.

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

**Option 3: Detailed conversation (via Assistant)**

Click **Assistant** → type the request → answer questions step-by-step → the assistant creates the task and shows it in real-time on the **Office** screen.

### Reviewing the Plan

After you type a task, the system:

1. Breaks it into up to 7 steps.
2. Shows you the **plan** (who does what, in what order, estimated cost).
3. Displays the **PIC** (person responsible for the final handoff).
4. Waits for your **"Confirm"** or **"Cancel"**.

On the Office screen, the 3D workspace shows the PIC's desk with a **⭐** and **PIC** label. You can refine the plan in the **Assistant** if needed (see Replan, below).

### Workrooms

Each assigned task opens a **workroom** — a dedicated space for that task. Workrooms are listed on the left of the Office screen:

- **●** = task in progress
- **⚠** = task stuck
- **✓** = task completed

Click a workroom to enter and:

- **Ask for status update** ("how's it going?") — agent responds in real-time (response is not saved to history).
- **Tweak the plan mid-execution** ("drop the final review step" / "add image verification") — see the DIFF before applying.
- **Assign sub-tasks to stay in the same workroom** ("now do X").

---

## Approvals & Trust Modes

### Two Types of Queued Work

**Tab: Approvals**

| Type | Source | Action |
|---|---|---|
| **Actions from guarded agents** | Agent set to `trust_mode: guarded` | Awaits your approval before executing. |
| **Automation proposals** | Automation script (no live agent) | Always awaits approval, any trust mode. |

### Autonomous vs. Guarded

**Autonomous (default):** Actions sent outside the company (post to Slack, merge PR, close Jira ticket) **run immediately** and appear in the audit log. No approval needed.

**Guarded (opt-in per agent):** Same actions **queue for approval**. You click "Approve" or "Reject" in the **Approvals** tab.

> **Hard-deny actions (Lớp A):** Actions that could lose data permanently (delete records, expose secrets) are **never allowed**, even if guarded. See [action-gateway-explainer.md](action-gateway-explainer.md).

**To switch an agent to guarded:**

1. Go to **Team** → select agent.
2. In the **Settings** tab, add:
   ```yaml
   safety:
     trust_mode: guarded
   ```
3. Save. Next upgrade cycle, agent becomes guarded.

---

## Team Management

### View Team Status

**Team** tab shows all agents with:

- **Status** (idle / working / errored)
- **Budget spent** this cycle
- **Any stuck tasks** (⚠)

### Create a New Agent

**Option 1: One-click templates** (fastest)

Click **"+ Create virtual agent"** → pick a template card (6 roles: Team Lead, Research, Content, Analytics, Verification, PM-Coordinator) → click **"Create now"** → done. Agents start **disabled**. Enable them after setting up credentials (if needed) in the Team tab.

Templates auto-load their skills at runtime, so updating a template skill instantly affects all agents using it.

**Option 2: Crew creation** (bulk)

Click **"+ Create full crew"** → system creates all 5 template agents at once (shows which ones already exist) → confirm → all created independently (if 1 fails, others still created).

**Option 3: Custom via chat**

Use the **Assistant** tab → ask "create an agent that…" → answer questions → assistant creates it and turns it on immediately.

### Manage Agents

**Pause an agent** → disable it (stops receiving new work; in-flight work completes).

**Delete an agent** → remove from roster (can recreate from template anytime).

**Upgrade agent config** — when a template updates:

1. Agent card shows **"⬆ new vN"** badge.
2. Click it → see what will change.
3. **"Upgrade"** applies new config (fields you customized stay yours); **old profile auto-backed up**.

---

## Reading Reports & Insights

### Office Display (v17)

The **Office** main screen has **3 columns + 3D workspace + chat**:

| Column | Shows |
|---|---|
| **Workroom list** (left) | All tasks in progress/stuck/done, organized by workroom. |
| **Live activity** (middle) | Real-time log of agent actions (who did what, when, result). |
| **Deliverables** (right) | Final outputs from each completed step. Click to see full markdown, copy it, or download as `.md` file. |

**3D Workspace (top, collapsible):**

- Each agent has a desk with their avatar color.
- **PIC's desk** has a ⭐.
- When agents consult each other, avatars walk toward each other.
- Agent's desk lights up when they're actively working.
- Click a desk to open that agent's workroom.

### Activity Log

**Office → Activity** (or ask Assistant "what did the team do this week?") shows the full audit trail:

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

Go to **Assistant** → type:

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

**Assistant** tab is your command center for ad-hoc requests:

- **"What did the team accomplish this week?"** → summary of activity.
- **"Run the daily report now"** (vs. waiting for the schedule).
- **"Create an agent that…"** (conversational wizard).
- **"Replan task-X: …"** (adjust running tasks).
- **"Enable web search for the Research agent"** (configuration tweaks).

Type a request and **send**. The assistant previews what it will do, asks clarifying questions if needed, and waits for you to confirm ("approve") before executing.

Click **"What can the assistant do?"** → system lists all available commands with examples. Click an example to copy it into the chat.

---

## Advanced Features (Optional Settings)

### Theme (Light / Dark / Auto)

Top-right corner button. Saved for next session.

### Advanced Mode

**Settings → Display Mode → "Advanced mode"** → navigation bar shows additional technical pages (all in Vietnamese):

- **Overview** — full agent roster + status.
- **Timeline** — execution history.
- **Cost** — budget tracker chart.
- **Memory** — what the assistant remembers + pending proposals.
- **Guardrail** — audit log of actions allowed/denied/queued.
- **Configuration** — edit agent profiles directly (YAML).
- **Manual run** — run a report immediately.
- **Office** — task timeline + 3D office wireframe.

Toggle off to return to the simplified 4-section view. This only changes detail level; it doesn't affect permissions.

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

**Team** tab → agent card → toggle **off**. Agent stops receiving new work; in-flight work finishes.

### Set Per-Agent Web Search (Research Role)

**Team** → Research agent → **Settings** tab → add to YAML:

```yaml
academic_search: true
```

Agent can now find papers via OpenAlex (no API key needed).

### Enable Telegram Alerts

**Team** → select agent → **Telegram Channel** tab → create a bot with @BotFather, paste token → agent sends alerts + reports to that bot.

### Watch a Project (Wake-up on Changes)

**Team** → agent → **Settings** → add:

```yaml
watchers:
  - source: jira
    query: "project = SCRUM"
    prompt: "Alert if new high-priority tasks"
```

System checks every 5 minutes (no LLM if content unchanged). When content changes, agent wakes and handles it once. Useful for staying on top of live projects.

### Deep Agent with Sub-Agents (v43)

Some tasks benefit from **multiple specialized sub-agents working inside a sandbox** (no Docker on host, all isolated):

**Team** → deep_agent → **Settings** → enable:

```yaml
deep_team: true
deep_team_max_calls: 3
```

Now that agent can decompose large tasks into ≤3 sub-tasks and run them in parallel within the sandbox. Useful for research or analysis that splits into independent branches.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Task assigned but not running | Coordinator daemon not running. Check **Settings → System Health** → "Coordinator" status. Start it: `uv run python -m my_crew.runtime.service` |
| "Agent offline" badge on agent card | Agent crashed or exceeded budget. Check **System Health** + agent's recent activity. Restart coordinator. |
| Cannot assign work via chat | Assistant tab not loaded. Refresh browser. Check console for errors. |
| Approvals tab not updating | Refresh browser. Check that coordinator is running. |
| Report shows "🔒 3 sandbox" but deep_agent unconfigured | Agent doesn't have Docker configured. Task will fail. Assign to an agent with `agent_runtime: deep_agent` + `sandbox` config. |
| "Web search not authorized" error | Web search key not set in Setup Wizard. Go to **Settings → System Health** for instructions. |

---

## FAQ

**Do agents write to Slack/GitHub without asking?**

By default (autonomous mode), **yes** — they write immediately and log it in the audit trail. If you want approval first, switch the agent to guarded mode (in Team → Settings).

**What if an agent makes a mistake?**

Every action is logged immutably (audit log). Dangerous actions (permanent data loss, exposing secrets) are blocked at the gateway even if you approved it. For mistakes within guardrails, you can manually undo via the source (Jira, Slack, GitHub, etc.).

**Can I see how much budget was spent?**

Yes — **Approvals** tab kanban cards show cost per step. Click **"Cost"** to break it down. **Advanced mode → Cost** page shows a chart.

**What if an agent gets stuck (⚠)?**

Go to the workroom → click **"Ask for help"** or **"Replan"** → adjust and confirm. If it's a genuine error, check **System Health** to see which integration failed.

**Can agents take on Telegram commands from me?**

Yes, if you've enabled Telegram for that agent. You can send "run the weekly report" via Telegram and the agent receives it as a task. See **Team → [agent] → Telegram Channel**.

---

## Next Steps

- **For setup troubleshooting:** [deployment-guide.md](deployment-guide.md)
- **To understand the safety model:** [action-gateway-explainer.md](action-gateway-explainer.md)
- **To see architecture & decisions:** [project-overview-pdr.md](project-overview-pdr.md) · [system-architecture.md](system-architecture.md)
- **To track feature history & lessons:** [journals/](journals/)
