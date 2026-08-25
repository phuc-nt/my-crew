# Deployment & Setup Guide

> Full setup for installing, running, and configuring my-crew as a production system.
> **For daily operations (CEO / team lead):** see [user-guide.md](user-guide.md).
> **Updated:** 2026-08-16 (0.10.0).

## 1. Prerequisites

| Tool | Notes |
|---|---|
| Python 3.12+ | Installed via `uv` (manages venv pinning); do **not** use global 3.14+ |
| `uv` | Install: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js + npm | For building the web SPA and running 3 MCP servers |
| `git` | For cloning the repo |
| `gh` (GitHub CLI) | `brew install gh && gh auth login` (interactive; required for GitHub reads) |
| `gws` (optional) | Google Workspace CLI — hr-pack (Sheets) and personal-pack (Gmail/Calendar read, email send, calendar write) |

### Credentials & Tokens

Fill these **in the browser Setup Wizard** (never via terminal). Required:

- **OpenRouter** (LLM backbone): 1 API key. Supports $50/month budget cap per company, auto-stops.
- **Atlassian** (Jira + Confluence): site URL, email, 1 API token (shared across both).
- **Slack** (browser-token mode): xoxc token, xoxd token, workspace name, channel for reports.
- **GitHub**: authenticated via `gh auth login` (CLI-stored, not in `.env`).

Optional:

- **Tavily or Brave** (web search): only if using the research agent.
- **SMTP**: only if exporting reports to email (`.xlsx` attachments) or operator escalation via email.
- **Telegram**: only if enabling mobile command/alerts per agent.
- **Operator channels**: `OPERATOR_EMAIL` (SMTP recipient) and `OPERATOR_WEBHOOK_URL` (endpoint that receives a POST). Escalation tries Telegram, then email, then webhook, and stops at the first that delivers. Set at least one of these if the operator does not use Telegram — otherwise escalation has no way to reach anyone.

### 3 MCP Servers

Node.js stdio servers. `install.sh` installs them from npm by default; pass `--mcp-dev` to clone & build from source:

