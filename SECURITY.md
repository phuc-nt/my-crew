# Security Policy

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability). Do not open public issues for security
reports. You should get a first response within a week.

## Threat model (what this project defends)

my-crew is an autonomous agent system with **write authority** over external
systems (Jira, Confluence, Slack, Telegram, email). The security posture is
architectural, not prompt-based:

- **Action Gateway** — every mutation passes one choke point:
  hard-deny (Lớp A) → trust-mode gate (Lớp B) → kill-switch → dry-run →
  rate-limit → dedup → execute → audit.
- **Lớp A red lines** are hard-coded and evaluated *before* any LLM output is
  consulted: permanent data loss, credential exfiltration, security incidents.
  No prompt, profile, or jailbreak reaches that code path.
- **Allowlist, not denylist**: unknown tools are denied by default.
- **Secrets**: live in `.env` under `MY_CREW_HOME` (never committed, never
  audited in plaintext); MCP server tokens are injected per-subprocess; the
  audit log redacts secret patterns.
- **Web dashboard**: binding a non-loopback host with auth disabled is refused
  at startup; sessions are signed; login is rate-limited.
- **deep_agent tier**: LLM-driven shell runs ONLY inside a hardened Docker
  sandbox (cap_drop ALL, no-new-privileges, network off by default,
  non-root, sanitized inputs) — never on the host.

Reports that demonstrate a path around the Gateway, a Lớp A bypass, secret
exfiltration, or sandbox escape are the highest priority. Full walkthrough:
[docs/action-gateway-explainer.md](docs/action-gateway-explainer.md).
