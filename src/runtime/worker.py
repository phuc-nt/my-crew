"""Per-agent worker entrypoint (v2 M1-P3).

    python -m src.runtime.worker --agent-id <id> --report <daily|weekly|okr|resource>
                                 [--audience internal|external] [--dry-run]
    python -m src.runtime.worker --agent-id <id> --resume
                                 --thread <thread_id> --decision approve|reject

One worker = one OS process running ONE report for ONE agent, fully isolated: it loads
`profiles/<id>/` at the per-agent data dir `.data/agents/<id>/`, so its gateway/audit/
budget/dedup/approvals/checkpoint all live under that dir (Slice 1). It mirrors the
cron report path but per-agent (data dir + agent-prefixed thread_id), appends a B1
run-event to `runs.jsonl`, and exits 0 (delivered) / 1 (ran, not delivered / error) /
2 (bad invocation or profile load failure) / 3 (PAUSED at a Lớp B interrupt, awaiting
approval — M2-P5). `--resume` re-attaches to a paused thread and applies the decision.
The coordinating service spawns this and collects the exit code + the last run-event.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from src.memory.provider import resolve_memory_text
from src.profile.context import ProfileContext
from src.profile.loader import LoadedProfile, load_profile
from src.runtime.agent_paths import agent_data_dir, agent_thread_id
from src.runtime.legacy_migration import migrate_legacy_data_dir
from src.runtime.run_config import invoke_config
from src.runtime.run_event import append_run_event

logger = logging.getLogger(__name__)

# A run_report runs the real graph; injectable so tests stay fully offline (no MCP).
RunReport = Callable[[LoadedProfile, Any, str, str, str], dict]


def _flag_value(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _report_kind(args: list[str]) -> str:
    return _flag_value(args, "--report") or "daily"


def _audience(args: list[str]) -> str:
    return "external" if _flag_value(args, "--audience") == "external" else "internal"


def build_graph_for(loaded: LoadedProfile, settings: Any, kind: str, audience: str):
    """Build the per-agent compiled graph for one (kind, audience).

    Shared by the fresh-run path and the `--resume` path so both rebuild the
    IDENTICAL graph structure — a resume must reconstruct the same node/edge shape
    the interrupted checkpoint was created with.
    """
    from src.agent.checkpoint import get_checkpointer
    from src.agent.memory_node import build_remember_node
    from src.agent.sibling_memory import build_sibling_context
    from src.agent.store import get_store
    from src.company_docs.pool import load_company_docs
    from src.packs.registry import PackRegistry
    from src.runtime.registry import load_registry
    from src.skills.skill_pool import build_skill_context

    cp = get_checkpointer(settings)
    st = get_store(settings)  # cross-thread memory Store (InMemoryStore default)
    # Same store instance serves the sibling READ here and the remember WRITE in the graph.
    skills, selector = build_skill_context(loaded, settings)
    sib_facts, sib_sel = build_sibling_context(loaded, settings, st, load_registry())
    context = ProfileContext(
        persona=loaded.soul, project=loaded.project, memory=resolve_memory_text(loaded),
        skills=skills, skill_selector=selector,
        sibling_facts=sib_facts, sibling_selector=sib_sel,
        sibling_project=loaded.project_group,
        company_docs=load_company_docs(getattr(loaded, "company_docs", ())),
        auto_approve=getattr(loaded, "auto_approve", None),
    )
    remember = build_remember_node(loaded.profile_id, settings, audience)

    # v3 M5 S2: dispatch the report kind through the agent's domain pack instead of an
    # if/elif ladder. The pm-pack registers daily/weekly/okr/resource builders that call
    # the same build_*_graph as before, so output stays byte-identical.
    pack = PackRegistry().load(loaded.domain)
    builder = pack.report_kinds.get(kind)
    if builder is None:
        raise ValueError(
            f"Report kind {kind!r} is not served by the {pack.domain!r} pack. "
            f"Available: {', '.join(sorted(pack.report_kinds)) or '(none)'}."
        )
    return builder(
        cp, config=loaded.config, settings=settings, context=context,
        audience=audience, store=st, remember=remember, tools=pack.tools,
    )


def _run_with_mcp_pool(fn: Callable[[], dict]) -> dict:
    """Run `fn` (a self-contained run: graph invoke or a poll/tick) under a fresh
    per-run MCP session pool (v11 P3), so every `call_tool` made while `fn` runs
    reuses one subprocess per server instead of spawning fresh per call.

    The pool is created and torn down around this single call — the contextvar is
    set on THIS thread, the same thread `fn` runs on, which the pool's owner-task/
    anyio design requires. `fn` runs on the worker's sync main thread, so this is a
    direct call (no `asyncio.to_thread` needed here, unlike run_manager).
    """
    from src.adapters.mcp_session_pool import McpSessionPool, _current_pool

    with McpSessionPool() as pool:
        token = _current_pool.set(pool)
        try:
            return fn()
        finally:
            _current_pool.reset(token)


def _default_run_report(
    loaded: LoadedProfile, settings: Any, kind: str, audience: str, thread_id: str
) -> dict:
    """Real dispatch: build the per-agent graph and run one report (mirrors cron)."""
    graph = build_graph_for(loaded, settings, kind, audience)
    return _run_with_mcp_pool(
        lambda: graph.invoke({}, config=invoke_config(thread_id, settings))
    )


def main(argv: list[str] | None = None, *, run_report: RunReport = _default_run_report) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]

    agent_id = _flag_value(args, "--agent-id")
    if not agent_id:
        print(
            "usage: python -m src.runtime.worker --agent-id <id> --report <kind>",
            file=sys.stderr,
        )
        return 2
    kind = _report_kind(args)
    audience = _audience(args)
    dry_run = "--dry-run" in args

    # A malformed agent id (path-escape, bad chars) is rejected before any data dir is
    # built — clean exit, no run-event (the data dir is unknown / unsafe).
    try:
        data_dir = agent_data_dir(agent_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Migrate the v1 .data/ into .data/agents/default/ once, on the first multi-agent run.
    migrate_legacy_data_dir()

    try:
        loaded = load_profile(agent_id, data_dir=data_dir)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        append_run_event(data_dir, _event(agent_id, kind, audience, "load_error", None, False))
        return 2

    settings = loaded.settings
    if dry_run:
        settings = replace(settings, dry_run=True)

    # Preflight the key (mirrors cron) so a misconfigured agent is a clean exit-2
    # `load_error`, not a noisy `status=error` the service would read as a crash.
    if not settings.openrouter_api_key:
        print(f"error: OPENROUTER_API_KEY not set for agent {agent_id!r}.", file=sys.stderr)
        append_run_event(data_dir, _event(agent_id, kind, audience, "load_error", None, False))
        return 2

    # M2-P5 resume: re-attach to a thread paused at the Lớp B interrupt and apply the
    # human decision. The thread_id (not --report/--audience) drives which graph to
    # rebuild, so this branches before the normal fresh-run dispatch.
    if "--resume" in args:
        from src.runtime.worker_resume import run_resume

        return run_resume(
            args, agent_id=agent_id, loaded=loaded, settings=settings, data_dir=data_dir,
            build_graph=build_graph_for, flag_value=_flag_value,
            append_event=append_run_event, make_event=_event,
        )

    # v3 M11: the ask-agent inbox poll is a generic run kind, not a pack report kind —
    # it never builds a report graph, so it branches before the graph dispatch.
    if kind == "inbox":
        # v6 M13: one tick fans out to every configured transport (Slack and/or Telegram).
        from src.runtime.inbox_dispatch import run_all_inboxes

        try:
            # v11 P3: a poll makes several Slack MCP calls (list_workspace_channels,
            # search_messages, maybe post_message per reply) — pool them into one spawn.
            result = _run_with_mcp_pool(lambda: run_all_inboxes(loaded, settings))
        except Exception as exc:  # noqa: BLE001 — record the failure, never crash
            logger.exception("worker %s/inbox failed", agent_id)
            append_run_event(data_dir, _event(agent_id, kind, "internal", "error", None, False))
            print(f"error: {exc}", file=sys.stderr)
            return 1
        append_run_event(
            data_dir,
            _event(agent_id, kind, "internal", result["status"], result.get("cost_usd"),
                   bool(result.get("delivered"))),
        )
        logger.info("worker %s inbox: %s (replied=%s)", agent_id, result["status"],
                    result.get("replied"))
        return 0  # a poll with zero mentions is a SUCCESS, unlike an undelivered report

    # v6 M15: the assigned-task runner is a generic run kind (not a pack report) — it
    # checks open tasks and posts reminders/done notices, branching before graph dispatch.
    if kind == "tasks":
        from src.runtime.task_runner import run_tasks

        try:
            # v11 P3: each open task's check + reminder can call MCP reads (Jira/GitHub/
            # Slack) — pool them per tick instead of spawning per call.
            result = _run_with_mcp_pool(lambda: run_tasks(loaded, settings))
        except Exception as exc:  # noqa: BLE001 — record the failure, never crash
            logger.exception("worker %s/tasks failed", agent_id)
            append_run_event(data_dir, _event(agent_id, kind, "internal", "error", None, False))
            print(f"error: {exc}", file=sys.stderr)
            return 1
        append_run_event(
            data_dir,
            _event(agent_id, kind, "internal", result["status"], result.get("cost_usd"),
                   bool(result.get("delivered"))),
        )
        logger.info("worker %s tasks: %s (checked=%s)", agent_id, result["status"],
                    result.get("checked"))
        return 0  # a tick with zero due tasks is a SUCCESS

    # v8 M21: the CEO-observability alert push is a generic run kind (fleet health tick on
    # the admin agent) — computes team_alerts and DMs the CEO, branching before graph dispatch.
    if kind == "ops-alerts":
        from src.runtime.ops_alert_runner import run_ops_alerts

        try:
            result = run_ops_alerts(loaded, settings)
        except Exception as exc:  # noqa: BLE001 — record the failure, never crash
            logger.exception("worker %s/ops-alerts failed", agent_id)
            append_run_event(data_dir, _event(agent_id, kind, "internal", "error", None, False))
            print(f"error: {exc}", file=sys.stderr)
            return 1
        append_run_event(
            data_dir,
            _event(agent_id, kind, "internal", result["status"], result.get("cost_usd"),
                   bool(result.get("delivered"))),
        )
        logger.info("worker %s ops-alerts: %s (checked=%s)", agent_id, result["status"],
                    result.get("checked"))
        return 0  # a tick with zero new alerts is a SUCCESS

    # v12 M29: the office-room milestone mirror is a generic run kind (fleet-wide tick
    # on the admin agent) — DMs the CEO ONLY milestone-kind office events, branching
    # before graph dispatch like ops-alerts above.
    if kind == "milestone-mirror":
        from src.runtime.milestone_mirror_runner import run_milestone_mirror

        try:
            result = run_milestone_mirror(loaded, settings)
        except Exception as exc:  # noqa: BLE001 — record the failure, never crash
            logger.exception("worker %s/milestone-mirror failed", agent_id)
            append_run_event(data_dir, _event(agent_id, kind, "internal", "error", None, False))
            print(f"error: {exc}", file=sys.stderr)
            return 1
        append_run_event(
            data_dir,
            _event(agent_id, kind, "internal", result["status"], result.get("cost_usd"),
                   bool(result.get("delivered"))),
        )
        logger.info("worker %s milestone-mirror: %s (checked=%s)", agent_id, result["status"],
                    result.get("checked"))
        return 0  # a tick with zero new milestones is a SUCCESS

    # v12 M28a: one team-task STEP is a generic run kind (not a pack report) — the
    # coordinator (P3) reserves a step (issuing a lease `attempt_id`) then spawns this
    # exact invocation. Branches before graph dispatch like inbox/tasks/ops-alerts above.
    if kind == "team-step":
        return _run_team_step_kind(args, agent_id=agent_id, loaded=loaded, settings=settings,
                                    data_dir=data_dir)

    # v12 M28b: the coordinator ticker is a generic run kind — one SHORT tick (read
    # store, take ONE action, exit) on the coordinator agent only. Branches before
    # graph dispatch like every other pseudo-kind above.
    if kind == "team-tick":
        from src.runtime.team_tick_runner import run_team_tick

        try:
            result = run_team_tick(loaded, settings)
        except Exception as exc:  # noqa: BLE001 — record the failure, never crash
            logger.exception("worker %s/team-tick failed", agent_id)
            append_run_event(data_dir, _event(agent_id, kind, "internal", "error", None, False))
            print(f"error: {exc}", file=sys.stderr)
            return 1
        append_run_event(
            data_dir,
            _event(agent_id, kind, "internal", result["status"], result.get("cost_usd"),
                   bool(result.get("delivered"))),
        )
        logger.info("worker %s team-tick: %s (checked=%s)", agent_id, result["status"],
                    result.get("checked"))
        return 0  # a tick with nothing actionable is a SUCCESS (mirrors tasks/ops-alerts)

    thread_id = agent_thread_id(agent_id, kind, audience)
    try:
        result = run_report(loaded, settings, kind, audience, thread_id)
    except Exception as exc:  # noqa: BLE001 — record the failure, never crash the worker
        logger.exception("worker %s/%s failed", agent_id, kind)
        append_run_event(data_dir, _event(agent_id, kind, audience, "error", None, False))
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # A graph-native Lớp B interrupt (M2-P5): the external report PAUSED before
    # delivery, state is checkpointed at `thread_id`. The worker exits 3 ("paused,
    # awaiting approval") and records an `interrupted` run-event — resume later with
    # `--resume --thread <thread_id> --decision approve|reject`.
    if "__interrupt__" in result:
        append_run_event(
            data_dir, _event(agent_id, kind, audience, "interrupted", None, False)
        )
        logger.info("worker %s %s/%s: PAUSED at approval gate (thread %s)",
                    agent_id, kind, audience, thread_id)
        print(f"paused for approval — resume with: --resume --thread {thread_id} "
              "--decision approve|reject")
        return 3

    delivered = bool(result.get("delivered", False))
    cost = result.get("cost_usd")
    status = "delivered" if delivered else "not_delivered"
    # v8 M22: store a short summary of the report so the portfolio roll-up can show each
    # agent's latest content. INTERNAL only — an external report's content must not be
    # persisted where the fleet accessor could read it into a roll-up.
    summary = ""
    if audience == "internal" and result.get("report_text"):
        from src.runtime.report_summary import summarize_report

        summary = summarize_report(str(result["report_text"]))
    append_run_event(
        data_dir, _event(agent_id, kind, audience, status, cost, delivered,
                         report_summary=summary,
                         # v8 M23: the approval gate set this when it auto-delivered a trusted
                         # scheduled external report — surfaces in the CEO's "đã tự duyệt" view.
                         auto_approved=bool(result.get("auto_approved"))),
    )
    logger.info(
        "worker %s %s/%s: delivered=%s %s",
        agent_id, kind, audience, delivered, result.get("delivery_summary", ""),
    )
    return 0 if delivered else 1


def _run_team_step_kind(args: list[str], *, agent_id: str, loaded: LoadedProfile, settings: Any,
                         data_dir) -> int:
    """The `team-step` branch body (v12 M28a): verify the lease, run one step of the
    team-task graph, write the outcome artifact on EVERY exit path, append a run-event
    on every exit, and return the worker's exit code (0 done / 1 error-or-rejected /
    3 paused-at-Lớp-B). Exit 3 fires whenever the step's `deliver` node gated an
    external write behind `ApprovalStore` (`TeamTaskDeps.external_write` returning
    "not yet"); the coordinator ticker POLLS that approval every tick and re-reserves
    the step once it resolves (`coordinator_nodes.tick_actions
    .poll_awaiting_approval_step`) — this exit code is reachable in production, not a
    placeholder for a future step kind.

    A malformed invocation (missing --task-id/--step-id/--attempt-id) is a clean no-op
    error — NOT an outcome-artifact write, since there is no valid task/step to write
    one for (mirrors the worker's own --agent-id-missing early exit).
    """
    from src.agent.team_task_artifact import write_step_artifact
    from src.runtime.team_step_runner import STATUS_DONE, STATUS_PAUSED, run_team_step
    from src.runtime.team_task_paths import team_tasks_root
    from src.runtime.team_task_store import TeamTaskStore, team_tasks_db_path

    task_id = _flag_value(args, "--task-id")
    step_id = _flag_value(args, "--step-id")
    attempt_id = _flag_value(args, "--attempt-id")
    if not task_id or not step_id or not attempt_id:
        print(
            "error: --report team-step requires --task-id --step-id --attempt-id",
            file=sys.stderr,
        )
        append_run_event(data_dir, _event(agent_id, "team-step", "internal", "error", None, False))
        return 1

    def _write_outcome(status: str, *, error: str = "") -> None:
        """Fallback outcome artifact for the paths where the GRAPH never reached its
        own `deliver` node (failed / paused) — the next step's `perceive` still needs
        SOMETHING to read there instead of a missing file. On the "done" path the
        graph's `deliver` already wrote the real artifact (with `result_text`); this
        must NOT be called there, or it would clobber that artifact with a smaller
        status-only payload.

        A write failure here must not mask the real result (logged, not raised): the
        step's store row is the source of truth, the artifact is the cross-agent
        handoff convenience."""
        store = TeamTaskStore(team_tasks_db_path())
        try:
            step = store.get_step(task_id, step_id)
        finally:
            store.close()
        if step is None:
            return  # no valid step row — nothing to attach the artifact to
        payload: dict[str, Any] = {"status": status, "step_title": step.title}
        if error:
            payload["error"] = error
        try:
            write_step_artifact(team_tasks_root(), task_id, step.seq, payload)
        except (OSError, ValueError) as exc:  # noqa: BLE001 — never let this crash the worker
            logger.warning("team-step %s/%s: outcome artifact write failed: %s",
                            task_id, step_id, exc)

    try:
        result = run_team_step(
            loaded, settings, task_id=task_id, step_id=step_id, attempt_id=attempt_id,
        )
    except Exception as exc:  # noqa: BLE001 — record the failure, never crash
        logger.exception("worker %s/team-step %s/%s failed", agent_id, task_id, step_id)
        _write_outcome("failed", error=str(exc))
        append_run_event(data_dir, _event(agent_id, "team-step", "internal", "error", None, False))
        print(f"error: {exc}", file=sys.stderr)
        return 1

    status = result["status"]
    if status == STATUS_PAUSED:
        _write_outcome("awaiting_approval")
        append_run_event(
            data_dir, _event(agent_id, "team-step", "internal", "interrupted", None, False)
        )
        logger.info(
            "worker %s team-step %s/%s: PAUSED at approval gate", agent_id, task_id, step_id
        )
        return 3

    if status != STATUS_DONE:
        # STATUS_REJECTED (bad/stale attempt_id lease) — a clean no-op, no artifact
        # written (the step never ran), but still an audited run-event.
        append_run_event(
            data_dir, _event(agent_id, "team-step", "internal", status, None, False)
        )
        logger.warning(
            "worker %s team-step %s/%s: rejected (%s)", agent_id, task_id, step_id, status
        )
        return 1

    # No `_write_outcome("done")` here — the graph's `deliver` node already wrote the
    # real artifact (result_text + step_title) when `run_team_step` returned STATUS_DONE;
    # overwriting it here would clobber the content the NEXT step's `perceive` reads.
    append_run_event(
        data_dir,
        _event(agent_id, "team-step", "internal", "done", result.get("cost_usd"),
               bool(result.get("delivered"))),
    )
    logger.info("worker %s team-step %s/%s: done", agent_id, task_id, step_id)
    return 0


def _event(agent_id, kind, audience, status, cost, delivered, *, report_summary="",
           auto_approved=False) -> dict:
    ev = {
        "agent_id": agent_id, "kind": kind, "audience": audience,
        "status": status, "cost_usd": cost, "delivered": delivered,
    }
    # Only carry the optional fields when set — event stays byte-identical for the
    # inbox/tasks/ops-alerts pseudo-kinds and for external runs (backward-compat).
    if report_summary:
        ev["report_summary"] = report_summary
    if auto_approved:
        ev["auto_approved"] = True
    return ev


if __name__ == "__main__":
    raise SystemExit(main())
