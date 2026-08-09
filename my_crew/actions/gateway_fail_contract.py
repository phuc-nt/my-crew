"""Gateway fail-mode contract (v76, learned from my-dandori `govern/contract.go`).

my-crew's gateway was always default-deny WHEN IT COULD EVALUATE. This module answers
the question that used to live implicitly in exception handlers: **what happens when a
checkpoint itself cannot run** (SQLite locked, store corrupt, notifier down). One
declarative table, one rule:

  - a check that runs BEFORE the side-effect fails CLOSED (the action does not run);
  - capture/notify-only paths fail OPEN (telemetry must never block work).

`CHECKPOINT_FAIL_MODES` is the single source of truth; the contract test enumerates it
and asserts each real code path matches. Changing a mode here without changing the
code (or vice versa) fails the suite — the table can never rot into documentation.

Break-glass: `MYCREW_GATEWAY_FAIL_OPEN=1` (env ONLY — the stores that could be broken
are exactly where a config flag would live) lets a *store-unavailable* Lớp B checkpoint
degrade to its no-op answer instead of blocking every external write. It NEVER touches
Lớp A hard-deny, the kill-switch, dry-run, or rate-limit — those evaluate in pure code
with no store to break. Every activation is logged and audited.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

FAIL_CLOSED = "fail_closed"  # check breaks → the action is NOT executed
FAIL_OPEN = "fail_open"  # check breaks → logged, the action path continues

#: The declarative contract. Keys mirror the checkpoint order in
#: `ActionGateway._execute` (module docstring chain) + its side channels.
CHECKPOINT_FAIL_MODES: dict[str, str] = {
    # Pure-code checks — no store to break; an exception is a programmer error and
    # must surface (the action does not run): closed by construction.
    "lop_a_classify": FAIL_CLOSED,
    "lop_b_interrupt": FAIL_CLOSED,
    "kill_switch": FAIL_CLOSED,
    "dry_run": FAIL_CLOSED,
    "rate_limit": FAIL_CLOSED,
    # Store-backed Lớp B checkpoints — closed by default; break-glass (env) degrades
    # each to its documented no-op answer ("no rule matched" / "no auto-approve slot")
    # or, for the queue itself, to an autonomous-style run with a break-glass audit row.
    "learned_rules": FAIL_CLOSED,
    "auto_approve_ladder": FAIL_CLOSED,
    "approval_enqueue": FAIL_CLOSED,
    # Dedup guards against double-posting — failing open would risk a duplicate
    # external write, so it stays closed even under break-glass.
    "dedup": FAIL_CLOSED,
    # "No audit => no write" is a founding invariant (PDR §7.1) — audit is NOT
    # telemetry here, it is a precondition of the write.
    "audit_record": FAIL_CLOSED,
    # Conveniences AROUND the decision — never allowed to affect it.
    "approval_push_notify": FAIL_OPEN,
    "office_bridge": FAIL_OPEN,
}

_ENV_FLAG = "MYCREW_GATEWAY_FAIL_OPEN"


def break_glass_active() -> bool:
    """True when the operator set the break-glass env. Read from the ENVIRONMENT on
    every call (never from a store/config file — those are exactly what may be broken
    when this flag matters). Callers log + audit each activation."""
    return os.environ.get(_ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def log_break_glass(checkpoint: str, error: Exception) -> None:
    """One loud line per activation — break-glass use must never be silent."""
    logger.warning(
        "BREAK-GLASS (%s=1): checkpoint %r unavailable (%s) — degrading to its no-op "
        "answer. Lớp A / kill-switch / dry-run / rate-limit / dedup are NOT relaxed.",
        _ENV_FLAG, checkpoint, error,
    )
