# my-crew

[![ci](https://github.com/phuc-nt/my-crew/actions/workflows/ci.yml/badge.svg)](https://github.com/phuc-nt/my-crew/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/my-crew)](https://pypi.org/project/my-crew/)

*[Tiếng Việt](README.vi.md)*

An **autonomous LangGraph (Python) agent** that does the repetitive **management** work (PM / Scrum Master / Team Lead) for an AI-native team — it reads project state across **Jira · GitHub · Confluence · Slack**, reasons, and *acts* (writes reports, flags risk, tracks OKRs) on its own schedule. Not a chatbot you ask — an agent that works.

The interesting part isn't the reporting. It's that the agent has **full autonomous write authority** by default — yet is safe, because every mutation flows through one guardrail: the **Action Gateway**.

> **Core idea, in one line:** *autonomy-first with locked guardrails and full audit.* Data-loss and security are hard red lines the agent literally cannot cross, even if the LLM "wants" to. Speed is the default; caution is one-line opt-in per agent.

## Why this repo exists

Most "AI agent" projects bolt tools onto a model and hope it behaves. This one flips it: **guardrail first, autonomy second** — trust enforced by architecture, not by prompting. Three convictions:

1. **Autonomy is the default, not a reward.** The agent runs on a schedule and acts without asking; approve-before-write is a per-agent opt-in.
2. **Some lines the LLM never crosses.** Data loss, credential exfiltration, security incidents — denied at the gateway *before* the model is consulted (**Lớp A**), hard-coded, unreachable by any prompt or jailbreak.
3. **A real harness, not a demo.** A model with tools isn't an agent. This is the whole environment: scheduler, layered memory, budget, hooks (PII firewall + approval-gate), an immutable audit log, and the Gateway every write must pass.

## The Action Gateway (the one thing worth reading)

Every write passes through one choke point:

```
request → [Lớp A hard-deny] → [Lớp B: autonomous auto-approve OR guarded queue?]
        → [kill-switch] → [dry-run?] → [rate-limit] → [dedup] → [execute] → [audit log]
```

- **Lớp A** (red line, hard-coded, never reaches the LLM): permanent data loss, credential exfiltration, security incidents.
- **Lớp B** (trust-mode dependent): merge/close PR, reassign, post to external channel — *autonomous* (execute + audit) by default, *guarded* (queue for approval) when opted in.
- **Allowlist, not denylist:** unknown tools are denied by default (switched after adversarial review found denylist bypasses).

Full walkthrough: **[docs/action-gateway-explainer.md](docs/action-gateway-explainer.md)**.

## What it grew into

One PM agent (daily/weekly/OKR/resource reports) became a **CEO-operated virtual-staff company**: many isolated agents, a browser dashboard, a 3D office, one-click staff templates, chat-ops, multi-runtime tiers (native / tool-calling / sandboxed deep-agent). The safety invariant held across every step. Full history: **[docs/project-roadmap.md](docs/project-roadmap.md)**.

## Documentation

| To… | Doc |
|---|---|
| **Use it (tiếng Việt)** — install + daily operation | [huong-dan-su-dung.md](docs/huong-dan-su-dung.md) |
| **Set up + run** — secrets, MCP servers, cron | [deployment-guide.md](docs/deployment-guide.md) |
| Understand the guardrail (the main lesson) | [action-gateway-explainer.md](docs/action-gateway-explainer.md) |
| The problem + vision / the architecture | [project-overview-pdr.md](docs/project-overview-pdr.md) · [system-architecture.md](docs/system-architecture.md) |
| **Follow the build, decision by decision** | [journals/](docs/journals/) — *what we decided & why*, *what broke & what we learned* |

The [journals](docs/journals/) are the best learning material here — each phase records the real decisions and the bugs adversarial review caught (denylist→allowlist, a JQL-injection surface, a privacy leak via a linked artifact).

## Install & first run (5 minutes)

```bash
uvx my-crew quickstart        # or: pipx install my-crew && my-crew quickstart
```

`quickstart` runs the starter agent's daily report **in dry-run** — it needs exactly
one thing, an `OPENROUTER_API_KEY` in `.env` (put it under `~/.my-crew/`), and can
never write anywhere external. From there:

```bash
my-crew serve                 # web dashboard + coordinator, foreground
# → http://127.0.0.1:8765 — the browser Setup Wizard takes the rest (secrets never
#   touch the terminal). Node.js is required for the Jira/Confluence/Slack servers.
```

Prefer containers? `deploy/docker/` has a Compose file (auth-first, state on a
volume). macOS operators can install background services with `./deploy/install.sh`.
Full setup — integrations, cron, trust modes: **[docs/deployment-guide.md](docs/deployment-guide.md)**.

## Evaluate the code

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew && uv sync
uv run pytest    # 2360 BE + 201 FE tests pass, no secrets needed
```

`DRY_RUN=true` by default everywhere — the agent logs what it *would* do, posts nothing, until you flip it.

## License

[Apache 2.0](LICENSE). Architectural patterns were studied (not copied) from production LangGraph harnesses; see [docs/research/](docs/research/).
