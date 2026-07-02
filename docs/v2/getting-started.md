---
title: "Getting Started — Add a New Agent & Project"
description: "Step-by-step tutorial to register and configure a new PM agent for your project."
status: stable
created: 2026-06-28
---

# Getting Started — Add a New Agent & Project

> Register a PM agent for a new Jira project, GitHub repo, and Slack channel. Takes 10 minutes.
> **New in M7**: You can now create agents via the web UI (non-technical). See §Web UI below. Otherwise, follow the CLI steps.
> Back to [v2 README](README.md).

---

## Web UI Method (New in M7)

If you have the web dashboard running on localhost, you can create agents without touching the terminal:

1. Open http://localhost:8765/create
2. **Step 1**: Select your domain (pm, hr, or custom)
3. **Step 2**: Enter agent ID and name; optionally fill persona
4. **Step 3**: Choose report kinds and build a cron schedule
5. **Step 4**: Fill bindings (Jira project, GitHub repo, Slack channel, Confluence space)
6. **Step 5**: Review and get a `.env` template to copy-paste to your technical operator

The wizard validates everything before saving. On completion, the agent appears in the Team view.

> **Ask-agent (M11):** add an `inbox:` block to the agent's profile.yaml (`channel: <internal channel ID>`, `poll_minutes: N`) and the running service will answer `@<agent-id>` mentions in that channel with real data, in a thread. Internal channels only; every reply goes through the Action Gateway.

---

## CLI Method (Traditional)

### Part 1: Register the Agent

The registration command scaffolds a new agent directory from the default template and adds it to the registry.

```bash
uv run python -m src.entrypoints.mpm agent register <agent-id>
```

Example: register an agent named `acme-web` for the ACME Web Platform project.

```bash
uv run python -m src.entrypoints.mpm agent register acme-web
```

This creates:

```
profiles/acme-web/
├── profile.yaml       ← config: bindings, thresholds, budget, schedule
├── SOUL.md            ← persona/tone (empty by default)
├── PROJECT.md         ← team context (empty by default)
└── MEMORY.md          ← agent-maintained memory (always empty at start)
```

And adds to `registry.yaml`:

```yaml
agents:
  - id: acme-web
    enabled: true
```

---

## Part 2: Fill the Profile

Open `profiles/acme-web/profile.yaml` and fill the **5 required fields**:

| Field | Example | Why |
|---|---|---|
| `bindings.jira.project_key` | `ACME` | Jira project key (uppercase, visible in Jira URL: `jira.example.com/browse/ACME-123`) |
| `bindings.github.repo` | `acme/web-platform` | GitHub owner/repo (used by `gh` CLI) |
| `bindings.slack.report_channel` | `#acme-standup` | Where the daily report posts |
| `bindings.slack.token_env` | `ACME_SLACK_XOXC_TOKEN` | Name of env var holding the Slack token (value goes in `.env`, not here) |
| `bindings.confluence.space_key` | `ACME` | Confluence space key (where reports are archived) |

**Minimal working example:**

```yaml
id: acme-web
name: "ACME Web Platform"
enabled: true

bindings:
  jira:
    project_key: ACME
    token_env: ATLASSIAN_API_TOKEN
  github:
    repo: acme/web-platform
  slack:
    report_channel: "#acme-standup"
    token_env: SLACK_XOXC_TOKEN
  confluence:
    space_key: ACME
    token_env: ATLASSIAN_API_TOKEN

# All defaults below — tune later if needed
model: minimax/minimax-m2.7
budget:
  monthly_usd: 50
  warn_ratio: 0.8
safety:
  dry_run: true          # ← DRY_RUN by default (logs, posts nothing)
  write_disabled: false
thresholds:
  pr_stale_days: 7
  blocker_label_substring: block
  okr_behind_threshold: 0.5
  resource_overload_ratio: 1.5
  labor_cost_per_issue: 0
schedule: {}
reports: []
```

### Optional: Add Persona & Context

**`profiles/acme-web/SOUL.md`** — your agent's tone:

