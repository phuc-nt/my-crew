"""Escalation destination: mint a Manager-agent team task (v94 P3, decision D7).

The ladder in `team_tick_collaborators.make_escalate` has one destination today: the
human operator, over Telegram/SMTP/webhook (`operator_channels.send_via_channels`).
That destination is correct for every INTERNAL escalation source (stuck ruling,
give-up, review-cap exhausted) — a human always decides those, unchanged here.

This module adds a SECOND destination for a source the ladder does not have a caller
for yet (P5, digital-assistant): a customer request that exceeds the assistant's
authority. Instead of paging a human immediately, it mints a single-step team task —
same NO-DECOMPOSE-LLM vehicle `watcher_runner._wake_via_team_task` established — whose
PIC is the company's Manager agent. The owner is told only AFTER the Manager task
finishes or stalls (`escalation_manager_outcome_notify`, wired at delivery time by
`team_tick_collaborators`), matching the picture's "khách hàng → escalation task →
Manager" arrow.

Three brakes, per the phase spec's non-functional requirements:
  1. Manager must be roster-assignable (`team_task_roster.is_assignable`) — the fallback
     chain `manager_id → coordinator_id → "admin"` will resolve to the admin domain
     agent when no dedicated manager is configured, and `is_assignable` EXCLUDES the
     admin domain agent by design (it holds ops-chat privileges no team-task step
     should carry). A configured-but-undispatchable target is the SAME "misconfigured
     — alert instead of minting forever" case `watcher_runner` already established, so
     it degrades to `escalate_to_manager` returning False (caller falls back to human).
  2. A daily cap (`company.escalation_daily_cap`, default 20) — a JSON sidecar counter
     (same read-fresh/write-fresh/atomic-replace shape as `team_tick_runner
     ._json_retry_tracker`), keyed by local calendar day. Over cap, mint is refused.
  3. `origin=escalation` on the minted task's `route_json` (the existing per-task
     free-form column — see `TeamTaskStore.set_route`/`get_route`, no schema change
     needed) — the recursion guard. A caller must pass the ORIGINATING task's route
     when escalating from inside one (see `is_escalation_origin`); this module never
     inspects call stacks, it only refuses to be handed a route that already says so.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CAP_SIDECAR_NAME = "manager_escalation_daily_cap.json"


def resolve_manager_id(company: Any) -> str:
    """`manager_id` → `coordinator_id` → `"admin"`, per the phase spec's fallback chain.
    Always returns a non-empty string (the final fallback is the literal `"admin"`)."""
    manager_id = str(getattr(company, "manager_id", "") or "").strip()
    if manager_id:
        return manager_id
    coordinator_id = str(getattr(company, "coordinator_id", "") or "").strip()
    return coordinator_id or "admin"


def is_escalation_origin(route: dict | None) -> bool:
    """True iff a task's `route_json` already carries this module's recursion marker.
    Callers escalating FROM a task pass its route here — a task minted by
    `escalate_to_manager` must never be allowed to escalate to the manager again."""
    return bool(route) and route.get("origin") == "escalation"


def _cap_sidecar_path() -> Path:
    from my_crew.runtime.team_task_paths import team_tasks_root

    return team_tasks_root() / _CAP_SIDECAR_NAME


def _today_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _load_cap_counts(path: Path) -> dict[str, int]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_cap_counts(path: Path, data: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _under_daily_cap(daily_cap: int, *, sidecar_path: Path | None = None) -> bool:
    """True and increments the counter iff today's mint count is still under
    `daily_cap`. The check-and-increment happens together so two escalations racing
    within one tick cannot both slip past a cap of 1 (best-effort — this sidecar has no
    cross-process lock beyond the atomic replace, which is the same guarantee
    `team_tick_runner._json_retry_tracker` accepts for its own counter)."""
    path = sidecar_path if sidecar_path is not None else _cap_sidecar_path()
    data = _load_cap_counts(path)
    key = _today_key()
    count = int(data.get(key, 0))
    if count >= daily_cap:
        return False
    data[key] = count + 1
    _save_cap_counts(path, data)
    return True


def _wake_plan_hash(steps: list[dict[str, Any]]) -> str:
    """Same recompute-matching hash `watcher_runner._wake_plan_hash` uses — the ticker's
    `_verify_plan_hash` recomputes over the real `TeamStep` rows, so a pre-set plan must
    hash exactly the way that recompute will, or the task stalls on tick one."""
    from types import SimpleNamespace

    from my_crew.agent.task_decomposition import decomposition_content_hash

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())),
                        needs_shell=bool(s.get("needs_shell", False)),
                        external_write=bool(s.get("external_write", False)),
                        needs_web=bool(s.get("needs_web", False)))
        for s in steps
    ]))


def escalate_to_manager(
    *,
    source: str,
    summary: str,
    context_ref: str = "",
    origin_route: dict | None = None,
    company: Any = None,
    sidecar_path: Path | None = None,
) -> str | None:
    """Mint a single-step team task for the company's Manager agent. Returns the new
    task id on success, or None on any degrade path (caller falls back to notifying
    the human operator directly — this function never raises).

    `source`: free-text tag identifying the escalation's origin (e.g.
    "customer_assistant") — stored in `route_json.source` and in the task's
    `assigned_by` for audit.
    `summary`: the escalation body (already-safe, code-composed text — see the
    UNTRUSTED-CONTENT note below).
    `context_ref`: opaque reference (customer/session id, original task id, ...) the
    Manager can use to pull full context through ITS OWN gated read path.
    `origin_route`: the CALLING task's `route_json` (or None for a fresh escalation
    with no originating task) — passed through `is_escalation_origin` to refuse minting
    a second hop when the escalation itself came from a Manager task.

    UNTRUSTED-CONTENT rule (same invariant `watcher_runner` documents for its wake):
    `summary` becomes the minted task's title/instruction, which the Manager agent will
    read directly. Callers MUST NOT hand this function raw external content (a
    customer's message text, an LLM's free-form output) — compose `summary` from
    code-owned templates plus safe identifiers only, exactly as the coordinator's
    escalation messages already do.
    """
    if is_escalation_origin(origin_route):
        logger.info("manager escalation from source=%s refused: origin task is itself "
                    "an escalation (recursion guard)", source)
        return None

    from my_crew.runtime.company import DEFAULT_ESCALATION_DAILY_CAP

    if company is None:
        from my_crew.runtime.company import load_company

        company = load_company()

    manager_id = resolve_manager_id(company)
    try:
        from my_crew.agent.team_task_roster import is_assignable

        if not is_assignable(manager_id):
            logger.warning(
                "manager escalation from source=%s: resolved manager %r is not "
                "roster-assignable (coordinator/admin/disabled) — configure "
                "company.yaml::manager_id to a real staff agent; falling back to "
                "human notify", source, manager_id,
            )
            return None
    except Exception:  # noqa: BLE001 — an unreadable roster must degrade, not raise
        logger.exception("manager escalation: roster check failed for %r", manager_id)
        return None

    # `escalation_daily_cap` semantics (company.yaml, `load_company` rejects negatives
    # back to the default): 0 means REFUSE EVERY mint today — the intuitive reading an
    # operator reaches for when facing an escalation storm ("set it to 0 to stop
    # this"). There is no "unlimited" value on this field; a fleet that truly wants no
    # cap simply omits `escalation_daily_cap` (defaults to `DEFAULT_ESCALATION_DAILY_CAP`)
    # or sets a very large number — `> 0` never bypasses the check.
    raw_cap = getattr(company, "escalation_daily_cap", None)
    daily_cap = int(raw_cap) if raw_cap is not None else DEFAULT_ESCALATION_DAILY_CAP
    if not _under_daily_cap(max(daily_cap, 0), sidecar_path=sidecar_path):
        logger.warning(
            "manager escalation from source=%s: daily cap (%d) reached — falling "
            "back to human notify", source, daily_cap,
        )
        return None

    task_id = uuid.uuid4().hex[:12]
    title = f"[escalation:{source}] {summary[:120]}"
    steps = [{"step_id": "s1", "title": summary, "assigned_to": manager_id,
              "deps": [], "needs_review": False}]
    try:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        try:
            store.create_task(
                task_id=task_id, title=title, original_request=summary,
                assigned_by=f"escalation:{source}", pic_id=manager_id,
            )
            store.set_plan(task_id, steps, plan_hash=_wake_plan_hash(steps))
            store.set_route(task_id, {
                "origin": "escalation", "source": source, "context_ref": context_ref,
            })
        finally:
            store.close()
    except Exception:  # noqa: BLE001 — a failed mint must degrade, never raise
        logger.exception("manager escalation from source=%s: mint failed", source)
        return None

    try:
        from my_crew.runtime.office_room_append import append_office_event

        append_office_event(
            task_id, author="escalation", kind="assignment",
            body={"text": f"Yêu cầu vượt thẩm quyền từ nguồn '{source}' — chuyển cho "
                          f"{manager_id} xử lý",
                  "task_title": title, "pic": manager_id, "task_id": task_id},
            also_office=True,
        )
    except Exception:  # noqa: BLE001 — room append is observability, never blocking
        logger.warning("manager escalation: office event append failed for %s", task_id,
                       exc_info=True)

    return task_id
