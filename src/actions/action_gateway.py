"""Action Gateway — the single authorized path for every mutation (PDR §7, §5).

No module may call a write API (MCP write tool, `gh` mutating command) directly.
Everything goes through `ActionGateway.execute()`, which runs this chain:

    Lớp A hard-deny -> Lớp B interrupt (queue for approval) -> deny-if-blocked
        -> kill-switch -> dry-run -> rate-limit -> idempotency -> execute -> audit

Each stage can short-circuit. Every outcome is audited. This is the invariant
that makes "full autonomous write" safe: autonomous in speed, never in
accountability.

Lớp B (sensitive-but-reversible: merge/close PR, close/transition/assign issue)
is queued via the approval store and only run later through `approve()` — never
auto-executed. Lớp A (data-loss/credential/security) is never overridable, even
by `approve()`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from src.actions.approval_store import ApprovalStore
from src.actions.dedup_store import DedupStore
from src.actions.hard_block import BlockCategory, classify, needs_interrupt
from src.audit.audit_log import AuditEntry, AuditLog
from src.config.settings import Settings

logger = logging.getLogger(__name__)

# Mutating action types this gateway governs. READ actions do not pass here.
_MUTATING_TYPES = {"mcp_tool", "gh_cli"}

# Rate limit: max mutations per rolling window (blast-radius cap, PDR §7.5).
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW_S = 60.0


class HardBlockedError(RuntimeError):
    """Raised when an action matches the Lớp A hard-block list."""


class WriteDisabledError(RuntimeError):
    """Raised when the kill switch (AGENT_WRITE_DISABLED) is on."""


class RateLimitedError(RuntimeError):
    """Raised when too many mutations happen within the rate-limit window."""


class Handler(Protocol):
    """A real write handler (Phase 1+). Receives the action, returns a summary."""

    def __call__(self, action: dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class GatewayResult:
    """Outcome of a gateway call."""

    # "executed" | "dry_run" | "skipped" | "deduplicated" | "pending_approval"
    status: str
    summary: str
    audited: bool = True
    approval_id: int | None = None  # set when status == "pending_approval"


def _action_dedup_key(action: dict[str, Any]) -> str:
    """Stable idempotency key for an action (PDR §7.6).

    If the action carries an explicit `dedup_hint`, use it — this lets callers
    dedup on a semantic identity (e.g. one report per day+channel) rather than
    on volatile content like LLM-generated text that changes every run. Falls
    back to hashing the whole action when no hint is given.
    """
    hint = action.get("dedup_hint")
    if isinstance(hint, str) and hint:
        # Namespace the hint by the action's tool identity so a hint can only
        # dedup within the same tool — two different tools sharing a hint string
        # must not collide and silently drop one mutation.
        return f"hint:{_label(action)}:{hint}"
    canonical = json.dumps(action, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _label(action: dict[str, Any]) -> str:
    """Human-readable tool label for audit, e.g. 'confluence:deletePage'."""
    atype = action.get("type", "?")
    if atype == "mcp_tool":
        return f"{action.get('server', '?')}:{action.get('tool', '?')}"
    if atype == "gh_cli":
        argv = action.get("argv", [])
        return "gh " + " ".join(str(a) for a in argv[:3])
    return str(atype)


class ActionGateway:
    """The one place mutations are authorized, executed, and audited."""

    def __init__(
        self,
        settings: Settings,
        audit_log: AuditLog | None = None,
        dedup_store: DedupStore | None = None,
        approval_store: ApprovalStore | None = None,
        external_channels: frozenset[str] | None = None,
    ) -> None:
        self._settings = settings
        self._recent_calls: deque[float] = deque()
        # External/stakeholder channels route Slack posts through Lớp B approval.
        # Injected by every real construction (from the per-flow config); defaults
        # to empty — a gateway with no external channels classifies none via channel.
        self._external_channels = (
            external_channels if external_channels is not None else frozenset()
        )
        # Stores: paths follow this gateway's settings data_dir (per-agent in v2) so
        # tests stay isolated to their tmp dir; dedup + approval survive restarts.
        data_dir = self._settings.data_dir
        self._audit = audit_log or AuditLog(data_dir / "audit" / "audit.jsonl")
        self._dedup = dedup_store or DedupStore(data_dir / "dedup.db")
        self._approvals = approval_store or ApprovalStore(data_dir / "approvals.db")

    def execute(
        self,
        action: dict[str, Any],
        *,
        handler: Handler | None = None,
        rationale: str = "",
    ) -> GatewayResult:
        """Run one action through the full guard chain. Audits every outcome.

        Public entry: a Lớp B action is queued for approval, never auto-run. The
        approval-bypass is NOT exposed here — only `approve()` can run a queued
        Lớp B action (and only past a NOT_ALLOWLISTED block, never past Lớp A).
        """
        return self._execute(action, handler=handler, rationale=rationale, approved=False)

    def _execute(
        self,
        action: dict[str, Any],
        *,
        handler: Handler | None = None,
        rationale: str = "",
        approved: bool = False,
    ) -> GatewayResult:
        """Internal guard chain. `approved=True` (only from `approve()`) skips the
        Lớp B enqueue and lets the action past a NOT_ALLOWLISTED block. Lớp A
        hard-deny + audit + dry-run + kill-switch always apply.
        """
        skip_interrupt = approved
        if not isinstance(action, dict):
            raise ValueError(
                f"action must be a dict, got {type(action).__name__}; refused un-run."
            )
        action_type = str(action.get("type", "")).lower()
        if action_type not in _MUTATING_TYPES:
            raise ValueError(
                f"ActionGateway only handles mutating actions {_MUTATING_TYPES}; "
                f"got type={action_type!r}. READ actions bypass the gateway."
            )

        tool = _label(action)

        # 1. Hard-block (Lớp A) — denied in code, before anything else.
        verdict = classify(action)

        # 1b. Interrupt (Lớp B) — sensitive-but-reversible: queue for human approval.
        # Checked BEFORE the allowlist default-deny: a Lớp B action is "allowed but
        # needs a human", not "forbidden". But it can NEVER override a Lớp A hard-deny
        # (data-loss/credential/security), so only consider it when the block, if any,
        # is merely NOT_ALLOWLISTED. Skipped when running an already-approved action.
        if not skip_interrupt:
            interrupt = needs_interrupt(action, external_channels=self._external_channels)
            is_hard_deny = verdict.blocked and verdict.category != BlockCategory.NOT_ALLOWLISTED
            if interrupt.interrupt and not is_hard_deny:
                approval_id = self._approvals.enqueue(
                    action, reason=interrupt.reason, rationale=rationale
                )
                self._record(
                    action_type, tool, "pending", interrupt.reason, action, rationale
                )
                return GatewayResult(
                    status="pending_approval",
                    summary=f"{tool} queued for approval (id={approval_id}): {interrupt.reason}",
                    approval_id=approval_id,
                )

        # Deny on any block, EXCEPT: an approved Lớp B action (skip_interrupt) is
        # allowed past a mere NOT_ALLOWLISTED block — the human approval is the
        # authorization. A real Lớp A hard-deny is never overridable.
        if verdict.blocked:
            approved_lop_b = skip_interrupt and verdict.category == BlockCategory.NOT_ALLOWLISTED
            if not approved_lop_b:
                self._record(action_type, tool, "deny", verdict.reason, action, rationale)
                raise HardBlockedError(
                    f"Lớp A hard-block ({verdict.category.value if verdict.category else '?'}): "
                    f"{verdict.reason}"
                )

        # 2. Kill switch — global write off.
        if self._settings.write_disabled:
            self._record(action_type, tool, "deny", "kill switch on", action, rationale)
            raise WriteDisabledError(
                "AGENT_WRITE_DISABLED is on; all mutations are refused."
            )

        # 3. Dry-run — log intent, do not execute.
        if self._settings.dry_run:
            self._record(
                action_type, tool, "dry_run", "DRY_RUN on", action, rationale, dry_run=True
            )
            return GatewayResult(status="dry_run", summary=f"[dry-run] would run {tool}")

        # 4. Rate limit — blast-radius cap.
        self._check_rate_limit(action_type, tool, action, rationale)

        # 5. Idempotency — atomically RESERVE the key before executing. claim()
        # is INSERT-OR-IGNORE; if it returns False the key was already taken (by a
        # prior run OR a concurrent process), so this is a duplicate. Reserving
        # before execute closes the two-process double-execute window. If the
        # handler then fails, we release the reservation so a retry can run.
        key = _action_dedup_key(action)
        if not self._dedup.claim(key):
            self._record(action_type, tool, "skipped", "duplicate action", action, rationale)
            return GatewayResult(status="deduplicated", summary=f"duplicate {tool} skipped")

        # 6. Execute.
        if handler is None:
            self._dedup.release(key)  # nothing ran; don't hold the reservation
            self._record(
                action_type, tool, "skipped", "no handler (Phase 0)", action, rationale
            )
            return GatewayResult(status="skipped", summary=f"no handler for {tool}")

        try:
            summary = handler(action)
        except Exception as exc:  # explicit: audit the failure, then re-raise with context
            self._dedup.release(key)  # release so a retry can run after a failure
            self._record(action_type, tool, "deny", f"handler error: {exc}", action, rationale)
            raise RuntimeError(f"Handler for {tool} failed: {exc}") from exc

        self._record(
            action_type, tool, "allow", "executed", action, rationale, result=summary
        )
        return GatewayResult(status="executed", summary=summary)

    def pending_approvals(self):
        """List Lớp B actions awaiting human approval."""
        return self._approvals.list_pending()

    def approve(self, approval_id: int, *, handler: Handler) -> GatewayResult:
        """Execute a previously-queued Lớp B action after human approval.

        Runs the stored action through the gateway with the interrupt check
        skipped (the human IS the approval), but Lớp A hard-deny + audit still
        apply. Marks the approval consumed. Raises if the id is unknown or not
        pending.
        """
        pending = self._approvals.get(approval_id)
        if pending is None:
            raise ValueError(f"No approval with id={approval_id}.")
        # Atomically claim the transition pending->approved BEFORE executing, so two
        # concurrent approves of the same id can't both run the action.
        if not self._approvals.transition_if_pending(approval_id, "approved"):
            raise ValueError(f"Approval id={approval_id} is already {pending.status!r}.")
        try:
            return self._execute(
                pending.action,
                handler=handler,
                rationale=f"approved (id={approval_id})",
                approved=True,
            )
        except Exception:
            # Execution failed — revert so the human can retry the approval.
            self._approvals.set_status(approval_id, "pending")
            raise

    def reject(self, approval_id: int) -> None:
        """Mark a pending approval as rejected (not executed) and audit the decision."""
        pending = self._approvals.get(approval_id)
        self._approvals.set_status(approval_id, "rejected")
        if pending is not None:
            action_type = str(pending.action.get("type", "")).lower()
            self._record(
                action_type, _label(pending.action), "reject",
                f"rejected approval id={approval_id}", pending.action, "",
            )

    def _check_rate_limit(
        self, action_type: str, tool: str, action: dict[str, Any], rationale: str
    ) -> None:
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_S
        while self._recent_calls and self._recent_calls[0] < cutoff:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= _RATE_LIMIT_MAX:
            self._record(action_type, tool, "deny", "rate limit", action, rationale)
            raise RateLimitedError(
                f"Rate limit: more than {_RATE_LIMIT_MAX} mutations in "
                f"{_RATE_LIMIT_WINDOW_S:.0f}s."
            )
        self._recent_calls.append(now)

    def _record(
        self,
        action_type: str,
        tool: str,
        verdict: str,
        reason: str,
        action: dict[str, Any],
        rationale: str,
        *,
        dry_run: bool = False,
        result: str = "",
    ) -> None:
        self._audit.record(
            AuditEntry(
                action_type=action_type,
                tool=tool,
                verdict=verdict,
                reason=reason,
                params=action,
                result_summary=result,
                dry_run=dry_run,
                rationale=rationale,
            )
        )