```markdown
# Persona — ACME Web Platform

You are the PM agent for the ACME Web Platform team. Be direct and action-focused.
When reporting to stakeholders (external audience), remove all developer jargon and issue keys.
```

**`profiles/acme-web/PROJECT.md`** — team facts the agent should know:

```markdown
# ACME Web Platform — Project Context

- Team: 6 engineers, 1 Scrum Master.
- Release schedule: quarterly (next: Q3 2026-09-30).
- Label convention: "p0" or "critical" = blocker.
- Known risk: review bottleneck on backend PRs (reviewer @minh-le is often blocked).
```

Both are optional — leave them empty if you prefer defaults. The agent reads them fresh on every run.

---

## Part 3: Add Secrets to `.env`

The `token_env` fields in `profile.yaml` are names. The actual tokens go in `.env` (gitignored).

```bash
cp config.example.env .env  # if not already done
```

Then add:

```bash
# For acme-web agent (using Slack XOXC token)
SLACK_XOXC_TOKEN=xoxc-...
SLACK_XOXD_TOKEN=xoxd-...
ATLASSIAN_API_TOKEN=ATATT...

# Global: required for all agents
OPENROUTER_API_KEY=sk-or-...
ATLASSIAN_SITE_NAME=acme.atlassian.net
ATLASSIAN_USER_EMAIL=you@acme.com
SLACK_TEAM_DOMAIN=acme.slack.com

# GitHub: auth via `gh` CLI (not in .env)
# Run: gh auth login
```

**Never commit `.env`** — it's in `.gitignore`.

---

## Part 4: Test (Dry Run)

The `dry_run: true` default means "log what the agent WOULD do, post nothing."

```bash
uv run python -m src.entrypoints.mpm agent run acme-web --report daily
```

Output logs to console (no Slack post, no Confluence write). Inspect the logs to verify:

- ✅ Jira connection OK (issues listed)
- ✅ GitHub connection OK (PRs listed)
- ✅ Slack & Confluence connections OK (channels found)

### Troubleshoot failures at this stage using the FAQ below.

---

## Part 5: Enable Live Mode & Schedule (Optional)

Once dry run succeeds:

### Enable posting:

```bash
# One-time test — posts to Slack/Confluence for real
DRY_RUN=false uv run python -m src.entrypoints.mpm agent run acme-web --report daily
```

Then flip it in `profile.yaml`:

```yaml
safety:
  dry_run: false    # ← Now live
```

### Schedule it:

Uncomment in `profile.yaml`:

```yaml
schedule:
  daily: "0 9 * * *"      # 09:00 every day
  weekly: "0 17 * * 5"    # 17:00 Fridays
```

Install the coordinating service (runs agents on schedule):

```bash
./deploy/launchd/install.sh
```

Check logs:

```bash
tail -f .data/cron-acme-web.log
```

---

## Part 6: Manage Approvals (Lớp B)

Certain writes (closing a PR, reassigning a person, posting to a stakeholder channel) require human approval first.

List pending approvals for an agent:

```bash
uv run python -m src.entrypoints.mpm agent approvals acme-web
```

Sample output:

```
ID                 | Type             | Status   | Created
approval-123-abc   | close_pr         | pending  | 2026-06-28 09:30
approval-124-def   | post_external    | pending  | 2026-06-28 09:31
```

Approve or reject:

```bash
# Approve
uv run python -m src.entrypoints.mpm agent approve acme-web approval-123-abc

# Reject
uv run python -m src.entrypoints.mpm agent reject acme-web approval-123-abc
```

For a web-based approval UI, see the web dashboard (M2 feature).

---

## FAQ & Troubleshooting

### MCP server spawn fails / "command not found"

**Symptom:** Error like `spawn ENOENT` or `cannot find jira-mcp-server`.

**Cause:** The 3 external MCP servers (Jira, Confluence, Slack) are separate repos you must clone and build.

**Fix:**

```bash
cd ~/workspace
for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
  git clone git@github.com:phuc-nt/$repo.git
  (cd $repo && npm install && npm run build)
done
```

