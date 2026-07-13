# my-crew

An **autonomous LangGraph (Python) agent** that does the repetitive **management** work (PM / Scrum Master / Team Lead) for an AI-native team — it reads project state across **Jira · GitHub · Confluence · Slack**, reasons about it, and *acts* (writes reports, flags risk, tracks OKRs) like a real PM would. Not a chatbot you ask questions — an agent that works on its own schedule.

The interesting part isn't the reporting. It's that the agent has **full autonomous write authority** by default (it posts to Slack, creates Confluence pages, could create Jira tickets) — and yet is **safe**, because every mutation flows through a single guardrail: the **Action Gateway**.

> **The core idea, in one line:** *autonomy-first with locked guardrails and full audit.* Permanent-data-loss and security are hard red lines the agent literally cannot cross, even if the LLM "wants" to. Speed is the default; caution is one-line opt-in per agent.

📖 **If you're here to learn how to build a guardrailed autonomous agent, start with [docs/action-gateway-explainer.md](docs/action-gateway-explainer.md)** — the standalone walkthrough of the safety model.

---

## Why this repo exists

Most "AI agent" projects bolt tools + skills onto a model and hope it behaves. This one takes the opposite stance: **the guardrail comes first, autonomy second.** The bet is that an agent you can *trust to act on its own* is worth more than one you must babysit — but only if "trust" is enforced by architecture, not by prompting.

Three convictions shape everything:

1. **Autonomy is the default, not a reward.** The agent runs on a schedule and acts without asking. Caution (approve-before-write) is an explicit per-agent opt-in, not the baseline. Speed is the point.
2. **Some lines the LLM never gets to cross.** Permanent data loss, credential exfiltration, and security incidents are denied at the gateway *before* the model is even consulted (**Lớp A**). No prompt, jailbreak, or bug in the model can reach them — the block is hard-coded, not a decision.
3. **Everything is a real harness, not a demo.** A model with tools is not an agent. A *real* harness needs a security gate + guardrails + observability around the model: scheduler, layered memory, budget, hooks (PII firewall + approval-gate), an immutable audit log, and the Action Gateway every write must pass. The guardrail isn't an add-on — it's an invariant, verified live.

## The Action Gateway (the one thing worth reading)

Every write the agent makes passes through one choke point:

```
request → [Lớp A hard-deny] → [Lớp B: autonomous auto-approve OR guarded queue?]
        → [kill-switch] → [dry-run?] → [rate-limit]
        → [idempotency dedup] → [execute] → [immutable audit log] → return
```

- **Lớp A (red line, hard-coded, never reaches the LLM):** permanent data loss, credential exfiltration, security incidents.
- **Lớp B (trust-mode dependent):** merge/close PR, reassign person, post to external channel — *autonomous* (execute + audit) by default, *guarded* (queue for human approval) when opted in.
- **Allowlist, not denylist:** unknown tools are denied by default (we switched after adversarial review found denylist bypasses).

Full walkthrough — the model, the layers, and the bugs adversarial review caught — is in **[docs/action-gateway-explainer.md](docs/action-gateway-explainer.md)**. The node-by-node harness map is in [docs/system-architecture.md](docs/system-architecture.md).

## What it grew into

It started as one PM agent producing daily/weekly/OKR/resource reports. It's now a **CEO-operated virtual-staff company**: many isolated agents across projects, a browser dashboard, a 3D virtual office, one-click staff templates, chat-ops, and multi-runtime tiers (native / tool-calling / sandboxed deep-agent). The safety invariant held across every step — that's the whole point.

The full feature history, version by version, lives in **[docs/project-roadmap.md](docs/project-roadmap.md)**.

## Documentation

| Read this to… | Doc |
|---|---|
| **Use the system (tiếng Việt)** — install + daily operation | [docs/huong-dan-su-dung.md](docs/huong-dan-su-dung.md) |
| **Set up + run it** — secrets, MCP servers, cron, kill switch | [docs/deployment-guide.md](docs/deployment-guide.md) |
| Understand the guardrail (the main lesson) | [docs/action-gateway-explainer.md](docs/action-gateway-explainer.md) |
| Understand the problem + vision | [docs/project-overview-pdr.md](docs/project-overview-pdr.md) |
| Understand the architecture | [docs/system-architecture.md](docs/system-architecture.md) |
| See what shipped, version by version | [docs/project-roadmap.md](docs/project-roadmap.md) |
| Find where any piece of code lives | [docs/codebase-summary.md](docs/codebase-summary.md) |
| **Follow the build, decision by decision** | [docs/journals/](docs/journals/) — *what we decided & why*, *what broke & what we learned* |

The [journals](docs/journals/) are the best learning material here: each phase records the real decisions and the bugs adversarial review caught (denylist→allowlist, a JQL-injection surface, a privacy leak via a linked artifact). Build narratives like this are rare — that's the point of sharing this repo.

## Try it

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew
uv sync
uv run pytest          # 2149 BE + 200 FE tests should pass, no secrets needed
```

`DRY_RUN=true` is the default — it logs what it *would* do and posts nothing. To configure secrets, build the 3 MCP servers it talks to, and go live, follow **[docs/deployment-guide.md](docs/deployment-guide.md)**.

## License

[Apache 2.0](LICENSE).

## Reference / acknowledgement

Architectural patterns were studied (not copied) from production LangGraph harnesses; see [docs/research/](docs/research/) for external study notes.
