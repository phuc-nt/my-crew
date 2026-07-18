"""Inbox transport dispatch (v6 M13) — one `inbox` tick runs every configured transport.

The worker's `inbox` pseudo-kind predates multi-transport: it used to mean "the Slack
inbox". Now an agent may declare a Slack `inbox:` block, a `telegram:` block, or both —
this module fans one tick out to each configured poller and merges the results into the
single run-event shape the worker records.

Backward-compat is load-bearing: with ONLY the Slack inbox configured, the Slack
result is returned unchanged (byte-identical to pre-M13); same for telegram-only.
"""

from __future__ import annotations

import logging
from typing import Any

from my_crew.profile.loader import LoadedProfile

logger = logging.getLogger(__name__)


def _telegram_config(loaded: LoadedProfile):
    """The agent's TelegramConfig or None. getattr-tolerant like the pre-M13 schedule
    fold: scheduler tests drive this with minimal profile stubs."""
    return getattr(getattr(loaded, "config", None), "telegram", None)


def has_any_inbox(loaded: LoadedProfile) -> bool:
    """True when at least one inbox transport is configured for this agent."""
    return bool(getattr(loaded, "inbox", None)) or _telegram_config(loaded) is not None


def inbox_poll_minutes(loaded: LoadedProfile) -> int:
    """The tick cadence: the FASTEST configured transport wins (both run each tick;
    the slower one simply sees an empty poll more often — polls are cheap, LLM calls
    only happen when there is something to answer)."""
    candidates = []
    if getattr(loaded, "inbox", None):
        candidates.append(int(loaded.inbox["poll_minutes"]))
    telegram = _telegram_config(loaded)
    if telegram is not None:
        candidates.append(int(telegram.poll_minutes))
    if not candidates:
        raise RuntimeError(f"agent {loaded.profile_id!r} has no inbox transport configured")
    return min(candidates)


def run_all_inboxes(loaded: LoadedProfile, settings: Any) -> dict:
    """Run every configured inbox transport once; merge into one run-event result.

    A transport that CRASHES (unexpected exception) does not stop the other: the error
    is logged, recorded in the status, and the merged result still reflects whatever the
    other transport did. Raises only when NO transport is configured (a worker dispatch
    bug, not a runtime condition).
    """
    results: dict[str, dict] = {}
    if getattr(loaded, "inbox", None):
        from my_crew.runtime.inbox import run_inbox

        try:
            results["slack"] = run_inbox(loaded, settings)
        except Exception:  # noqa: BLE001 — one transport must not silence the other
            logger.exception("inbox %s: slack transport failed", loaded.profile_id)
            results["slack"] = {"status": "error", "replied": 0, "cost_usd": None,
                                "delivered": False}
    if _telegram_config(loaded) is not None:
        from my_crew.runtime.telegram_inbox import run_telegram_inbox

        try:
            results["telegram"] = run_telegram_inbox(loaded, settings)
        except Exception:  # noqa: BLE001
            logger.exception("inbox %s: telegram transport failed", loaded.profile_id)
            results["telegram"] = {"status": "error", "replied": 0, "cost_usd": None,
                                   "delivered": False}
    if not results:
        raise RuntimeError(
            f"agent {loaded.profile_id!r} has no inbox: block and no telegram: block"
        )
    if len(results) == 1:
        return next(iter(results.values()))  # single transport ⇒ byte-identical result

    costs = [r["cost_usd"] for r in results.values() if r.get("cost_usd") is not None]
    return {
        "status": ";".join(f"{name}={r['status']}" for name, r in sorted(results.items())),
        "replied": sum(int(r.get("replied") or 0) for r in results.values()),
        "cost_usd": sum(costs) if costs else None,
        "delivered": any(bool(r.get("delivered")) for r in results.values()),
    }