If you cloned them to a different path, set env vars in `.env`:

```bash
JIRA_MCP_DIST=~/my-servers/jira-cloud-mcp-server/dist/index.js
CONFLUENCE_MCP_DIST=~/my-servers/confluence-cloud-mcp-server/dist/index.js
SLACK_MCP_DIST=~/my-servers/slack-browser-mcp-server/dist/index.js
```

---

### GitHub calls fail / "not authorized"

**Symptom:** `GraphQL error: Unauthorized` or `gh: authentication required`.

**Cause:** GitHub auth via the `gh` CLI (not a token in `.env`). You must log in first.

**Fix:**

```bash
gh auth login
# Select: GitHub.com, HTTPS, Paste PAT or use browser login, scoped (read repo + PR + commit)
gh auth status  # verify
```

The agent reads your logged-in credentials automatically.

---

### Slack: "channel not found" or report not posted

**Symptom:** Slack post fails with `channel_not_found` or report never appears.

**Cause:** 
1. Channel name vs ID mismatch (profile uses `#acme-standup` but Slack internal ID is `C0123456`)
2. Agent lacks permission to post (token expired or not in channel)
3. Report queued for approval (Lớp B) — won't auto-post to stakeholder channels

**Fix:**

1. **Use channel ID instead of name** (more reliable):

   ```bash
   # In Slack, open the channel → Details → copy the ID (C0123XXXXX)
   ```

   Update `profile.yaml`:

   ```yaml
   slack:
     report_channel: "C0123XXXXX"    # ← ID, not name
   ```

2. **Verify token has channel access:**

   ```bash
   uv run python -m src.entrypoints.mpm agent run acme-web --report daily
   # Check logs for "channel_not_found" errors
   ```

3. **For stakeholder channels:** If the report is for an external audience, it goes to Lớp B approval:

   ```bash
   uv run python -m src.entrypoints.mpm agent approvals acme-web
   # Approve the pending `post_external` action
   ```

---

### "Nothing posted at all" / report silent

**Symptom:** Dry run logs mention "Would post to Slack" but nothing appears. No errors.

**Cause:** `dry_run: true` (the safe default) means the agent logs but does NOT post.

**Fix:**

Verify `profile.yaml`:

```yaml
safety:
  dry_run: false    # ← Change from true
```

Or run with the flag:

```bash
DRY_RUN=false uv run python -m src.entrypoints.mpm agent run acme-web --report daily
```

---

### Budget hard-stop reached / agent stopped writing

**Symptom:** Error like `monthly_budget_usd exceeded (cost: $52 > budget: $50)`.

**Cause:** The agent tracks OpenRouter API spend. Cost hit the month's limit.

**Fix:**

1. Wait for the calendar month boundary (resets automatically), OR
2. Increase the cap in `profile.yaml`:

   ```yaml
   budget:
     monthly_usd: 100    # ← raise the limit
   ```

3. Check spend:

   ```bash
   uv run python -m src.entrypoints.mpm agent audit acme-web --cost
   ```

---

### External report never appears / "stuck in Lớp B queue"

**Symptom:** You ran `--audience external` but the report never posts to the stakeholder channel.

**Cause:** External posts (to executives, investors, or public channels) are queued for human review first (Lớp B approval). This is by design — no autonomous post to sensitive audiences.

**Fix:**

The report is **not** lost; it's waiting. Check approvals:

```bash
uv run python -m src.entrypoints.mpm agent approvals acme-web
```

Approve it:

```bash
uv run python -m src.entrypoints.mpm agent approve acme-web <approval_id>
```

Then the agent posts to Slack + Confluence.

---

### launchd job not firing / scheduled report didn't run

**Symptom:** Scheduled time passed but `.data/cron-acme-web.log` is empty.

**Cause:** 
1. `install.sh` wasn't run (manual symlink of .plist doesn't work reliably)
2. Machine was asleep (launchd only fires when awake)
3. The schedule cron expression is wrong

**Fix:**