- **Jira** → [github.com/phuc-nt/jira-cloud-mcp-server](https://github.com/phuc-nt/jira-cloud-mcp-server) (v4.2.0)
- **Confluence** → [github.com/phuc-nt/confluence-cloud-mcp-server](https://github.com/phuc-nt/confluence-cloud-mcp-server) (v1.5.0)
- **Slack** → [github.com/phuc-nt/slack-browser-mcp-server](https://github.com/phuc-nt/slack-browser-mcp-server) (v1.3.0)

If they're not in the default location (`~/workspace/*-mcp-server`), point agents to them via `JIRA_MCP_DIST`, `CONFLUENCE_MCP_DIST`, `SLACK_MCP_DIST` in `.env`.

---

## 2. Install from PyPI (any OS — the shortest path)

```bash
uvx my-crew quickstart          # zero-install trial run (dry-run, needs only an OpenRouter key)
# or a persistent install:
pipx install my-crew            # or: uv tool install my-crew
my-crew doctor                  # diagnose the environment (node, keys, MCP builds)
my-crew serve                   # web dashboard + coordinator in the foreground
```

Installed this way, all user state lives in `~/.my-crew/` (override with
`MY_CREW_HOME`); the starter profiles seed themselves on first run. The web
dashboard is bundled in the wheel — Node is needed only for the MCP servers.
Upgrade later with `my-crew upgrade` (prints the exact command for your install
mode; `--check` compares against PyPI).

---

## 2b. One-Command Install (macOS + launchd, production)

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew
./deploy/install.sh
```

The script runs **7 automated steps**:

1. **Preflight** — checks required tools (`uv`, `node`, `git`, `gh`); prints exact fix commands if missing.
2. **`uv sync`** — installs Python dependencies into a venv.
3. **Build web SPA** — compiles React frontend to a temporary directory, then swaps atomically (never breaks live servers).
4. **Install 3 MCP servers** — from npm (default) or clones+builds (with `--mcp-dev`).
5. **`.env` bootstrap** — copies template on first run (v18); secrets only via browser wizard.
6. **Install launchd services** — coordinator + web daemon. Reloads only when plist or build changes (idempotent; won't kill in-flight agent runs).
7. **Health check** — reports ✓/✗ for each integration before opening the browser.

**Safe to re-run:** `./deploy/install.sh` after `git pull` is a no-op if nothing changed. Does **not** restart services unnecessarily and won't drop web sessions.

---

## 3. Setup Wizard (Browser — Secrets Entry Path)

On first run, the browser opens a **Setup Wizard** with interactive steps. Each step has a "Test Connection" button:

1. **OpenRouter** — paste API key.
2. **Atlassian** — site, email, token, Jira project code (e.g., `SCRUM`).
3. **Slack** — xoxc token, xoxd token, workspace name, reports channel.
4. **GitHub** — repo; verifies `gh auth login`.
5. **(Optional) Web Search** — toggle Tavily or Brave and paste API key (skip if research agent won't use it).
6. **Dashboard Password** — set a bcrypt-hashed login credential.

> **Security model:** Secrets flow **only** through this wizard. They are written to `.env` (gitignored) and never appear in terminals or URLs. The wizard self-locks after completion; you cannot re-open it.

---

## 4. Quick Start (30 seconds, v49)

Want to see results immediately without setting up all integrations?

```bash
# .env lives in your user-state root: the repo dir for a checkout,
# ~/.my-crew/ for a pipx/uvx install (see MY_CREW_HOME below).
echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.my-crew/.env    # checkout: >> .env
my-crew quickstart      # or: python -m my_crew.entrypoints.mpm quickstart
```

This runs the default agent's daily report in **dry-run mode** (logs intended actions; makes no external writes). It's safe to try.

### Scaffold the Starter Crew

To create sample agents and keep the setup:

```bash
my-crew crew init [office|personal]    # create starter crew (default: office)
my-crew serve                          # foreground: web dashboard + coordinator
# → http://127.0.0.1:8765
```

Options:
- `crew init` or `crew init office` — create the default office crew (manager + 4 specialists)
- `crew init personal` — create a personal assistant crew (personal assistant + 4 specialists)

After `crew init`, the **Teams** page shows coordinator status and launch instructions.

---

## 5. Manual Run (development, no launchd)

```bash
uv sync
cd web && npm install && npm run build && cd ..
uv run my-crew serve            # both processes, foreground; Ctrl-C stops cleanly
# → http://127.0.0.1:8765
# or split them: `my-crew serve --web-only` / `my-crew serve --scheduler-only`
```

- **Web:** binds to `BIND_HOST` (default: 127.0.0.1) on `PORT` (default: 8765). LAN binding is blocked unless `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` are set.
- **Coordinator daemon:** **required** for agents to dispatch work. Without it, the web dashboard shows a red banner warning that the scheduler is down.

---

## 6. Docker Compose (cross-platform, auth-first)

```bash
cd deploy/docker/
cp my-crew.env.example my-crew.env
```

Generate auth credentials **before** starting (R3 rule: secrets must be set before binding 0.0.0.0):

```bash
docker compose run --rm --no-deps my-crew my-crew web hash-password
# → paste the bcrypt hash into my-crew.env (WEB_AUTH_PASSWORD_HASH)
# → generate WEB_SESSION_SECRET: openssl rand -hex 32
# → set OPENROUTER_API_KEY in my-crew.env
```

Then start:

```bash
docker compose up -d
# → http://127.0.0.1:8765 → log in → Setup Wizard
```

User state (`.env`, `registry.yaml`, `profiles/`, `.data/`) persists on the `my-crew-data` volume. `docker compose down` keeps data; `docker compose up` resumes it.

---

## 7. Configuration

| File | Role | Git |
|---|---|---|
| `.env` | Secrets (tokens, API keys) | ignored |
| `registry.yaml` | Team roster (agent IDs, enabled/disabled) — **user data (v18)** | ignored (template: `registry.example.yaml`) |
| `company.yaml` | Company name, coordinator selection, budget cap, auto-confirm rules | ignored |
| `profiles/<id>/` | Agent profile (YAML + SOUL/PROJECT/MEMORY markdown files) | ignored (except default/ and templates/) |
| `company-docs/` | Company documentation injected into agent context | ignored |

> **v18 Important:** `registry.yaml` is **not** in git. Fresh checkout auto-bootstraps from `registry.example.yaml`. **Never `git checkout registry.yaml`** — you will lose your team.

### User State Root (`MY_CREW_HOME`)

Determines where `.env`, `registry.yaml`, profiles, and `.data/` live:

**Resolution order:**
1. `MY_CREW_HOME` env var (if set)
2. Git checkout root (operator behavior unchanged; live data in repo for dev)
3. `~/.my-crew/` (installed user, default)

### Model Configuration: Three Tiers (v79)

Every LLM call resolves its model through three tiers — most specific wins:

1. **Fleet default** — `OPENROUTER_MODEL` in `.env`. Unset ⇒ the built-in default
   `deepseek/deepseek-v4-pro-0813` (0.9.x shipped `qwen/qwen3.7-plus`).
2. **Per-agent** — `model:` in `profiles/<id>/profile.yaml` overrides the fleet
   default for that agent only.
3. **Per-role** — `role_models:` in the profile (or `OPENROUTER_ROLE_MODELS`
   in `.env` as a `role=model,role=model` string) overrides by work kind:
   `content`, `review`, `aggregate`, `plan`, `util`, `advisor`, `sprint_low`.

```yaml
# profiles/<id>/profile.yaml
model: deepseek/deepseek-v4-pro-0813    # tier 2: this agent's fleet override
role_models:                             # tier 3: per work kind
  review: your/cheaper-model
  util: your/cheaper-model
  sprint_low: your/very-cheap-model     # applies only when intake scores a brief as "easy"
```

The point of tier 3 is **cost shape, not capability**: the `content` role writes the
deliverable a human reads (never downgrade it), while review verdicts and slot
extraction are short mechanical calls that can run a cheaper model. The `sprint_low`
role applies only when sprint intake scores a brief as easy (low effort) — unconfigured,
easy briefs simply use the normal content model. A role override
keeps the fleet chain as fallback — when the cheap model is rate-limited or errors,
the role degrades *up* to the fleet model instead of failing. An unknown role name or
a duplicate role fails at config load, not at 3 a.m. in a cron run.

### Runtime Tiers: Choosing an Agent's Engine

**Default: `native`** — fixed DAG (perceive → analyze → compose → deliver). Cheap, deterministic, best for templated reports (daily/weekly/OKR). **Keep native agents for scheduled reports.**

**For open-ended reasoning:** upgrade to `create_agent` (LLM-chosen tools, read-only) or `deep_agent` (shell in isolated Docker sandbox).

```yaml
# profiles/<id>/profile.yaml

# Option 1: LLM self-directs across tools (Jira, GitHub, Confluence, web.scrape, etc.)
agent_runtime: create_agent
# or with custom loop limit for complex tasks:
agent_runtime:
  kind: create_agent
  runtime_loop_limit: 12

# Option 2: Autonomous shell within Docker sandbox (slow, needs Docker daemon)
agent_runtime:
  kind: deep_agent
  sandbox:
    provider: docker
    lease_seconds: 1800    # container lifetime (default 1800s, max 3600s)
    mem_limit: 512m        # container RAM cap (default 512m, max 4g)
```

Since v86 the `create_agent` tier runs a self-owned **thin tool loop** (OpenAI SDK) by default —
same toolset, ~3.5× fewer prompt tokens, exact cost reporting (no estimate). No profile change
needed. Set `loop_engine: langchain` inside the `agent_runtime` profile block to fall back to
the LangChain `create_agent` baseline (kept for A/B comparison).

**Per-team options (v44):**

```yaml
deep_team: true                 # enable in-sandbox subagents (v43)
deep_team_max_calls: 3          # subagent cap (default 3, range [1,8])
```

**v45 Smart Routing:** Team tasks auto-route per-step — no-shell steps run `create_agent` (0 Docker); steps with `needs_shell` flag run `deep_agent`. One agent with `deep_agent` config doesn't spin a container for every step; only steps that need shell pay the Docker cost.

### Docker Sandbox for `deep_agent`

**Requires:** Docker Desktop OR `colima` (lightweight, no GUI):

```bash
brew install colima && colima start
```

If Docker daemon is offline, deep_agent steps fail with "sandbox unavailable" — check the **Health** panel (§8) before assigning shell-heavy work.

**Limitation:** deep_agent sandbox is **not available inside the provided container** — if running my-crew in Docker, agents cannot spawn a nested sandbox. If you need deep_agent (shell tasks), run my-crew on the host or with Docker-in-Docker.

---

## 8. Going Live: DRY_RUN & Trust Modes

### Dry-Run Toggle

By default, agents **log intended actions without writing anywhere external.**

```bash
DRY_RUN=false my-crew serve       # enable external writes (Slack posts, PR merges, etc.)
```

Without this, all agents run in dry-run; set it in `.env`:

```env
DRY_RUN=false
```

**Per-agent override beats the fleet default.** `DRY_RUN` in `.env` only sets the
*fleet-wide* fallback. Any agent with an explicit `safety.dry_run` key in its own
`profiles/<id>/profile.yaml` uses that value instead, regardless of `.env`:

```yaml
# profiles/<id>/profile.yaml
safety:
  dry_run: true    # this agent stays in dry-run even if DRY_RUN=false fleet-wide
```

**Web toggle:** each agent's **Team → \<agent\> → Profile** tab shows the agent's
*effective* dry-run state as a badge (Diễn tập/Dry-run vs Gửi thật/Live), labelled with
its source (per-agent override vs fleet default), and a one-click checkbox to flip it.
The toggle writes `safety.dry_run` straight into that agent's `profile.yaml` (preserving
the rest of the file's comments and formatting) — no manual YAML editing needed.

**Takes effect on the agent's next run, no restart required.** Both the scheduler
(ticks) and the per-run worker process re-read `profile.yaml` from disk fresh every
time they dispatch — there is no in-memory cache of the profile between runs. A run
already dispatched keeps whatever setting it started with; the very next scheduled or
triggered run picks up the flip. This differs from `.env`-based settings such as
connection/webhook config, which env-loading processes cache at boot and DO need a
`my-crew serve` restart to pick up.

### Trust Modes (per agent)

**Autonomous (default):** Actions that send outside the company (post to Slack, merge PR, close ticket) **run immediately** and are logged in the audit trail. No CEO approval needed.

```yaml
# profiles/<id>/profile.yaml
safety:
  trust_mode: autonomous
```

**Guarded (opt-in):** Same actions **queue for approval** before executing. CEO must review and click "Approve" or "Reject" in the **Approvals** tab.

```yaml
safety:
  trust_mode: guarded
```

> **Hard-deny (Lớp A):** Actions that could lose data permanently (delete records, expose secrets) are **never allowed**, regardless of trust mode. See [action-gateway-explainer.md](action-gateway-explainer.md) for details.

### Google Workspace Access (per agent, v71)

**Disable reading and writing Google Workspace** (Gmail, Calendar, Tasks, Drive) for a specific agent by setting `gws_enabled: false` in its profile. This is **profile-only** (not an environment variable) on purpose: an env var is fleet-wide and could not disable one agent without disabling every agent.

When disabled:
- All Google Workspace **reads** (calendar events, unread emails, pending tasks) return `"(chưa cấu hình)"` with no API call. The keys stay present, so the prompt keeps the same shape as an enabled agent.
- All Google Workspace **write** commands (`gws_write`: send email, create/update/delete calendar events) are removed from the agent's command catalog — the agent cannot even offer to do them.
- The team-step tool loop's `gws.gmail` / `gws.calendar` / `gws.drive` tools are withheld even if that agent's `gws_context: true`. `gws_enabled` dominates.

```yaml
# profiles/<id>/profile.yaml
gws_enabled: false     # default true when key is absent; existing agents unaffected
```

This is useful for the personal assistant agent (to respect user privacy) or any agent that should not interact with personal email/calendar.

### Autopilot (v63) — the AI as final approver

Company-wide flag in `company.yaml` (next to the repo, or under `MY_CREW_HOME`):

```yaml
autopilot: true    # default false
```

When on: team-task plans auto-confirm, stalled tasks auto-resolve on a two-step
ladder, pending Lớp B approvals auto-approve — every decision is reported back over
Telegram and audited. Per-task opt-out: the CEO says "để anh duyệt" when assigning.
Lớp A hard-denies and per-task cost caps are unaffected by this flag (pinned by tests).

### Cost & Review Brakes (v78–v79)

- **Per-task cost cap:** `team_task_cap_usd` in `company.yaml` (default $2). Since
  0.10.0 a breach also **halts steps already running** — previously cancel only
  flipped the task status while spawned workers ran (and billed) to completion.
- **Per-task review/rework budget:** 2× the task's content steps, floor 5. On breach
  the task stalls and escalates to the CEO instead of minting more review rounds.
  Not configurable; each step's peer review is additionally capped at 2 rework rounds.

---

## 9. Backup & Recovery

```bash
./deploy/backup.sh /path/to/backups
# → creates timestamped tar of .data/, profiles/, registry.yaml, company-docs/
```

**Secrets (.env) are NOT backed up.** Restore manually from your password manager. Restore data:

```bash
cd /path/to/repo
tar -xzf /path/to/backups/my-crew-TIMESTAMP.tar.gz
./deploy/install.sh    # idempotent; re-seeds state from backups
```

**Cron backup (daily at 02:00):**

```bash
0 2 * * * /path/to/deploy/backup.sh /path/to/backups
```

---

## 10. Health Checks

Access **Settings → System Health** in the web dashboard. A table shows ✓/✗ status for:

- OpenRouter (LLM connectivity)
- Atlassian (Jira + Confluence)
- Slack
- GitHub (via `gh`)
- MCP server builds
- Docker daemon (for deep_agent)
- Web search integration

Each failure shows the exact remediation command. Docker probe has a time limit (won't hang the panel); ✗ only affects agents using `deep_agent` — teams without deep_agent work fine.

### Warm Sandbox Image (Optional)

On first `deep_agent` step, the Docker image is pulled (slow). Pre-warm it:

```bash
my-crew sandbox prepull
# or with a custom image:
my-crew sandbox prepull ghcr.io/phuc-nt/my-crew-sandbox:latest
```

Idempotent: if image exists, no-op. If daemon is offline, prints a clear message (no crash).

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Tasks assigned but stuck (not running) | Coordinator daemon not running | `uv run python -m my_crew.runtime.service` |
| Dashboard shows empty teams | Registry missing agents | **Teams** tab → "Profiles not in registry" → **Add to team** |
| Research agent says "web search not authorized" | Web search key not provided in Setup Wizard | Add Tavily or Brave key in Setup, or disable web_search |
| LAN bind fails on startup | Web auth not configured | Set `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` in `.env` |
| deep_agent step errors "sandbox unavailable" | Docker daemon not running | Start Docker Desktop or `colima start`; check **Health** panel first |
| First deep_agent step is slow | Image not cached; Docker is pulling | Pre-warm with `my-crew sandbox prepull` (§10) |
| New route/feature doesn't appear after `git pull` | Dev server not reloading code | Restart web service: kill + re-run `serve`, or `./deploy/install.sh` if using launchd |
| Every MCP integration fails at import (Jira, Confluence, Slack), doctor shows an ImportError next to a "set the token" hint | `mcp` resolved to 2.0.0, which dropped `mcp.shared.context.RequestContext` that `langchain-mcp-adapters` still imports | Already pinned as `mcp<2` in `pyproject.toml`; on an old environment re-sync deps rather than chasing the token hint, which cannot fix it |

---

## 12. Upgrade Path & Breaking Changes

### 0.6.x → 0.7.0: persistent memory store default

The profile default `runtime.store` changed `memory` → `sqlite` (shared
`.data/memory_store.sqlite3`): extracted facts now survive restarts and are readable
across agents, with 90-day retention. Existing profiles keep whatever they declare —
a profile still on `store: memory` works but its facts vanish on restart; switch it
to `store: sqlite` to join the shared memory. New per-profile field `memory_share:
full | read_only` (default full) controls whether an agent's facts are shared or the
agent only reads others' (the shipped secretary is `read_only`).

### v51 Rename Notification

**After upgrading to v51**, the source directory was renamed (`src/` → `my_crew/`). If upgrading a running system:

1. **Re-run the installer to re-render launchd plists:**
   ```bash
   git pull origin main
   ./deploy/install.sh
   ```

2. **Check for orphan pre-rename processes** (they will 500 every route):
   ```bash
   lsof -nP -iTCP:8765
   # Kill any stale processes holding port 8765
   ```

3. **Restart coordinator and web if upgrading from <v51:**
   ```bash
   # If using launchd:
   launchctl stop com.phucnt.my-crew-coordinator
   launchctl stop com.phucnt.my-crew-web
   
   # Then re-run install.sh, which reloads them
   ./deploy/install.sh
   ```

### DRY_RUN Default Behavior

`DRY_RUN=true` is the safe default. On first deploy, all agents log intended actions but make no external writes. Only set `DRY_RUN=false` when you are ready for the agent to act autonomously.

---

## 13. Performance & Scaling

### Memory & CPU

**Minimum:** 2 GB RAM, 2 CPU cores.

**Recommended:** 4 GB RAM, 4 CPU cores (if running deep_agent with multiple concurrent tasks).

**Docker:** Set container `mem_limit` in `docker-compose.yaml` if needed; default 512m per sandbox.

### Concurrency Knobs

```yaml
# company.yaml (global settings)
team_task_concurrency: 2        # max parallel team tasks (default 2)
deep_team_max_calls: 3          # max subagents per deep_agent (default 3)
```

---

## 14. Production Checklist

- [ ] All 3 required credentials filled in Setup Wizard (OpenRouter, Atlassian, Slack, GitHub).
- [ ] `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` set if binding to LAN.
- [ ] `DRY_RUN=false` set in `.env` to enable external writes.
- [ ] Backup script configured: `0 2 * * * /path/to/deploy/backup.sh /path/to/backups`.
- [ ] Coordinator daemon running (check **Health** → "Coordinator" ✓).
- [ ] Health panel shows ✓ for all integrations you're using.
- [ ] First test report ran successfully (check **Activity** tab).
- [ ] Agents assigned to work; observe one full cycle (compose → execute → report).
- [ ] Telegram bot optional but recommended for real-time alerts.

---

## Further Reading

- **Daily operations:** [user-guide.md](user-guide.md)
- **Understanding the guardrail:** [action-gateway-explainer.md](action-gateway-explainer.md)
- **Architecture & decisions:** [project-overview-pdr.md](project-overview-pdr.md) · [system-architecture.md](system-architecture.md)
- **Build history & lessons:** [journals/](journals/)
