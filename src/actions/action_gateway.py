"""Action Gateway — the single authorized path for every mutation (PDR §7, §5).

No module may call a write API (MCP write tool, `gh` mutating command) directly.
Everything goes through `ActionGateway.execute()`, which runs this chain:

    hard-block (Lớp A) -> kill-switch -> dry-run -> rate-limit -> idempotency
        -> execute handler -> audit -> return

Each stage can short-circuit. Every outcome is audited. This is the invariant
that makes "full autonomous write" safe: autonomous in speed, never in
accountability.

Phase 0 scope: the guard chain is complete, but there are no real write handlers
yet (Phase 1). `execute()` accepts an optional handler; with none, it records a
"skipped (no handler)" outcome. Lớp B (ask-human interrupt) is a Phase 1/2 hook,
intentionally not faked here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

from src.actions.hard_block import classify
from src.audit.audit_log import AuditEntry, AuditLog
from src.config.settings import Settings, get_settings

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

    status: str  # "executed" | "dry_run" | "skipped" | "deduplicated"
    summary: str
    audited: bool = True


def _action_dedup_key(action: dict[str, Any]) -> str:
    """Stable hash of an action for idempotency (PDR §7.6)."""
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
        settings: Settings | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._audit = audit_log or AuditLog()
        self._recent_calls: deque[float] = deque()
        self._seen_keys: set[str] = set()

    def execute(
        self,
        action: dict[str, Any],
        *,
        handler: Handler | None = None,
        rationale: str = "",
    ) -> GatewayResult:
        """Run one action through the full guard chain. Audits every outcome."""
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
        if verdict.blocked:
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

        # 5. Idempotency — skip exact re-runs.
        key = _action_dedup_key(action)
        if key in self._seen_keys:
            self._record(action_type, tool, "skipped", "duplicate action", action, rationale)
            return GatewayResult(status="deduplicated", summary=f"duplicate {tool} skipped")

        # 6. Execute.
        if handler is None:
            self._record(
                action_type, tool, "skipped", "no handler (Phase 0)", action, rationale
            )
            return GatewayResult(status="skipped", summary=f"no handler for {tool}")

        try:
            summary = handler(action)
        except Exception as exc:  # explicit: audit the failure, then re-raise with context
            self._record(action_type, tool, "deny", f"handler error: {exc}", action, rationale)
            raise RuntimeError(f"Handler for {tool} failed: {exc}") from exc

        self._seen_keys.add(key)
        self._record(
            action_type, tool, "allow", "executed", action, rationale, result=summary
        )
        return GatewayResult(status="executed", summary=summary)

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
