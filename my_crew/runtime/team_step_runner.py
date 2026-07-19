"""Team-task step runner — the `team-step` generic run kind's body.

Mirrors `task_runner.py`/`ops_alert_runner.py`: worker.py's `team-step` branch calls
straight into `run_team_step`, which does everything for ONE step:

  1. verify the presented `attempt_id` is the CURRENT lease on this step (reject as a
     clean no-op otherwise — see module docstring on `team_task_store.verify_attempt`);
  2. run the `team_task_graph` (perceive reads the prior step's handoff artifact, work
     calls the LLM, deliver writes THIS step's handoff artifact);
  3. record the outcome in the store (`mark_done`/`mark_failed`/`mark_awaiting_approval`)
     and return a dict the worker turns into a run-event + exit code.

The worker branch (not this module) owns writing the run-event and the fallback outcome
artifact on an exception this function itself doesn't catch — this function raises on
setup failures (bad task/step) so the caller's `except Exception` still produces a
'failed' outcome artifact + a non-zero exit, matching the "write outcome on EVERY exit
path" requirement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Result "status" values `run_team_step` returns — the worker maps these to an exit code.
STATUS_DONE = "done"
STATUS_REJECTED = "rejected"  # bad/absent/mismatched attempt_id — clean no-op
STATUS_PAUSED = "paused"  # a Lớp B interrupt inside the step's graph (exit 3)


def run_team_step(
    loaded: Any, settings: Any, *, task_id: str, step_id: str, attempt_id: str,
) -> dict:
    """Run one team-task step. Returns `{status, cost_usd, delivered, room_message}`.

    `status`:
      - `"rejected"`: the attempt_id lease didn't match (no work done, no artifact
        written) — the worker treats this as a clean no-op error (exit 1).
      - `"done"`: the step ran to completion (delivered artifact written).
      - `"failed"`: the step's graph raised — the CALLER (worker) catches the
        exception this function re-raises and writes the failed outcome artifact.
      - `"paused"`: a Lớp B interrupt inside a step's graph (an external write went to
        `pending_approval`) — the worker maps this to exit 3 / `awaiting_approval`.

    Lease safety: every terminal store write in this function (`mark_done`/
    `mark_failed`) passes `attempt_id`, so if the ticker has since killed this worker
    for a lease timeout and re-reserved the step (new `attempt_id`), the write is a
    no-op against the new attempt's row instead of corrupting it or double-counting
    cost. `store.heartbeat(...)` is called at each graph node boundary (perceive/work/
    deliver, via `_run_graph`'s injected hook) so a step that is genuinely still
    working keeps refreshing its own lease and the ticker's unconditional
    kill-on-expiry never fires against live work.
    """
    import time
    from datetime import UTC, datetime

    from my_crew.runtime.step_telemetry import StepTelemetry
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    # One collector per attempt: whichever engine runs the step fills it with token counts +
    # cost provenance (side-channel, since run_work's tuple contract can't grow). Timing is
    # measured IN THIS worker process (monotonic) — never `spawned_at`, which the ticker sets
    # in a different process, so it is not this worker's wall clock.
    telemetry = StepTelemetry()
    started_at = datetime.now(UTC).isoformat()
    t0 = time.monotonic()
    engine = getattr(getattr(loaded, "agent_runtime", None), "kind", "native") or "native"

    store = TeamTaskStore(team_tasks_db_path())
    try:
        if not store.verify_attempt(task_id, step_id, attempt_id):
            logger.warning(
                "team-step %s/%s: attempt_id %r does not match the current lease — "
                "rejecting as a no-op", task_id, step_id, attempt_id,
            )
            return {"status": STATUS_REJECTED, "cost_usd": None, "delivered": False,
                     "room_message": ""}

        step = store.get_step(task_id, step_id)
        task = store.get(task_id)
        if step is None or task is None:
            logger.warning(
                "team-step %s/%s: task/step vanished after lease verify", task_id, step_id
            )
            return {"status": STATUS_REJECTED, "cost_usd": None, "delivered": False,
                     "room_message": ""}

        def _touch() -> None:
            try:
                store.heartbeat(task_id, step_id)
            except Exception:  # noqa: BLE001 — a heartbeat write must never fail the step
                logger.warning("team-step %s/%s: heartbeat write failed", task_id, step_id)

        if step.step_type == "review":
            result = _run_review(
                loaded, settings, task_id=task_id, step=step, store=store, telemetry=telemetry
            )
        else:
            result = _run_graph(
                loaded, settings, task_id=task_id, step=step, attempt_id=attempt_id,
                task_title=task.title, on_node=_touch, telemetry=telemetry,
            )
        if result.get("status") == "waiting_clarify":
            # v34 P2: the graph paused on a CEO question. Persist the correlation id;
            # the ticker polls the ClarifyStore and re-dispatches on answer/expiry —
            # the worker then RESUMES the saved thread (Command(resume=...)).
            store.mark_waiting_clarify(
                task_id, step_id, attempt_id=attempt_id,
                clarify_id=result.get("clarify_id"),
            )
            _record_capture(
                attempt_id=attempt_id, task_id=task_id, step=step, engine=engine,
                status="waiting_clarify", telemetry=telemetry,
                cost_usd=result.get("cost_usd"),
                started_at=started_at, t0=t0, error=None,
            )
            _append_step_event(
                task_id, author=step.assigned_to, task_title=task.title,
                step_title=step.title, kind="step_status", status="waiting_clarify",
                message="Đang chờ CEO trả lời câu hỏi làm rõ.", attempt_id=attempt_id,
            )
            return {"status": STATUS_PAUSED, "pause_reason": "clarify",
                    "cost_usd": result.get("cost_usd"),
                    "delivered": False, "room_message": ""}
        if result.get("status") == "awaiting_approval":
            store.mark_awaiting_approval(task_id, step_id, attempt_id=attempt_id)
            _record_capture(
                attempt_id=attempt_id, task_id=task_id, step=step, engine=engine,
                status="awaiting_approval", telemetry=telemetry, cost_usd=result.get("cost_usd"),
                started_at=started_at, t0=t0, error=None,
            )
            return {"status": STATUS_PAUSED, "pause_reason": "approval",
                     "cost_usd": result.get("cost_usd"),
                     "delivered": False, "room_message": ""}
        import json as _json

        cost = result.get("cost_usd")
        split = result.get("split_proposal") or None
        store.mark_done(
            task_id, step_id,
            outcome_ref=f"team-tasks/{task_id}/step-{step.seq}.json", cost_usd=cost,
            attempt_id=attempt_id,
            split_proposal_json=_json.dumps(split, ensure_ascii=False) if split else None,
        )
        _record_capture(
            attempt_id=attempt_id, task_id=task_id, step=step, engine=engine,
            status="done", telemetry=telemetry, cost_usd=cost,
            started_at=started_at, t0=t0, error=None,
            # v54 P4b: attach the review's own per-criterion list to ITS capture row —
            # `result.get("criteria")` is only ever non-empty for a review-step's result
            # (see `_run_review`/`review_graph.run_review_step`); `None` for every other
            # step_type keeps the column NULL exactly like before this phase existed.
            criteria=result.get("criteria") if step.step_type == "review" else None,
        )
        room_message = result.get("room_message", "")
        if step.step_type == "review":
            _append_review_event(
                task_id, author=step.assigned_to, task_title=task.title,
                step_title=step.title, passed=result.get("passed"),
                failures=result.get("failures") or [],
                criteria=result.get("criteria") or [],
            )
        else:
            _append_step_event(
                task_id, author=step.assigned_to, task_title=task.title, step_title=step.title,
                kind="handoff", status="done", message=room_message,
            )
        return {
            "status": STATUS_DONE, "cost_usd": cost, "delivered": bool(result.get("delivered")),
            "room_message": room_message,
        }
    except Exception as exc:
        # The graph or store call failed — mark the step failed so a stuck lease
        # doesn't block the DAG forever, then re-raise so the WORKER (caller) writes
        # the failed outcome artifact + failed run-event + exit 1 (single place that
        # does artifact writes on the failure path, matching every other exit).
        try:
            store.mark_failed(task_id, step_id, attempt_id=attempt_id)
        except Exception:  # noqa: BLE001 — never let a store write mask the original error
            logger.exception("team-step %s/%s: failed to record failure status", task_id, step_id)
        _task = locals().get("task")
        _step = locals().get("step")
        # Capture the failed attempt — but only if the step was resolved (a pre-work failure,
        # e.g. the store read raised, has no attempt to describe; mirror the existing defensive
        # `locals().get("step")` idiom so we don't emit a spurious row/WARNING).
        if _step is not None:
            _record_capture(
                attempt_id=attempt_id, task_id=task_id, step=_step, engine=engine,
                status="failed", telemetry=telemetry, cost_usd=None,
                started_at=started_at, t0=t0, error=str(exc)[:500],
            )
        _append_step_event(
            task_id, author=_step.assigned_to if _step is not None else "coordinator",
            task_title=_task.title if _task is not None else task_id,
            step_title=_step.title if _step is not None else step_id,
            kind="step_status", status="failed", message="", attempt_id=attempt_id,
        )
        raise
    finally:
        store.close()


def _record_capture(
    *, attempt_id: str, task_id: str, step, engine: str, status: str, telemetry,
    cost_usd, started_at: str, t0: float, error: str | None,
    criteria: list[dict] | None = None,
) -> None:
    """Write one per-attempt telemetry row — best-effort, must NEVER fail the step.

    Telemetry is an observability side-channel: a broken capture write is logged at WARNING
    (with the exception, not silently) but does not abort the step, which has already done its
    real work and recorded its outcome in the team-task store. `ended_at`/`duration_ms` are
    computed here from the monotonic clock started in the caller's own process.

    `criteria` (v54 P4b): the review step's per-criterion list, or `None` for every other
    caller/step_type — see `CaptureStore.record`'s own docstring for the storage contract.
    """
    import time
    from datetime import UTC, datetime

    ended_at = datetime.now(UTC).isoformat()
    duration_ms = int((time.monotonic() - t0) * 1000)
    try:
        from my_crew.runtime.capture_store import CaptureStore
        from my_crew.runtime.team_task_paths import capture_db_path

        cs = CaptureStore(capture_db_path())
        try:
            cs.record(
                attempt_id=attempt_id, task_id=task_id,
                step_id=getattr(step, "step_id", "") or str(step.seq),
                agent_id=step.assigned_to, engine=engine, status=status,
                step_type=step.step_type, review_round=step.review_round,
                cost_usd=cost_usd, cost_source=telemetry.cost_source,
                input_tokens=telemetry.input_tokens, output_tokens=telemetry.output_tokens,
                started_at=started_at, ended_at=ended_at, duration_ms=duration_ms, error=error,
                criteria=criteria,
            )
        finally:
            cs.close()
    except Exception as exc:  # noqa: BLE001 — telemetry must never fail a completed step
        logger.warning(
            "team-step %s/%s: capture record failed (step still done): %s",
            task_id, step.step_id, exc,
        )


def _append_step_event(
    task_id: str, *, author: str, task_title: str, step_title: str, kind: str, status: str,
    message: str, attempt_id: str | None = None,
) -> None:
    """try/degrade room-event append for one step's outcome (done → `handoff` with the
    graph's own `room_message`; failed → `step_status`) — never raises, matching
    `office_room_append.append_office_event`'s own contract.

    `assigned_to` always equals `author` here (the worker posting its OWN outcome), but
    is still carried explicitly in the body — the office-room reducer keys a desk by
    `assigned_to`, never by `author`, so every `step_status`/`handoff` producer (this one
    and the ticker's `started` event) agrees on one field name regardless of who the
    authoring identity is.
    """
    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    body: dict[str, str] = {"task_title": task_title, "step_title": step_title, "status": status,
                            "assigned_to": author}
    # Carry the attempt_id whenever the caller has one (failed/waiting_clarify — the
    # phase events already do): the FE's zombie-attempt guard can only drop a
    # superseded worker's event if the event NAMES its attempt. Without it, a stale
    # `failed` from a re-reserved step paints a false red desk over the live retry
    # (review M1). `attempt_id` is already an allowlisted step_status field.
    if attempt_id:
        body["attempt_id"] = attempt_id
    if kind == "handoff":
        body["message"] = message
    append_office_event(room_for_task(task_id), author=author, kind=kind, body=body,
                        also_office=True)


def _append_review_event(
    task_id: str, *, author: str, task_title: str, step_title: str, passed: bool | None,
    failures: list[str], criteria: list | None = None,
) -> None:
    """try/degrade room-event append for a review-step's own verdict (M32) — never
    raises, matching `office_room_append.append_office_event`'s own contract.

    `passed is None` means `run_review_step` returned `"stale_artifact"` (no verdict
    was actually reached, the ticker will re-queue a fresh review) — no room event is
    posted for that outcome, since "cần sửa (0 lỗi)" would misreport a re-queue as a
    real failed review. Only a genuine verdict (`passed` True/False) is ever surfaced
    to the room, carrying `failure_count` (never the failure list itself — see
    `office_event_projection`'s `review` allowlist) so the CEO/staff see a count, not
    reviewed-content-echoing detail.
    """
    if passed is None:
        return
    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    body: dict[str, object] = {
        "task_title": task_title, "step_title": step_title,
        "verdict": "passed" if passed else "needs_rework",
        "failure_count": len(failures), "assigned_to": author,
    }
    # v34 P5: per-criterion COUNTS only (never the criterion text — same
    # no-content-echo posture as failure_count vs the failures list).
    if criteria:
        body["criteria_total"] = len(criteria)
        body["criteria_passed"] = sum(1 for c in criteria if (c or {}).get("passed"))
    append_office_event(room_for_task(task_id), author=author, kind="review", body=body,
                        also_office=True)


def _run_review(
    loaded: Any, settings: Any, *, task_id: str, step, store: Any, telemetry=None,
) -> dict:
    """Dispatch body for `step_type == "review"` (M32) — the reviewer's own worker run.

    Unlike `_run_graph` (perceive→work→self_check→...→deliver, a LangGraph build),
    `review_graph.run_review_step` is three plain sequential calls with one early exit
    (stale artifact) — no branching/looping worth a graph object, see that module's
    docstring. `review_input.parent_seq`/`locked_version`/`acceptance` all come from the
    REVIEWED content step (`step.parent_step_id`), read fresh from the store here rather
    than trusted off any caller-supplied state, since a review-step's OWN `deps` may
    point at a rework row (round >=1), not the original content step directly.
    """
    from my_crew.agent.review_graph import ReviewStepInput, run_review_step

    content_step = store.get_step(task_id, step.parent_step_id) if step.parent_step_id else None
    if content_step is None:
        logger.warning(
            "review-step %s/%s: parent_step_id %r not found — cannot run review",
            task_id, step.step_id, step.parent_step_id,
        )
        return {"status": "stale_artifact", "cost_usd": None, "delivered": False,
                "room_message": "", "passed": None, "failures": []}

    # The GRADED artifact is whatever `deps[0]` points at — the content step itself
    # for round 0, or the LATEST rework step for round >=1 (each rework writes its own
    # `step-<seq>.json`, never overwriting the content step's) — `graded_seq`/
    # `locked_version` both come from THAT row, re-read fresh here (not trusted off a
    # stale copy) so a dep that itself re-ran between mint and this run is caught as a
    # stale-artifact mismatch instead of silently grading content nobody will see.
    dep_step_id = step.deps[0] if step.deps else step.parent_step_id
    dep_step = store.get_step(task_id, dep_step_id)
    graded_seq = dep_step.seq if dep_step is not None else content_step.seq
    locked_version = (dep_step.attempt_id or "") if dep_step is not None else ""

    from my_crew.runtime.team_task_paths import team_tasks_root

    review_input = ReviewStepInput(
        task_id=task_id, graded_seq=graded_seq, verdict_seq=content_step.seq,
        review_round=step.review_round, locked_version=locked_version,
        acceptance=content_step.acceptance, step_title=content_step.title,
    )
    return run_review_step(
        loaded, settings, data_dir=team_tasks_root(), review_input=review_input,
        telemetry=telemetry,
    )


def _run_graph(
    loaded: Any, settings: Any, *, task_id: str, step, attempt_id: str = "",
    task_title: str = "", on_node: Callable[[], None] | None = None, telemetry=None,
) -> dict:
    """Build + invoke the team_task_graph for one step, checkpointed (v34 P1).

    Checkpoint semantics: thread_id is `team:<task_id>:<step_id>` — attempt-AGNOSTIC,
    because the whole point is that a NEW attempt (minted after a crash/kill) adopts
    the previous attempt's mid-step progress instead of re-paying completed nodes.
    On dispatch:
      - a mid-run checkpoint exists → adopt it: `update_state` stamps the CURRENT
        `attempt_id` into the saved state (terminal store writes must match the
        current lease, never the dead attempt's), then stream(None) resumes at the
        next node;
      - a FINISHED checkpoint exists (crash landed between graph-END and the store's
        `mark_done`) → return the saved state without re-running anything — deliver
        already wrote the artifact, re-running would double-deliver;
      - no checkpoint (the overwhelmingly common case) → fresh run, byte-identical
        to the pre-v34 path.
    ANY checkpoint failure (open/read/schema drift after a code change) degrades to a
    fresh un-checkpointed run — resume is an optimization, never a gate. The thread is
    deleted eagerly once the graph reaches END; the ticker sweeps leftovers of tasks
    that ended without a clean delete.

    `on_node`, when given, is called after EACH `updates`-mode chunk (one per node
    finishing) — the heartbeat hook that keeps a genuinely-still-working step's lease
    from expiring mid-run. `stream_mode=["updates","custom"]` (a LIST) makes
    `.stream()` yield `(mode, chunk)` TUPLES instead of bare chunks — `updates` chunks
    are node-output dicts (as before, merged into `state`); `custom` chunks are
    whatever a node's own `get_stream_writer()` call emitted (`{"phase": ...}` from
    work/self_check/rework) and are turned into a room `step_status` event carrying
    `body.phase` + `body.attempt_id` (so the FE can drop a stale/zombie attempt's
    events — see `office_event_projection`'s `phase` allowlist). Heartbeat fires ONLY
    on `updates` chunks (once per node), never once per `custom` chunk, so a node that
    writes multiple custom events in one run does not multiply heartbeat writes.
    """
    from my_crew.company_docs.pool import load_company_docs
    from my_crew.memory.provider import resolve_memory_text
    from my_crew.profile.capability_block import build_capability_block
    from my_crew.profile.context import EMPTY, ProfileContext
    from my_crew.runtime.team_task_paths import team_tasks_root
    from my_crew.skills.skill_pool import build_skill_context

    if loaded is not None:
        skills, selector = build_skill_context(loaded, settings)
        # Capability block is INTERNAL-only (rides build_context_block); pack=None keeps
        # this step-runner off the pack-load path (report_kinds line is simply omitted).
        context = ProfileContext(
            persona=loaded.soul, project=loaded.project, memory=resolve_memory_text(loaded),
            capability=build_capability_block(loaded, None),
            skills=skills, skill_selector=selector,
            company_docs=load_company_docs(getattr(loaded, "company_docs", ())),
        )
    else:
        context = EMPTY

    # v20: route the team-step build through the AgentRuntime seam. `loaded` may be None
    # (a step whose profile failed to load still runs with EMPTY context) — resolve_runtime
    # degrades that to native. NativeGraphRuntime.build_task delegates to build_team_task_graph
    # unchanged, so native output is byte-identical.
    from my_crew.runtime_backends.protocol import resolve_step_runtime

    # v45: resolve the runtime PER STEP — a no-shell step on a deep_agent-pinned agent drops to
    # the fast, Docker-free create_agent tier; a needs_shell step escalates to deep_agent (or fails
    # loud if the agent has no sandbox). The `_extra` wiring below is gated on the EFFECTIVE kind,
    # not the profile kind, so a dropped step feeds the tool-calling runtime the right kwargs (each
    # runtime already pops what it doesn't use — v43/v44). `loaded=None` → native (degrade path).
    runtime = resolve_step_runtime(loaded, step)
    effective_kind = type(runtime).__name__
    _is_non_native = effective_kind != "NativeGraphRuntime"

    # `reporting_config` is consumed only by a tool-calling runtime (read toolset); the native
    # runtime ignores it. NativeGraphRuntime.build_task passes **kwargs straight to
    # build_team_task_graph, which does not accept reporting_config — so pop-or-ignore lives in
    # the ToolCallingRuntime; native must not receive it. Only pass it for non-native.
    _extra = {}
    if loaded is not None and _is_non_native:
        _extra["reporting_config"] = loaded.config
        # v20.5: thread the per-runtime caps (loop limit / sandbox) to the runtime.
        _extra["runtime_config"] = loaded.agent_runtime
        # v31 P6: per-agent OpenAlex opt-in for the read toolset (keyless — the flag gates).
        _extra["academic_search"] = bool(getattr(loaded, "academic_search", False))
        # v39 #1: per-agent Google-Workspace-read opt-in (gws CLI OAuth is the credential).
        _extra["gws_context"] = bool(getattr(loaded, "gws_context", False))
        # v43: per-agent in-sandbox subagent delegation opt-in (deep_agent tier reads it; other
        # non-native runtimes ignore the kwarg — see DeepAgentRuntime.build_task pop).
        _extra["deep_team"] = bool(getattr(loaded, "deep_team", False))
        # v44: optional per-agent delegation-cap override (None ⇒ default in the loop).
        _extra["deep_team_max_calls"] = getattr(loaded, "deep_team_max_calls", None)
    # v20.5 Phase 0: wire the team-step external_write hook to the per-agent Action Gateway when
    # the agent opted into step egress. Absent ⇒ external_write stays None (deliver writes only
    # the internal artifact — byte-identical pre-v20.5).
    external_write = _resolve_external_write(loaded, settings)
    if external_write is not None:
        _extra["external_write"] = external_write
    # Remember-node: extract salient facts from this step's output into the assignee's MEMORY.md
    # after deliver, folding the extraction cost into the step total (capture honesty). Built only
    # for a real loaded profile (a step whose profile failed to load has no MEMORY.md to write).
    from my_crew.agent.memory_node import build_team_step_remember_node

    remember_node = (
        build_team_step_remember_node(step.assigned_to, settings) if loaded is not None else None
    )
    checkpointer = _team_checkpointer_best_effort()
    if checkpointer is not None:
        _extra["checkpointer"] = checkpointer
    # v34 P4 depth-1 guard at the cheapest spot: only an ORIGINAL confirmed work step
    # may propose a runtime split — sub/gather/review/rework rows never re-split.
    _extra["allow_split"] = (
        getattr(step, "parent_step_id", None) is None
        and not getattr(step, "system_inserted", False)
        and getattr(step, "step_type", "work") == "work"
    )
    graph = runtime.build_task(
        settings=settings, context=context, step_title=step.title,
        data_dir=team_tasks_root(), task_id=task_id, step_seq=step.seq,
        step_deps=step.deps, search_hook=_resolve_search_hook(loaded, settings),
        self_id=step.assigned_to, telemetry=telemetry, remember_node=remember_node, **_extra,
    )
    initial_state: dict[str, Any] = {
        "step_title": step.title, "acceptance": step.acceptance,
        "attempt_id": attempt_id, "version": attempt_id,
    }
    thread_id = f"team:{task_id}:{getattr(step, 'step_id', '') or step.seq}"
    config = {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None

    stream_input: dict[str, Any] | None = initial_state
    state: dict[str, Any] = dict(initial_state)
    if checkpointer is not None:
        stream_input, state, finished = _load_resume_state(
            graph, config, initial_state, attempt_id=attempt_id,
            task_id=task_id, step_id=getattr(step, "step_id", "") or str(step.seq),
        )
        if finished is not None:
            if finished.get("status") != "waiting_clarify":
                # A still-pending clarify "finished" is a REPORT, not an end-state —
                # its thread IS the resume state; deleting it would wedge the step
                # (review H2).
                _delete_thread_best_effort(checkpointer, thread_id)
            return finished

    for mode, chunk in graph.stream(stream_input, config, stream_mode=["updates", "custom"]):
        if mode == "updates":
            # v34 P2: an interrupt chunk means await_clarify paused the graph on a
            # pending CEO question — surface it as the step outcome instead of a
            # completed state. The payload carries the clarify_id the ticker polls.
            if isinstance(chunk, dict) and "__interrupt__" in chunk:
                intr = chunk["__interrupt__"]
                payload = getattr(intr[0], "value", {}) if intr else {}
                state["status"] = "waiting_clarify"
                state["clarify_id"] = (payload or {}).get("clarify_id")
                continue
            for node_output in chunk.values():
                if isinstance(node_output, dict):
                    state.update(node_output)
            if on_node is not None:
                on_node()
        elif mode == "custom" and isinstance(chunk, dict):
            phase = chunk.get("phase")
            if phase:
                _append_step_phase_event(
                    task_id, author=step.assigned_to, task_title=task_title,
                    step_title=step.title, phase=str(phase), attempt_id=attempt_id,
                    deep_team=bool(_extra.get("deep_team")),
                )
    if checkpointer is not None and state.get("status") != "waiting_clarify":
        # ONLY waiting_clarify keeps its thread (the mid-run interrupt IS the resume
        # state). Everything else — including an awaiting_approval END-state — is
        # deleted here: post-approval the step re-runs deliver fresh (see
        # _load_resume_state), so a kept thread would only mislead the next attempt
        # into short-circuiting.
        # The graph reached END (or raised out of this function before we get here —
        # in which case the thread stays for the NEXT attempt to resume). A paused
        # (awaiting_approval) step keeps its thread too: that is a legitimate mid-step
        # stop the resume path exists for.
        _delete_thread_best_effort(checkpointer, thread_id)
    return state


def _team_checkpointer_best_effort():
    """Open the shared team checkpointer, or None — resume is an optimization; a
    broken/locked checkpoint DB must never stop a step from running fresh."""
    try:
        from my_crew.agent.checkpoint import get_team_checkpointer

        return get_team_checkpointer()
    except Exception:  # noqa: BLE001 — degrade to un-checkpointed, exactly pre-v34
        logger.warning("team checkpointer unavailable — running un-checkpointed",
                       exc_info=True)
        return None


def _load_resume_state(
    graph, config, initial_state: dict[str, Any], *, attempt_id: str,
    task_id: str, step_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    """(stream_input, state_seed, finished_state) for a possibly-resumable thread.

    - no checkpoint → (initial_state, initial_state, None): fresh run.
    - mid-run checkpoint → (None, adopted_state, None): stream(None) resumes; the
      saved state is stamped with the CURRENT attempt_id first (update_state), so
      every downstream artifact/store write matches the live lease.
    - finished checkpoint → (None, values, values): caller returns it directly —
      deliver already ran; re-running would double-deliver.
    ANY error → fresh run (resume must never become a gate).
    """
    try:
        snapshot = graph.get_state(config)
        if snapshot is None or not snapshot.values:
            return initial_state, dict(initial_state), None
        if not snapshot.next:  # graph previously reached END
            finished = dict(snapshot.values)
            finished.setdefault("status", "")
            if finished.get("status") == "awaiting_approval":
                # The graph COMPLETED but deliver stopped short at the Lớp B gate —
                # after approval the step must actually re-run deliver, so this
                # end-state is NOT reusable. Fresh run (same thread id gets fresh
                # checkpoints; the gateway's dedup keeps the external write single).
                return initial_state, dict(initial_state), None
            logger.info("team-step %s/%s: found FINISHED checkpoint — skipping re-run",
                        task_id, step_id)
            return None, finished, finished
        adopt = {"attempt_id": attempt_id, "version": attempt_id}
        state = dict(snapshot.values)
        state.update(adopt)
        pending_interrupt = any(
            getattr(t, "interrupts", ()) for t in (snapshot.tasks or ())
        )
        # NOTE: update_state happens ONLY on a real resume (below) — touching an
        # interrupted thread's state while the clarify is still pending would consume
        # the interrupt and wedge the eventual resume (review H2 follow-on).
        if pending_interrupt:
            # v34 P2: the thread paused on await_clarify. Resolve the CEO's answer
            # from the clarify store: answered → resume with it; expired → resume
            # with "" (safe default — the draft ships as-is); still pending → the
            # dispatch was premature, report waiting_clarify again without running.
            resume_input, still_waiting = _clarify_resume_input(snapshot)
            if still_waiting:
                # Carry the clarify_id OUT of the interrupt payload (review H2): the
                # snapshot's `values` never contain it, and the caller re-marks the
                # step waiting_clarify with this id — a None here would produce an
                # un-pollable row after a crash in the interrupt→mark window.
                waiting = dict(state)
                waiting["status"] = "waiting_clarify"
                waiting["clarify_id"] = _interrupt_clarify_id(snapshot)
                return None, waiting, waiting
            graph.update_state(config, adopt)
            logger.info("team-step %s/%s: resuming clarify interrupt", task_id, step_id)
            return resume_input, state, None
        graph.update_state(config, adopt)
        logger.info("team-step %s/%s: resuming checkpoint at %s (attempt adopted)",
                    task_id, step_id, ",".join(snapshot.next))
        return None, state, None
    except Exception:  # noqa: BLE001 — schema drift / tampered DB: run fresh
        logger.warning("team-step %s/%s: checkpoint unusable — running fresh",
                       task_id, step_id, exc_info=True)
        return initial_state, dict(initial_state), None


def _interrupt_clarify_id(snapshot) -> int | None:
    """The clarify_id riding a paused thread's interrupt payload, or None."""
    for t in getattr(snapshot, "tasks", ()) or ():
        for intr in getattr(t, "interrupts", ()) or ():
            value = getattr(intr, "value", None)
            if isinstance(value, dict) and value.get("clarify_id") is not None:
                return value["clarify_id"]
    return None


def _clarify_resume_input(snapshot):
    """(stream_input, still_waiting) for a thread paused on a clarify interrupt.

    Reads the interrupt payload's clarify_id and asks the ClarifyStore:
    answered → Command(resume=answer); expired/unknown → Command(resume="") (safe
    default, never wedge); pending → (None, True) — do not run, stay paused."""
    from langgraph.types import Command

    clarify_id = _interrupt_clarify_id(snapshot)
    if clarify_id is None:
        return Command(resume=""), False  # unpollable — proceed on the safe default
    from my_crew.runtime.clarify_service import clarify_status

    status = clarify_status(int(clarify_id))
    if status is None:
        return Command(resume=""), False
    st, answer = status
    if st == "answered":
        return Command(resume=answer), False
    if st == "expired":
        return Command(resume=""), False
    return None, True  # pending — stay paused


def _delete_thread_best_effort(checkpointer, thread_id: str) -> None:
    try:
        checkpointer.delete_thread(thread_id)
    except Exception:  # noqa: BLE001 — cleanup is hygiene; the ticker sweep catches leftovers
        logger.warning("team-step: checkpoint thread cleanup failed for %s", thread_id,
                       exc_info=True)


def _append_step_phase_event(
    task_id: str, *, author: str, task_title: str, step_title: str, phase: str, attempt_id: str,
    deep_team: bool = False,
) -> None:
    """try/degrade room-event append for a mid-run phase transition (work/self_check/
    rework) — never raises, matching `office_room_append.append_office_event`'s own
    contract. Duplicate phase events across a retry (a fresh attempt re-runs
    perceive→work→...) are expected/acceptable: the room is an append-only timeline
    and the FE keys the CURRENT phase display off `attempt_id`, not off "last event
    wins" — a stale attempt's phase event is simply dropped client-side.

    `deep_team` (v54): carried ONLY when True (the agent opted into in-sandbox subagent
    delegation for this step) — omitted otherwise, so a pre-v54/non-deep_team event body
    stays byte-identical (see `office_event_projection`'s `step_status` pass-through).
    """
    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    body: dict[str, Any] = {
        "task_title": task_title, "step_title": step_title, "status": "started",
        "assigned_to": author, "phase": phase, "attempt_id": attempt_id,
    }
    if deep_team:
        body["deep_team"] = True
    append_office_event(room_for_task(task_id), author=author, kind="step_status",
                        body=body, also_office=True)


def _resolve_search_hook(loaded: Any, settings: Any) -> Callable[[str], str] | None:
    """Build the real `search_hook` iff the agent's profile opted in (`web_search:
    true`) AND at least one provider key is configured — either gate absent ⇒ None
    (the graph's `work` node then skips search entirely, a clean no-op degrade).

    Wires `web_search`'s own `audit_log` param to the shared team-tasks audit trail
    (`team_tasks_root()/audit/audit.jsonl` — the same shared-root convention
    `team_task_paths.py` uses for the store DB and handoff artifacts; a team step is
    cross-agent by design, so its egress audit belongs in that shared trail, not a
    per-agent one) so every real search call — not just tests — leaves a redacted-query
    audit row, matching the Action Gateway's "no audit => no write" posture applied to
    this tool's own network egress.
    """
    if loaded is None or not getattr(loaded, "web_search", False):
        return None
    from my_crew.audit.audit_log import AuditLog
    from my_crew.runtime.team_task_paths import team_tasks_root
    from my_crew.tools.search_result_formatter import format_search_results
    from my_crew.tools.web_search_tool import WebSearchConfig, web_search

    config = WebSearchConfig(
        tavily_api_key=getattr(settings, "tavily_api_key", None),
        brave_api_key=getattr(settings, "brave_api_key", None),
    )
    if not config.available():
        return None

    audit_log = AuditLog(team_tasks_root() / "audit" / "audit.jsonl")

    def _hook(query: str) -> str:
        results = web_search(query, config=config, audit_log=audit_log)
        text, _count, _quarantined = format_search_results(results)
        return text

    return _hook


def _resolve_external_write(loaded: Any, settings: Any) -> Callable[[str], bool] | None:
    """Build the team-step external_write hook iff the agent opted into egress (v20.5 Phase 0).

    Returns None (deliver writes only the internal artifact) unless the agent's profile declares
    `team_step_egress: {channel}`. When set, builds the per-agent Action Gateway and a hook that
    posts a step's result to that channel THROUGH the gateway (Lớp A/B + audit) — no bypass.
    """
    if loaded is None:
        return None
    egress = getattr(loaded, "team_step_egress", None)
    if not egress or not egress.get("channel"):
        return None
    from datetime import UTC, datetime

    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.runtime.team_step_egress import make_external_write

    config = loaded.config
    gateway = ActionGateway(
        settings,
        external_channels=config.slack_external_channels,
        auto_approve=getattr(loaded, "auto_approve", None),
        actor=getattr(loaded, "profile_id", ""),  # v46: attribute audit/approval to the agent
    )
    report_date = datetime.now(UTC).date().isoformat()
    return make_external_write(
        gateway, config, loaded.profile_id, egress["channel"], report_date
    )
