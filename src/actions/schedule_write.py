"""schedule_update WRITE — an agent re-schedules ITS OWN reports (v31 P2).

The first fully-native action type after email/telegram: no MCP server, no argv — the
payload is `{"type": "schedule_update", "schedule": {kind: cron}, "dedup_hint": ...}`
and the executor is this handler, routed through the Action Gateway like every other
mutation (Lớp A scan + Lớp B queue in guarded / audited run-now in autonomous).

Self-only BY ARCHITECTURE: the action carries NO agent identity. The handler is a
closure over `profile_id`, built at a call site that already holds the agent's own
`loaded` profile (chat auto-handler, web/mpm approve). A hostile payload cannot point
the write at another agent because there is no field to smuggle the target in.

The handler RE-ENFORCES every policy the gateway's classify already checked (structure,
cron floor, entry cap) plus the checks only it can do (kind ∈ the domain pack's report
kinds, merged-map cap, per-day update cap) — it never assumes classify ran. Verdict
drift is prevented by sharing `cron_floor_error` with hard_block.

Write path: read profile.yaml → merge ONLY the `schedule:` key → `save_profile_yaml`
(validate-then-atomic). YAML comments/formatting in profile.yaml are LOST on this
round-trip (yaml.safe_load → safe_dump) — an accepted trade-off, documented in the
user guide. The new schedule takes effect on the service's next profile reload.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import yaml

from src.actions.hard_block import _SCHEDULE_MAX_ENTRIES, cron_floor_error

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]

#: Per-agent, per-local-day cap on EXECUTED schedule updates (red-team F2: autonomous
#: mode has no trust-ladder daily cap, so a chat-flatten sender could otherwise flip a
#: schedule in a loop / quietly sabotage oversight cadence one step at a time).
_MAX_UPDATES_PER_DAY = 5


def make_schedule_update_handler(profile_id: str) -> Handler:
    """Build the gateway handler bound to ONE agent's own profile.

    `profile_id` comes from the call site's `loaded` profile — never from the action.
    """

    def _handler(action: dict[str, Any]) -> str:
        schedule = action.get("schedule")
        # Re-enforce structure + floor before any side effect (never trust classify ran:
        # approve-reentry and direct execute() reach here without the chat door).
        if not isinstance(schedule, dict) or not schedule:
            raise PermissionError("schedule_update refused: payload must be {kind: cron}")
        for kind, cron in schedule.items():
            if not isinstance(kind, str) or not kind.strip():
                raise PermissionError("schedule_update refused: empty schedule kind")
            err = cron_floor_error(cron)
            if err:
                raise PermissionError(f"schedule_update refused: {err}")

        from src.packs.registry import PackRegistry
        from src.profile.loader import load_profile
        from src.runtime.agent_paths import agent_data_dir

        loaded = load_profile(profile_id, data_dir=agent_data_dir(profile_id))
        pack = PackRegistry().load(loaded.domain)
        valid_kinds = set(pack.report_kinds)
        for kind in schedule:
            if kind not in valid_kinds:
                raise PermissionError(
                    f"schedule_update refused: kind {kind!r} is not a report of domain "
                    f"{loaded.domain!r} (có: {', '.join(sorted(valid_kinds)) or '—'})"
                )

        _claim_daily_update_slot(profile_id)

        from src.server.profile_editor import read_profile_files, save_profile_yaml

        text = read_profile_files(profile_id)["profile"]
        doc = yaml.safe_load(text) if text.strip() else {}
        if not isinstance(doc, dict):
            raise PermissionError("schedule_update refused: profile.yaml is not a mapping")
        merged = {**(doc.get("schedule") or {}), **{k: str(v) for k, v in schedule.items()}}
        if len(merged) > _SCHEDULE_MAX_ENTRIES:
            raise PermissionError(
                f"schedule_update refused: merged schedule exceeds "
                f"{_SCHEDULE_MAX_ENTRIES} entries"
            )
        doc["schedule"] = merged
        # safe_dump loses comments/formatting — accepted (validate-then-atomic still
        # guarantees a loadable profile or no write at all).
        save_profile_yaml(profile_id, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))

        changes = ", ".join(f"{k}→{v}" for k, v in schedule.items())
        _notify_ceo_best_effort(profile_id, changes)
        return (
            f"schedule updated ({profile_id}): {changes} — "
            "hiệu lực từ lần reload service kế tiếp"
        )

    return _handler


def _claim_daily_update_slot(profile_id: str) -> None:
    """Reserve one of today's update slots in the agent's own dedup store, or refuse.

    Same date-key reservation shape as `auto_approve_policy.claim_daily_slot`: local
    date (matches the operator's clock), slots claimed atomically, a consumed slot is
    not released on later failure — the safe direction.
    """
    from src.actions.dedup_store import DedupStore
    from src.runtime.agent_paths import agent_data_dir

    local_date = datetime.now().astimezone().date().isoformat()
    dedup = DedupStore(agent_data_dir(profile_id) / "dedup.db")
    try:
        for seq in range(1, _MAX_UPDATES_PER_DAY + 1):
            if dedup.claim(f"schedule-update-slot:{local_date}:{seq}"):
                return
    finally:
        dedup.close()
    raise PermissionError(
        f"schedule_update refused: đã hết {_MAX_UPDATES_PER_DAY} lượt đổi lịch hôm nay"
    )


def _notify_ceo_best_effort(profile_id: str, changes: str) -> None:
    """DM the CEO that a schedule changed (red-team F2: rescheduling can move oversight
    cadence — the operator must SEE it happen, not discover it in the audit log later).

    Routed through the shared admin-ops DM helper (v21 ops path, audited under the
    admin agent). Best-effort by that helper's contract — never fails the update.
    """
    from src.runtime.operator_notify import notify_operator_best_effort

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    notify_operator_best_effort(
        f"🗓 Agent '{profile_id}' vừa tự đổi lịch chạy: {changes} "
        "(hiệu lực lần reload kế tiếp).",
        dedup_hint=f"schedule-update-notice:{profile_id}:{changes}:{stamp}",
        rationale="schedule_update notice to CEO",
    )
