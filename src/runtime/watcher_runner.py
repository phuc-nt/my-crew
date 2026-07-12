"""Wake-gate watcher tick — the `watch` generic run kind's body (v31 P5).

NO-LLM by construction: for each declared watcher, poll the source through an
EXISTING read tool (bounded timeout), normalize → hash (`watcher_normalize`), compare
against the committed hash (`WatcherStore`) and ONLY on a real diff wake the agent —
exactly once. An unchanged source costs zero LLM calls; that absence is measurable in
the capture store (the core ROI metric).

THE INVARIANT: the watcher is read-only "perceive". It never mutates a source, never
emits a gateway action — `src/actions/*` is untouched. The wake itself enqueues one
pre-planned single-step team task (below); every action the WOKEN agent then takes
flows through the Action Gateway as always.

Wake vehicle (the v29a unresolved #1, settled here): enqueue ONE team task whose plan
is already set — a single step assigned to the watching agent itself, its title being
the watcher's own static `prompt`. `create_task` + `set_plan` needs NO decompose LLM;
the coordinator's team-tick dispatches the step through the standard lease/step/
capture machinery within a minute, so "the agent woke up and worked" is the normal
work path, fully telemetered. The v29a objection to a team-task vehicle was the
decompose-LLM cost — a pre-set plan has none. Requires a coordinator to be configured
(the demo company has one); the step assignee must be roster-assignable, checked
BEFORE enqueue so a misconfigured watcher alerts instead of minting undispatchable
tasks forever.

Lost-wake safety: the new hash is committed ONLY after the wake enqueue succeeded —
a failed wake leaves the old hash, so the same diff re-fires next tick.

UNTRUSTED-CONTENT rule (hard): nothing read from the source enters the wake. The
task title/instruction is `watcher.prompt` (agent-owned, static, from profile.yaml)
plus the watcher id — the woken agent re-reads the source through its own gated read
path. Watched text (issue titles, PR bodies) never rides the wake.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from src.runtime.watcher_normalize import normalize_and_hash
from src.runtime.watcher_store import WatcherStore

logger = logging.getLogger(__name__)

#: Per-poll bound so a hung MCP/CLI read cannot hold the worker toward the service's
#: 600s kill. The underlying tools carry their own timeouts (MCP client / gh / gws
#: subprocess); this is the defensive outer bound.
_POLL_TIMEOUT_S = 20
#: Consecutive failures before the operator is alerted (per watcher, once per day).
_FAIL_ALERT_THRESHOLD = 3
_STALE_HOURS = 24.0


def run_watchers(
    loaded: Any, settings: Any, *,
    poll_fn: Callable[[dict, Any, Any], Any] | None = None,
    wake_fn: Callable[[Any, dict], bool] | None = None,
) -> dict:
    """One watch tick over `loaded.watchers`. Returns a run-event dict for the worker.

    `poll_fn`/`wake_fn` are injectable at the boundary for tests; production uses the
    real reads + the team-task wake. Always `cost_usd=None` — this path has no LLM.
    """
    watchers = list(getattr(loaded, "watchers", ()) or ())
    if not watchers:
        return {"status": "no_watchers", "checked": 0, "diffs": 0, "cost_usd": None,
                "delivered": False}
    poll = poll_fn or _poll_source
    wake = wake_fn or _wake_via_team_task

    store = WatcherStore(Path(settings.data_dir) / "watcher.db")
    checked, diffs, woke = 0, 0, 0
    try:
        for watcher in watchers:
            wid = f"{loaded.profile_id}:{watcher['id']}"
            source = str(watcher["source"])
            try:
                payload = _bounded(lambda w=watcher: poll(w, loaded, settings))
                current = normalize_and_hash(source, payload)
            except Exception as exc:  # noqa: BLE001 — a failing source must not stop siblings
                store.record_check(wid, source, None, error=str(exc)[:300])
                state = store.get_state(wid) or {}
                fails = int(state.get("fail_count") or 0)
                logger.warning("watcher %s poll failed (%d consecutive): %s",
                               wid, fails, exc)
                if fails == _FAIL_ALERT_THRESHOLD:
                    _alert(f"⚠️ Watcher '{wid}' lỗi {fails} lần liên tiếp: "
                           f"{str(exc)[:150]}", wid, "fail")
                continue
            checked += 1
            is_new, _old = store.record_check(wid, source, current)
            if is_new:
                diffs += 1
                if wake(loaded, watcher):
                    store.advance_hash(wid, current)
                    woke += 1
                else:
                    # Hash NOT advanced: the diff re-fires next tick (lost-wake safety).
                    logger.warning("watcher %s: wake failed — diff will re-fire", wid)
            elif store.is_stale(wid, max_age_hours=_STALE_HOURS):
                # A stale-quiet source is an operator's problem, not a reason to burn
                # an LLM run: alert, never wake.
                _alert(f"⚠️ Watcher '{wid}' không có thay đổi nào >24h — kiểm tra "
                       "nguồn/cấu hình.", wid, "stale")
    finally:
        store.close()
    status = "woke" if woke else ("diff_wake_failed" if diffs else "no_change")
    return {"status": status, "checked": checked, "diffs": diffs, "woke": woke,
            "cost_usd": None, "delivered": False}


def _bounded(fn: Callable[[], Any]) -> Any:
    """Run one poll under the outer timeout (a hung read must not eat the tick).

    NOT a `with` block: the executor's __exit__ JOINS worker threads, so a hung poll
    would block right there and defeat the timeout. `shutdown(wait=False)` lets the
    tick move on; the abandoned thread is bounded by the underlying tool's own
    timeout, and the service's worker kill (`_supervise`) is the final backstop.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=_POLL_TIMEOUT_S)
    except FutureTimeout:
        raise TimeoutError(f"poll quá {_POLL_TIMEOUT_S}s") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _poll_source(watcher: dict, loaded: Any, settings: Any) -> Any:
    """Read one source via the EXISTING read tools (no new read paths)."""
    source, target = str(watcher["source"]), str(watcher["target"])
    if source == "jira":
        from src.tools.jira_read import get_open_issues

        return get_open_issues(target, config=loaded.config)
    if source == "github":
        from src.tools.github_read import get_open_prs

        return get_open_prs(target, config=loaded.config)
    if source == "sheets":
        # The hr-pack's gws read pair is the one existing Sheets read; the pack module
        # loader is how every pack consumer reaches pack code.
        from src.packs.registry import _load_pack_module

        tools = _load_pack_module("hr", "tools")
        rows = tools._gws_sheet_rows(target, "A1:Z200")  # noqa: SLF001 — spec'd reuse
        return tools._rows_to_tasks(rows, source="sheet")  # noqa: SLF001
    # confluence/linear reach normalize_and_hash's fail-closed raise via this same
    # error: declared-but-unsupported is a per-watcher failure, not a silent skip.
    raise RuntimeError(f"watcher source {source!r} chưa hỗ trợ poll")


