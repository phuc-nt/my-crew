# How the Action Gateway works — a guardrail for an autonomous write agent

> A standalone walkthrough of this project's core idea. If you read only one doc to learn
> *how to let an LLM agent write to real systems without it being a loaded gun*, read this one.
> Code: [`src/actions/action_gateway.py`](../../src/actions/action_gateway.py),
> [`src/actions/hard_block.py`](../../src/actions/hard_block.py).

## The problem

We gave the agent **full autonomous write authority** — it posts to Slack, creates Confluence
pages, and could create or transition Jira issues, with no human approving each action. That is
genuinely useful (a PM agent that needs a human click per post saves nobody time) and genuinely
dangerous (an LLM with a bug, a bad prompt, or a hallucination can delete a branch, leak a token,
or make a private repo public).

The guiding principle we landed on:

> **Autonomous about speed, never about responsibility.**
> Permanent data loss and security incidents are red lines the agent *cannot* cross — not because
> the LLM is told not to, but because the code makes it impossible.

The mechanism is a single **choke point**: no module calls a write API directly. Every mutation —
whether it goes through an MCP tool (Jira/Confluence/Slack) or the `gh` CLI (GitHub) — passes
through `ActionGateway.execute(action, handler)`. If you ever see a write that doesn't, that's a bug.

## The chain

`execute()` runs each mutation through this chain, in this exact order (see `_execute()` in the code):

```
request
  → [1.  Lớp A hard-deny]      data-loss / credential / security → DENIED in code
  → [1b. Lớp B interrupt?]     sensitive-but-reversible → QUEUE for human approval, stop here
  → [2.  kill switch]          AGENT_WRITE_DISABLED → refuse all writes
  → [3.  dry-run?]             DRY_RUN=true → log intent, execute nothing
  → [4.  rate limit]           cap writes/minute → blast-radius limit
  → [5.  idempotency dedup]    reserve-before-execute → no double-post on re-run
  → [6.  execute handler]      the real side effect, finally
  → [7.  immutable audit log]  append-only, secrets redacted
  → return
```

Order is not arbitrary. Two ordering decisions carry the whole safety model:

- **Lớp A is checked first, in code, before the LLM's choice ever matters.** The LLM doesn't get a
  vote on whether to delete a branch — `classify(action)` denies it before execution.
- **Lớp B is checked *before* the allowlist default-deny**, but can *never* override a Lớp A deny.
  (Why this subtlety exists is explained under "Two layers" below.)

## Two layers of "no"

Not every dangerous action is the same kind of dangerous. We split them:

### 🚫 Lớp A — the red line (hard-deny, never reaches the LLM)

Hard-coded denials at the gateway. The agent **never** does these, even if the LLM "wants" to:

- **Permanent data loss:** `git push --force`, deleting a commit/branch/tag, deleting a Jira issue,
  overwriting a Confluence page without versioning, `rm`-ing data.
- **Credential exfiltration:** reading a token/key/secret and sending it anywhere (a Slack message,
  a Jira comment, an HTTP request to an unknown host, an un-redacted log).
- **Security incidents:** changing visibility (making a private repo/page public), granting
  permissions, inviting outsiders, disabling a security setting.

`classify()` ([`hard_block.py`](../../src/actions/hard_block.py)) inspects the **MCP tool name + args**
or the **`gh` command line** — not Python SDK calls — and returns a block with a category. A Lớp A
block is final: it is never overridable, not even by human approval.

### ⏸️ Lớp B — human-in-the-loop (queue, don't auto-run)

Reversible-but-consequential actions that *sometimes* legitimately need doing:

- merge / close a PR, close / transition / reassign a real person's issue,
- post to an **external stakeholder / customer** channel.

These don't get denied — they get **queued**. `execute()` returns `pending_approval` with an
`approval_id`; a human runs `cli approve <id>` and *only then* does the action execute (re-entering
the gateway, where Lớp A + audit still apply, but the Lớp B prompt is skipped — the human approval
*is* the authorization).

### The subtle ordering, and why it matters

