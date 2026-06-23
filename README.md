# my-project-manager

An **autonomous LangGraph (Python) agent** that does the repetitive **management** work (PM / Scrum Master / Team Lead) for an AI-native team — it reads project state across **Jira · GitHub · Confluence · Slack**, reasons about it, and *acts* (writes reports, flags risk, tracks OKRs) like a real PM would. Not a chatbot you ask questions — an agent that works on its own schedule.

The interesting part isn't the reporting. It's that the agent has **full autonomous write authority** (it posts to Slack, creates Confluence pages, could create Jira tickets) — and yet is **safe**, because every mutation flows through a single guardrail: the **Action Gateway**.

> **The core idea, in one line:** *autonomous about speed, never about responsibility.* Permanent-data-loss and security are hard red lines the agent literally cannot cross, even if the LLM "wants" to.

📖 **If you're here to learn how to build a guardrailed autonomous agent, start with [docs/action-gateway-explainer.md](docs/v1/action-gateway-explainer.md)** — the standalone walkthrough of the safety model.

---

## What it does (all built + E2E-verified)

| Report | Command | What it produces |
|---|---|---|
| Daily standup | `report --daily` | Risk digest (overdue, blockers, stale PRs, CI failures) → Slack + Confluence |
| Weekly sprint review | `report --weekly` | Sprint progress + embedded OKR & resource sections |
| OKR status | `report --okr` | Reads an OKR table from Confluence → rolls up weighted progress from Jira epics |
| Resource & cost | `report --resource` | Per-assignee workload (overload vs team mean) + LLM-budget + labor estimate |
| Any of the above, for stakeholders | `... --audience external` | Business-tone summary → posts to a stakeholder channel **via human approval** |