def _wake_via_team_task(loaded: Any, watcher: dict) -> bool:
    """Enqueue the one-step wake task. True ⇒ the agent WILL be dispatched.

    Everything here is internal store state — no gateway action, no LLM. Returns
    False (→ hash not advanced, re-fire) on any failure, including a non-assignable
    agent (coordinator/admin/disabled must not accumulate undispatchable tasks).
    """
    prompt = str(watcher.get("prompt") or "").strip()
    wid = str(watcher["id"])
    try:
        from src.agent.team_task_roster import is_assignable

        if not is_assignable(loaded.profile_id):
            logger.warning(
                "watcher %s: agent %r is not roster-assignable (coordinator/admin/"
                "disabled) — wake impossible, check the watcher's host agent",
                wid, loaded.profile_id,
            )
            return False

        from src.runtime.team_task_paths import team_tasks_db_path
        from src.runtime.team_task_store import TeamTaskStore

        task_id = uuid.uuid4().hex[:12]
        store = TeamTaskStore(team_tasks_db_path())
        try:
            store.create_task(
                task_id=task_id,
                title=f"[watch:{wid}] {prompt[:120]}",
                original_request=prompt,
                assigned_by=f"watcher:{wid}",
                pic_id=loaded.profile_id,
            )
            store.set_plan(
                task_id,
                [{"step_id": "s1", "title": prompt, "assigned_to": loaded.profile_id,
                  "deps": [], "needs_review": False}],
                plan_hash=f"watch-{uuid.uuid4().hex[:8]}",
            )
        finally:
            store.close()

        from src.runtime.office_room_append import append_office_event

        append_office_event(
            task_id, author=loaded.profile_id, kind="assignment",
            body={"text": f"watcher '{wid}' phát hiện thay đổi — {loaded.profile_id} "
                          "nhận việc rà soát",
                  "task_title": f"[watch:{wid}] {prompt[:80]}",
                  "pic": loaded.profile_id, "task_id": task_id},
            also_office=True,
        )
        return True
    except Exception:  # noqa: BLE001 — a failed wake must return False, never raise
        logger.exception("watcher %s: wake enqueue failed", wid)
        return False


def _alert(text: str, wid: str, kind: str) -> None:
    """Operator DM, once per (watcher, kind, local-day) — dedup keyed in the hint."""
    from datetime import datetime

    from src.runtime.operator_notify import notify_operator_best_effort

    local_date = datetime.now().astimezone().date().isoformat()
    notify_operator_best_effort(
        text, dedup_hint=f"watcher-alert:{wid}:{kind}:{local_date}",
        rationale="watcher fail/stale alert",
    )