1. **Ensure install.sh was run:**

   ```bash
   ./deploy/launchd/install.sh
   # Checks: ~/.config/launchd/my-project-manager-coordinator.plist exists
   ```

2. **Check logs:**

   ```bash
   tail -f .data/cron-acme-web.log
   # If empty or old, the job hasn't fired
   ```

3. **Manual trigger (test):**

   ```bash
   launchctl start my.project-manager.coordinator
   # Then check logs again
   ```

4. **Validate the cron expression:**

   ```yaml
   schedule:
     daily: "0 9 * * *"   # ← 09:00 UTC daily (verify TZ if needed)
   ```

   Test locally:

   ```bash
   DRY_RUN=false uv run python -m src.entrypoints.mpm agent run acme-web --report daily
   ```

---

### Agent crashes with "import error" or "module not found"

**Symptom:** Error like `ModuleNotFoundError: No module named 'src.actions'`.

**Cause:** Dependencies not synced or Python version mismatch (repo requires Python 3.12).

**Fix:**

```bash
# Re-sync dependencies
uv sync

# Verify Python version
python --version   # should be 3.12.x

# If using system Python, force 3.12
uv python install 3.12
uv sync
```

---

### Confluence page not created / OKR section blank

**Symptom:** Jira/GitHub data posts to Slack OK, but Confluence page is empty or missing OKR section.

**Cause:**
1. `space_key` is wrong
2. `okr_page_id` not set (OKR only if you link a Confluence page with an OKR table)
3. Confluence token lacks write permission

**Fix:**

1. **Verify space key:**

   ```bash
   # In Confluence, go to Space → Space settings → get the "Space key"
   ```

   Update `profile.yaml`:

   ```yaml
   confluence:
     space_key: ACME     # ← correct key
   ```

2. **Link OKR page (optional):**

   If you have a Confluence page with an OKR tracking table, get its page ID and add:

   ```yaml
   confluence:
     okr_page_id: "557057"    # ← page ID (visible in URL: ...pages/557057/...)
   ```

3. **Check token scope:**

   Atlassian token must have write access to the space. Regenerate if needed (id.atlassian.com → Security → API tokens).

---

### Performance: report takes too long

**Symptom:** Daily report takes >30 seconds; agent seems slow.

**Cause:** 
1. Large Jira project (1000s of issues) — analyzer fetches all
2. Network latency to Slack/Confluence API
3. LLM latency (depends on OpenRouter queue)

**Fix:**

1. **Filter Jira in PROJECT.md:**

   ```markdown
   # Focus on backlog only (not closed issues)
   Analyzer filter: JQL = status != Done AND sprint = ACME-Current
   ```

2. **Check cost/latency with audit:**

   ```bash
   uv run python -m src.entrypoints.mpm agent audit acme-web --timing
   ```

3. **Adjust thresholds to reduce LLM context:**

   ```yaml
   thresholds:
     pr_stale_days: 10      # ← less strict = fewer PRs to analyze
   ```

---

### "Dry run showed stale PRs but doesn't mention my specific PR"

**Symptom:** You know a PR is stale, but the agent's daily report doesn't list it.

**Cause:** 
1. PR state changed since agent ran (merged/closed)
2. PR is in a draft state (agent filters drafts)
3. `pr_stale_days` threshold is higher than the PR's age

**Fix:**

Check manually in the logs:

```bash
# Re-run with DEBUG=true
DEBUG=true uv run python -m src.entrypoints.mpm agent run acme-web --report daily 2>&1 | grep "PR\|stale"
```

Adjust threshold:

```yaml
thresholds:
  pr_stale_days: 3    # ← lower threshold (flag PRs older than 3 days)
```

---

## Next Steps

- **Web dashboard:** See [v2/README.md](README.md) for access to live UI (M2 feature).
- **More agents:** Repeat Parts 1–5 for your next project.
- **Advanced:** See [profile-design.md](profile-design.md) for detailed field reference, including Postgres config, per-agent models, and skill injection.
- **Safety & audit:** See [../v1/action-gateway-explainer.md](../v1/action-gateway-explainer.md) for how guardrails work.