Runs on demand or on a schedule (launchd cron). Read paths use [MCP servers](#external-dependency-3-mcp-servers) (Jira/Confluence/Slack) + the `gh` CLI (GitHub).

## The Action Gateway (why this repo is worth reading)

Every write the agent makes passes through one choke point that applies, in order:

```
request → [Lớp A hard-deny] → [Lớp B interrupt? → queue for human approval]
        → [kill-switch] → [dry-run?] → [rate-limit]
        → [idempotency dedup (reserve-before-execute)]
        → [execute handler] → [immutable audit log] → return
```

- **Lớp A (red line, hard-coded, never reaches the LLM):** permanent data loss, credential exfiltration, security incidents. Denied at the gateway — *not* a decision the LLM gets to make.
- **Lớp B (human-in-the-loop):** merge/close a PR, reassign a real person, post to an **external stakeholder** channel. Queued; a human approves before it executes.
- **Allowlist, not denylist:** unknown tools are denied by default (we switched after adversarial review found denylist bypasses — see [the Phase 0 journal](docs/journals/260621-phase-0-scaffold.md)).
- Plus: append-only audit log with secret redaction, `DRY_RUN` default in dev, a kill switch, a $50/month OpenRouter budget cap with hard-stop, and persistent dedup so re-runs never double-post.

Full walkthrough: **[docs/action-gateway-explainer.md](docs/v1/action-gateway-explainer.md)**. Code: [`src/actions/action_gateway.py`](src/actions/action_gateway.py) + [`src/actions/hard_block.py`](src/actions/hard_block.py).

## Quickstart

```bash
# 1. Clone + install (uses uv; Python 3.12)
git clone git@github.com:phuc-nt/my-project-manager.git
cd my-project-manager
uv sync

# 2. Verify the install (no network, no secrets needed)
uv run pytest            # 269 tests should pass
uv run ruff check src tests

# 3. Configure (see docs/deployment-guide.md for each value)
cp config.example.env .env
# fill in: OPENROUTER_API_KEY, Atlassian + Slack tokens, JIRA_PROJECT_KEY, GITHUB_REPO, channels

# 4. Build the 3 MCP servers it talks to (see "External dependency" below)

# 5. Run — DRY_RUN=true by default, so this logs what it WOULD do, posts nothing
uv run python -m src.entrypoints.cli report --daily
```

To post for real, set `DRY_RUN=false` in `.env`. See [docs/deployment-guide.md](docs/v1/deployment-guide.md) for secrets, scoped tokens, cron (launchd), and the kill switch.

### External dependency: 3 MCP servers

Jira, Confluence, and Slack are reached through **Model Context Protocol** servers (Node, stdio) that the agent spawns as subprocesses. GitHub uses the `gh` CLI. Clone + build the three servers (each has its own README):

- Jira → [github.com/phuc-nt/jira-cloud-mcp-server](https://github.com/phuc-nt/jira-cloud-mcp-server)
- Confluence → [github.com/phuc-nt/confluence-cloud-mcp-server](https://github.com/phuc-nt/confluence-cloud-mcp-server)
- Slack (browser-token) → [github.com/phuc-nt/slack-browser-mcp-server](https://github.com/phuc-nt/slack-browser-mcp-server)

```bash
cd ~/workspace && git clone <each repo> && cd <repo> && npm install && npm run build
```

Point the agent at them with `JIRA_MCP_DIST` / `CONFLUENCE_MCP_DIST` / `SLACK_MCP_DIST` in `.env` if they aren't at the default `~/workspace/*-mcp-server` paths.

## How it's built (the LangGraph core)

`perceive → analyze → compose → deliver`, an explicit graph (no hidden agentic loop). State is checkpointed (SQLite) and holds only primitives. Tools are a read layer (`src/tools/`); every mutation is a write layer behind the Action Gateway (`src/actions/`). Entry points (`src/entrypoints/`) are thin — the agent core knows nothing about CLI vs cron, so a service/bot frontend is additive later.

Architecture: [docs/system-architecture.md](docs/v1/system-architecture.md) · Code map: [docs/codebase-summary.md](docs/v1/codebase-summary.md)

## Documentation

| Read this to… | Doc |
|---|---|
| Understand the guardrail (the main lesson) | [action-gateway-explainer.md](docs/v1/action-gateway-explainer.md) |
| Understand the problem + vision | [project-overview-pdr.md](docs/v1/project-overview-pdr.md) |
| Understand the architecture | [system-architecture.md](docs/v1/system-architecture.md) |
| Find where any piece of code lives | [codebase-summary.md](docs/v1/codebase-summary.md) |
| Set up + run it | [deployment-guide.md](docs/v1/deployment-guide.md) |
| See how it compares to other agent harnesses | [architecture-comparison.md](docs/architecture-comparison.md) — vs DeerFlow 2.0, Hermes, OpenClaw/Pi.dev |
| See where it's headed next | [v2/](docs/v2/README.md) — multi-agent platform: profiles, registry/workers, web dashboard (draft) |
| **Follow the build, decision by decision** | [journals/](docs/journals/) — a phase-by-phase narrative with *what we decided & why* and *what broke & what we learned* |

The [journals](docs/journals/) are the best learning material here: each phase records the real decisions and the bugs adversarial review caught (denylist→allowlist, a JQL-injection surface, a privacy leak via a linked artifact). Build narratives like this are rare — that's the point of sharing this repo.

## Status

**Phases 0–5 complete** (2026-06-22) — reporting, guardrail hardening, OKR, resource/cost, and audience-split, all E2E-verified against real Jira/GitHub/Slack/Confluence. 269 tests, ruff clean. See [docs/project-roadmap.md](docs/v1/project-roadmap.md).

**Deferred (a separate, larger effort):** an HTTP service backend + a real Slack bot UI + multi-user. The current Slack MCP server is send-only (browser-token, no inbound events), so an interactive bot needs new infrastructure.

## License

[Apache 2.0](LICENSE).

## Reference / acknowledgement

Architectural patterns were studied (not copied) from production LangGraph harnesses; see [docs/research/](docs/research/) for external study notes.