Lớp B is checked **before** the allowlist's default-deny, but only fires when the action isn't a
true Lớp A hard-deny. The reason: a Lớp B action (e.g. "merge this PR") is *"allowed, but ask a
human"* — not *"forbidden"*. If we checked the allowlist first, a not-yet-allowlisted Lớp B action
would be denied outright instead of queued. But we must also guarantee a Lớp B-*shaped* action that
is *actually* Lớp A (e.g. `gh pr merge --delete-branch` — looks like a merge, but deletes data)
still hits the red line. So the rule is: **consider Lớp B only when the block, if any, is merely
`NOT_ALLOWLISTED`.** This invariant is verified with adversarial payloads in the tests.

## Allowlist, not denylist

The gateway's default verdict is **deny**. Only an explicit allowlist of `(server, tool)` pairs and
`gh` sub-commands gets through; everything unknown is refused.

This wasn't the first design. We started with a *denylist* (block known-bad, allow the rest). An
adversarial code review found real bypasses — secrets leaking into the immutable audit log as
free text, `gh api` doing implicit-POST writes, glued-verb commands sneaking past string matches.
A denylist lets through everything you didn't think to forbid, which is exactly the wrong default
for a red line. We switched to allowlist + Lớp-A-first. The full story is in
[the Phase 0 journal](../journals/260621-phase-0-scaffold.md) — it's a good lesson in why "secure by
default" means *deny* by default.

## The supporting guarantees

The two layers are the headline, but they only hold up because of the rest:

| Guarantee | What it does | Where |
|---|---|---|
| **Immutable audit log** | Every write (tool, params, result, timestamp, the agent's rationale) appended to JSONL, with secrets redacted by a shared pattern set. No audit = no write. | `src/audit/audit_log.py`, `src/actions/secret_patterns.py` |
| **Dry-run default** | `DRY_RUN=true` (the dev default) logs what it *would* do and executes nothing. Posting for real is an explicit opt-in. | gateway step 3 |
| **Kill switch** | `AGENT_WRITE_DISABLED` refuses all mutations instantly. | gateway step 2 |
| **Rate / blast-radius limit** | Caps writes per minute, so a looping bug can't spam 500 tickets. | gateway step 4 |
| **Idempotency (reserve-before-execute)** | A persistent dedup store claims a key *before* executing, so a re-run (or a cron + manual race) never double-posts the same day's report. | `src/actions/dedup_store.py` |
| **Budget cap** | $50/month OpenRouter cap with an 80% warning and a 100% hard-stop — an autonomous loop with a bug can burn money fast. | `src/llm/budget_tracker.py` |
| **Secret redaction** | The same `secret_patterns` module powers the gateway's credential hard-deny *and* the audit redaction *and* the approval store — so what the gateway blocks is exactly what the log hides. One source of truth, no drift. | `src/actions/secret_patterns.py` |

## Things we learned (the hard way)

These are the bugs adversarial review caught *after* the design looked done — the real teaching value:

- **Denylist → allowlist** (Phase 0): the original denylist let unexamined writes + free-text secrets
  through. Default-deny is the only safe default for a red line.
- **A "bypass flag" must be private** (Phase 2): a public `skip_interrupt=True` kwarg on `execute()`
  would let any caller defeat Lớp B. It became a private `_execute(approved=...)` only reachable via
  `approve()`.
- **The approval store is a second copy of the action → it must redact too** (Phase 2): anything
  that persists an action must run the same secret redaction as the audit log.
- **Validate external input before it reaches a query language** (Phase 3): user-typed epic keys from
  a Confluence table flowed unsanitized into JQL — an injection surface. Validate at the boundary.
- **Privacy is about linked artifacts, not just text** (Phase 5): an "external" report's Slack message
  was clean, but it *linked* a Confluence page that still exposed per-person workload + cost. The leak
  was one click away. Sanitize the whole reachable surface, not just the immediate output.

Each is written up in [the journals](../journals/) under "Vấp & học được" (what broke → what we learned).

## How to read the code

1. [`src/actions/action_gateway.py`](../../src/actions/action_gateway.py) — `_execute()` *is* the chain
   above, top to bottom. Start here.
2. [`src/actions/hard_block.py`](../../src/actions/hard_block.py) — `classify()` (Lớp A + allowlist) and
   `needs_interrupt()` (Lớp B). The actual red-line logic.
3. A real write that uses it: [`src/actions/slack_write.py`](../../src/actions/slack_write.py) — note it
   never calls the Slack API directly; it hands the gateway an `action` + a `handler` and lets the
   chain run.

Then read [system-architecture.md §5](system-architecture.md) for how the gateway sits between the
LangGraph agent core and the outside world.
