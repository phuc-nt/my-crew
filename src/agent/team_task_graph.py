"""Task execution graph:
`perceive → work → (self_check | recover→work) → (deliver | rework→self_check)`.

Runs ONE step of a team task, on ONE agent, as the `team-step` generic run kind (see
`worker.py`). Per-agent isolation is unchanged — this graph runs inside the SAME
per-agent subprocess/data-dir/gateway every other report graph runs in; the only new
thing is where its input/output come from: not Jira/GitHub, but the team-task handoff
artifact(s) (`team_task_artifact`) written by this step's DEPENDENCIES.

  - `perceive`: reads the step brief (title + task context) + the handoff artifact(s)
    of this step's DEPENDENCIES (not simply "the previous step" — a DAG step's real
    upstream producer is its `deps`, see `_read_handoff`). No deps ⇒ empty context.
  - `work`: one LLM call with the agent's persona/skills/company docs injected (same
    seam every report graph uses), producing the step's result text. `search_hook`
    is an injectable, OPTIONAL web-search callable — None (no-op, the default) when
    the caller has no real search wired in. Runs exactly ONCE per attempt. Before the
    work LLM call, an OPTIONAL consult hook (`deps.ask_colleague`, M33) may ask up to
    `MAX_CONSULTS` colleagues one question each — a synchronous role-play consultation
    over a colleague's `SOUL.md`/`PROJECT.md` FILES (`team_task_consult.ask_colleague`),
    deliberately NOT the sibling-memory system (see that module's docstring for why).
    `deps.ask_colleague is None` ⇒ no consult, byte-identical to pre-M33 behavior.
  - `self_check`: one structured LLM call grading `result_text` against the step's
    `acceptance` criteria (`team_steps.acceptance`, metadata — see
    `task_decomposition.decomposition_content_hash`'s docstring for why it is not part
    of the DAG hash). Binary `passed` + `failures` list + `confidence` — routing
    (`route_after_check`) uses ONLY `passed` + the rework counter, never `confidence`
    (kept for observability/logging only).
  - `recover` (v14 "blocked-step tự cứu"): when the work LLM call itself RAISES (API
    error, provider outage, hard prompt rejection), the failure gets ONE bounded
    in-graph recovery pass before propagating: `recover` asks a colleague about the
    exact blocker (same consult seam/budget as pre-work consult, best-effort) and
    routes back to `work` for one retry with the advice folded into the context. The
    retry failing (or the consult being off) re-raises exactly as pre-v14 — the
    runner's mark_failed/escalate contract is untouched, this only gives a step one
    chance to unblock ITSELF before waking the CEO.
  - `rework`: re-runs the work LLM call with the ORIGINAL brief + the prior attempt's
    `result_text` + the self-check's structured `failures`, asking the model to fix
    ONLY the listed failures. Bumps `rework_count`. Capped at `max_rework` (2) —
    exhausted ⇒ `route_after_check` sends the LATEST result to `deliver` anyway with
    `self_check_failed=True` set (a stuck self-check must never block delivery
    forever; the CEO/room sees the flag instead).
  - `deliver`: writes the result to `step-<n>.json` (internal artifact — THE
    INVARIANT: no external write happens here) and returns a room-message payload
    (a short human-readable line the coordinator can post to the group chat). A step
    that itself needs an EXTERNAL write (e.g. "post this to Slack") does so through
    the normal per-agent `ActionGateway` via the optional `deps.external_write` hook,
    called from `deliver` BEFORE the internal artifact is written. If the gateway
    answers `pending_approval` (trust ladder / Lớp B queue — same contract as every
    other write path, see `action_gateway.GatewayResult`), `deliver` does NOT write
    the internal artifact yet and the graph reports `status: "awaiting_approval"` in
    its result instead of completing; the CALLER (`team_step_runner.run_team_step`)
    maps this to the worker's exit-3 / `awaiting_approval` step status.

No LangGraph checkpointer on this graph (`build_team_task_graph` compiles with
`checkpointer=None` — deliberate, see the module's design note below): each step's
graph run is a single in-process `.stream()` call, start to finish, within one
attempt. There is therefore no resumable in-flight state to restore mid-graph: the
coordinator ticker POLLS the step's stored `approval_id` against `ApprovalStore`
every tick (`coordinator_nodes.tick_actions.poll_awaiting_approval_step`) — once the
CEO resolves it out-of-band (`mpm approve`/`mpm reject`), the very next tick
re-reserves the SAME step (a FRESH `attempt_id`) and it re-runs
`perceive → work → self_check → ... → deliver` from scratch (approve) or marks it
`failed` + escalates (reject). Rework/self-check counters live only in this one
attempt's in-memory state (`total=False` TypedDict, primitives only) and are NOT
persisted across attempts — a retried step starts its rework budget fresh, matching
"retry = fresh attempt re-run" (there is no production caller that resumes the SAME
attempt_id mid-graph: every re-spawn mints a new one, `reserve_step`
`team_task_steps.py`). `deliver`'s external write MUST therefore be idempotent/
safe-to-retry from the gateway's own dedup, exactly like every other scheduled
report's external delivery.

State holds only primitives (checkpoint-safe shape, even though nothing is actually
checkpointed here), matching every other report graph's state discipline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from src.company_docs.inject import company_docs_text
from src.profile.context import EMPTY, ProfileContext
from src.skills.skill_selector import select_skill_text

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)

#: Optional web-search hook: query -> result text. None (default) ⇒ `work` skips
#: search entirely.
SearchHook = Callable[[str], str]

#: Optional consult hook: (colleague_agent_id, question) -> (answer, cost_usd). Mirrors
#: `SearchHook`'s "None ⇒ no-op" contract (M33) — see `TeamTaskDeps.ask_colleague`.
AskColleagueHook = Callable[[str, str], tuple[str, float]]

#: Hard ceiling on rework attempts per step run — exhausted ⇒ deliver anyway with
#: `self_check_failed=True` (a stuck self-check must never loop forever, R5).
MAX_REWORK = 2

#: Hard ceiling on consults per step ATTEMPT (M33, `TeamStepState.consult_count`,
#: reset per attempt like `rework_count`) — matches `team_task_consult.MAX_CONSULTS`
#: (duplicated as a plain int, not imported, so this module never needs a hard import
#: of `team_task_consult` just to read a constant — the graph shape must not depend on
#: the consult module's own internals, only on the `deps.ask_colleague` callable shape).
MAX_CONSULTS = 2

#: Hard ceiling on in-graph recovery attempts per step ATTEMPT (v14 "blocked-step tự
#: cứu"): a `work` LLM failure gets ONE consult-then-retry pass through the `recover`
#: node before the exception propagates exactly as it always did (runner marks the step
#: failed + escalates). Bounded like `MAX_REWORK` — counter-in-state, primitives only.
MAX_RECOVER = 1

#: Cap on how much of a work-failure's exception text rides into state/consult prompts —
#: enough to describe the blocker, never a full traceback/content echo.
_WORK_ERROR_CHARS = 200

#: Custom stream-writer phase tags (`team_step_runner._run_graph` maps these to a
#: room `step_status` event's `body.phase`) — one per node that does real work. Each
#: tag MUST also be in `office_event_projection._STEP_PHASES` (write-time allowlist)
#: and the FE's `speech-bubble.tsx` PHASE_LABEL, or the room event drops/hides it.
PHASE_WORK = "dang-lam"
PHASE_SELF_CHECK = "tu-soat"
PHASE_REWORK = "dang-sua"
PHASE_RECOVER = "nho-tro-giup"


class TeamStepState(TypedDict, total=False):
    """State for one team-task step run. `total=False`: each node fills its slice."""

    step_title: str  # the step's brief (what this agent must do)
    handoff_context: str  # deps' result text(s), "" if this step has no deps
    result_text: str  # this step's produced output (written to the artifact)
    cost_usd: float | None
    room_message: str  # short line for the group-chat room (deliver's output)
    delivered: bool  # True once the artifact write succeeds
    status: str  # "done" (default) | "awaiting_approval" — set by deliver
    # --- self-check / rework loop (all primitives, reset per attempt by design) ---
    acceptance: str  # this step's self-check rubric (team_steps.acceptance)
    rework_count: int
    max_rework: int
    self_check_passed: bool
    check_failures: list[str]
    check_confidence: float
    check_reasons: list[str]  # appended each self_check pass, for observability
    attempt_id: str
    version: str  # == attempt_id (deliver artifact provenance, see module docstring)
    self_check_failed: bool  # True iff rework was exhausted without a passing check
    # --- consult (M33, all primitives, reset per attempt by design) ---
    consult_count: int  # how many ask_colleague calls this attempt has made so far
    consult_log: list[str]  # short "asked <id>: <question>" lines, observability-only
    # Accumulated "[Tham vấn <id>] <answer>" blocks — PERSISTED in state (not a work-
    # local variable) so a recovery retry still sees the answers the FIRST pass paid
    # for even when the recover consult itself came up empty (v14 review finding M1).
    consult_context: str
    # --- blocked-step recovery (v14, all primitives, reset per attempt by design) ---
    work_error: str  # truncated failure text from the last work call, "" once handled
    recover_count: int  # how many recover passes this attempt has burned (<= MAX_RECOVER)
    recover_hint: str  # colleague's unblock advice, folded into the retry's handoff


@dataclass
class TeamTaskDeps:
    """Injectable collaborators for the team-task step flow (real or fake in tests)."""

    # perceive: reads the handoff artifact(s) left by this step's DEPS (or "" if none).
    read_handoff: Callable[[], str]
    # work: runs the LLM call (persona/skills/company docs already folded in by the
    # caller) and returns (result_text, cost_usd). Receives the resolved search hook.
    run_work: Callable[[str, str, SearchHook | None], tuple[str, float | None]]
    # self_check: grades result_text against acceptance criteria. Returns
    # (passed, failures, confidence).
    run_self_check: Callable[[str, str], tuple[bool, list[str], float]]
    # rework: re-runs the work call with the original brief + prior output + the
    # self-check's structured failures. Returns (new_result_text, cost_usd).
    run_rework: Callable[[str, str, list[str]], tuple[str, float | None]]
    # deliver: writes the internal artifact + builds the room message; returns
    # (delivered, room_message).
    deliver_step: Callable[[str, str, bool], tuple[bool, str]]
    search_hook: SearchHook | None = None
    # Optional external write (e.g. post to Slack) attempted BEFORE the internal
    # artifact write. Returns True (proceed to internal artifact write) or False
    # (gateway answered pending_approval — deliver stops short, graph reports
    # status="awaiting_approval"). None (default): no external write, always proceeds.
    external_write: Callable[[str], bool] | None = None
    # M33: optional consult hook — (colleague_agent_id, question) -> (answer, cost_usd).
    # None (default, no-op): `work` skips consult entirely, byte-identical to pre-M33
    # behavior. See `AskColleagueHook`/`team_task_consult.ask_colleague`.
    ask_colleague: AskColleagueHook | None = None
    # M33: optional pre-work TARGETING hook — (step_title, handoff_context) -> up to
    # MAX_CONSULTS (colleague_agent_id, question) pairs, the ONE structured LLM call
    # that decides who/what to consult (KISS v1: bounded, not a tool-calling loop; see
    # `team_task_consult_propose.propose_consult_targets`). None (default, no-op): no
    # targets are ever proposed, so `ask_colleague` (even if wired) is never invoked —
    # matches `ask_colleague=None`'s "consult off" contract.
    propose_consults: Callable[[str, str], list[tuple[str, str]]] | None = None
    # M33: optional per-attempt context setter — `work` calls this ONCE, before any
    # `ask_colleague` call, with the current attempt's `attempt_id` (state carries it,
    # but `ask_colleague`'s own signature is fixed to `(agent_id, question)`, matching
    # `SearchHook`'s shape, so it cannot ride as a call argument). None (default,
    # no-op) when consult is off (`ask_colleague is None`) — nothing to set.
    set_attempt_id: Callable[[str], None] | None = None


def default_team_task_deps(
    *,
    settings: Settings,
    context: ProfileContext = EMPTY,
    step_title: str,
    data_dir: Any,
    task_id: str,
    step_seq: int,
    step_deps: tuple[str, ...] = (),
    search_hook: SearchHook | None = None,
    self_id: str = "",
) -> TeamTaskDeps:
    """Wire the real collaborators. Lazy imports keep graph-build network-free.

    `data_dir`/`task_id`/`step_seq` locate THIS step's own handoff artifact (what
    `deliver` writes). `step_deps` (the step's own `deps` step_ids, from
    `TeamStep.deps`) is what `perceive` reads FROM — mapped to seqs via the store
    (`_read_handoff` is DEPS-aware, not "seq - 1"; see that function's docstring).
    `acceptance`/`attempt_id` are NOT closure params here — they ride in the graph's
    initial state instead (`team_step_runner._run_graph` seeds them), since both are
    per-attempt values the state schema already carries (`state["acceptance"]`,
    `state["attempt_id"]`) and nodes read directly from state.

    `self_id` (M33): the assignee running THIS step — required for `ask_colleague`'s
    "never consult yourself" guard. Blank (default) ⇒ `ask_colleague` is wired as None
    (consult off, byte-identical pre-M33 behavior) rather than wiring a real hook that
    could not tell "colleague" from "self"; a caller that wants consult enabled MUST
    pass the real assignee id.
    """
    from src.llm.client import LlmClient
    from src.llm.team_task_check_prompt import (
        build_rework_messages,
        build_self_check_messages,
        parse_check_verdict,
    )
    from src.llm.team_task_prompt import build_team_step_messages

    llm_box: dict[str, LlmClient] = {}

    def _llm() -> LlmClient:
        llm = llm_box.get("llm")
        if llm is None:
            llm = LlmClient(settings)
            llm_box["llm"] = llm
        return llm

    def _read_handoff() -> str:
        return _read_deps_handoff(data_dir, task_id, step_deps)

    def _run_work(
        title: str, handoff: str, hook: SearchHook | None
    ) -> tuple[str, float | None]:
        search_text = ""
        if hook is not None:
            try:
                search_text = hook(title)
            except Exception as exc:  # noqa: BLE001 — search is best-effort, never fatal
                logger.warning("team-step search hook failed, continuing without it: %s", exc)
                search_text = ""
        try:
            result = _llm().complete(
                build_team_step_messages(
                    step_title=title,
                    handoff_context=handoff,
                    search_context=search_text,
                    persona=context.persona,
                    project=context.project,
                    memory=context.memory,
                    capability=context.capability,
                    skills=select_skill_text(context, "internal", kind="team-step"),
                    company_docs=company_docs_text(context, "internal"),
                )
            )
            return result.content, result.cost_usd
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a failed step
            logger.warning("team-step work failed: %s", exc)
            raise

    def _run_self_check(result_text: str, criteria: str) -> tuple[bool, list[str], float]:
        if not criteria.strip():
            # No rubric was ever set for this step (`acceptance` blank) — nothing to
            # grade against, so self-check trivially passes rather than inventing a
            # criteria-less judgment call.
            return True, [], 1.0
        try:
            result = _llm().complete(
                build_self_check_messages(
                    result_text=result_text, acceptance=criteria, persona=context.persona,
                )
            )
            verdict = parse_check_verdict(result.content)
            return verdict.passed, list(verdict.failures), verdict.confidence
        except Exception as exc:  # noqa: BLE001 — a broken self-check must never block
            # delivery (self-check is a QUALITY gate, not a safety gate) — fail OPEN.
            logger.warning("team-step self_check failed, treating as passed: %s", exc)
            return True, [], 0.0

    def _run_rework(
        brief: str, prior_output: str, failures: list[str]
    ) -> tuple[str, float | None]:
        try:
            result = _llm().complete(
                build_rework_messages(
                    brief=brief, prior_output=prior_output, failures=failures,
                    persona=context.persona,
                )
            )
            return result.content, result.cost_usd
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller as a failed step
            logger.warning("team-step rework failed: %s", exc)
            raise

    def _deliver(result_text: str, version: str, self_check_failed: bool) -> tuple[bool, str]:
        from src.agent.team_task_artifact import write_step_artifact

        write_step_artifact(
            data_dir, task_id, step_seq,
            {
                "status": "done", "result_text": result_text, "step_title": step_title,
                "attempt": version, "version": version, "self_check_failed": self_check_failed,
            },
        )
        room_message = _room_message(step_title, result_text)
        return True, room_message

    ask_colleague_hook: AskColleagueHook | None = None
    propose_consults_hook: Callable[[str, str], list[tuple[str, str]]] | None = None
    set_attempt_id_hook: Callable[[str], None] | None = None
    if self_id:
        # Single-slot mutable box for the CURRENT attempt's `attempt_id` (same
        # lazy-init idiom `llm_box` above uses) — `ask_colleague`'s deps-facing
        # signature is fixed to `(agent_id, question)` (matches `SearchHook`'s
        # shape), so the per-attempt `attempt_id` (needed only for the room event's
        # `body.attempt_id`, see `team_task_consult.ask_colleague`) cannot ride as a
        # call argument. `work` calls `deps.set_attempt_id(state["attempt_id"])`
        # once, before any consult, to fill this box for the closures below.
        attempt_box: dict[str, str] = {"attempt_id": ""}

        def _set_attempt_id(attempt_id: str) -> None:
            attempt_box["attempt_id"] = attempt_id

        def _ask_colleague(agent_id: str, question: str) -> tuple[str, float]:
            from src.agent.team_task_consult import ask_colleague
            from src.runtime.office_room_append import room_for_task

            return ask_colleague(
                agent_id, question, settings=settings, self_id=self_id,
                room_id=room_for_task(task_id), attempt_id=attempt_box["attempt_id"],
            )

        def _propose_consults(title: str, handoff: str) -> list[tuple[str, str]]:
            from src.agent.team_task_consult_propose import propose_consult_targets
            from src.agent.team_task_roster import assignable_staff, roster_with_role_hints

            # v14: each roster entry carries a short role hint (SOUL.md first line, RO)
            # so the propose call picks a colleague by expertise, not by domain word.
            roster = roster_with_role_hints(
                [(a, d) for a, d in assignable_staff() if a != self_id]
            )
            return propose_consult_targets(
                title, handoff, roster, settings=settings, persona=context.persona,
                project=context.project, memory=context.memory,
            )

        ask_colleague_hook = _ask_colleague
        propose_consults_hook = _propose_consults
        set_attempt_id_hook = _set_attempt_id

    return TeamTaskDeps(
        read_handoff=_read_handoff, run_work=_run_work, run_self_check=_run_self_check,
        run_rework=_run_rework, deliver_step=_deliver, search_hook=search_hook,
        ask_colleague=ask_colleague_hook, propose_consults=propose_consults_hook,
        set_attempt_id=set_attempt_id_hook,
    )


def _read_deps_handoff(data_dir: Any, task_id: str, step_deps: tuple[str, ...]) -> str:
    """DEPS-aware handoff read: the artifact(s) of THIS step's `deps` (step_ids),
    mapped to their store `seq` via `TeamTaskStore.get_step` — NOT "seq - 1" (the
    prior implementation's shortcut).

    "seq - 1" breaks two ways a real DAG hits in practice: (1) an inserted row between
    this step and its actual producer (e.g. a later phase's auto-appended review/rework
    step takes the next AUTOINCREMENT seq, so "seq - 1" no longer points at the real
    upstream step), and (2) a parallel branch, where "seq - 1" may belong to a SIBLING
    step still running concurrently, not a dependency at all — reading its artifact
    would silently hand this step either "" (not written yet) or another branch's
    unrelated output as if it were real handoff context.

    No deps ⇒ "" (first step / a step with nothing to read). Multiple deps ⇒ each
    dep's result_text, concatenated with a blank-line separator (in `deps` order) so a
    fan-in step sees every upstream producer's output, not just one.
    """
    if not step_deps:
        return ""
    from src.agent.team_task_artifact import read_step_artifact
    from src.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(_team_task_db_path(data_dir))
    try:
        parts: list[str] = []
        for dep_step_id in step_deps:
            dep_step = store.get_step(task_id, dep_step_id)
            if dep_step is None:
                continue
            artifact = read_step_artifact(data_dir, task_id, dep_step.seq)
            if artifact is None:
                continue
            text = str(artifact.get("result_text", ""))
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    finally:
        store.close()


def _team_task_db_path(data_dir: Any) -> Any:
    """`data_dir/team_tasks.sqlite3` — same convention `team_task_paths.team_tasks_db_path`
    uses, but parametrized on the CALLER's `data_dir` (tests pass a `tmp_path`, not the
    real repo-root `DATA_DIR`) rather than reading the global settings path directly."""
    from pathlib import Path

    return Path(data_dir) / "team_tasks.sqlite3"


def _room_message(step_title: str, result_text: str) -> str:
    """A short human-readable line for the group-chat room — the first ~200 chars of
    the result, not the full text (the room is a summary feed, not a report viewer)."""
    snippet = result_text.strip().replace("\n", " ")
    if len(snippet) > 200:
        snippet = snippet[:197] + "..."
    return f"[{step_title}] {snippet}" if snippet else f"[{step_title}] (không có nội dung)"


def _make_team_task_nodes(deps: TeamTaskDeps):
    def perceive(state: TeamStepState) -> dict:
        handoff = deps.read_handoff()
        return {"handoff_context": handoff}

    def work(state: TeamStepState) -> dict:
        writer = get_stream_writer()
        writer({"phase": PHASE_WORK})
        title = state.get("step_title", "")
        handoff = state.get("handoff_context", "")
        recover_hint = state.get("recover_hint", "")

        consult_count = state.get("consult_count", 0)
        consult_log = list(state.get("consult_log", ()))
        consult_context = state.get("consult_context", "")
        consult_cost = 0.0
        # Pre-work consult (M33): a bounded, OPTIONAL heuristic hook — never a full
        # tool-calling loop (KISS v1, see module docstring). Off entirely unless both
        # `ask_colleague` and `propose_consults` are wired (`self_id` was passed to
        # `default_team_task_deps`, or a test injects both directly). Skipped on a
        # recovery retry (`recover_count` > 0, hint or no hint): the recover node
        # already made the ONE targeted consult attempt that matters for the retry —
        # re-proposing here would just burn budget on a question the failure already
        # answered (or that recover already found unanswerable).
        if deps.ask_colleague is not None and deps.propose_consults is not None \
                and not state.get("recover_count", 0):
            if deps.set_attempt_id is not None:
                deps.set_attempt_id(state.get("attempt_id", ""))
            remaining = MAX_CONSULTS - consult_count
            if remaining > 0:
                try:
                    proposals = deps.propose_consults(title, handoff)
                except Exception as exc:  # noqa: BLE001 — consult is advisory, never fatal
                    logger.warning("team-step propose_consults failed, skipping: %s", exc)
                    proposals = []
                for agent_id, question in proposals[:remaining]:
                    try:
                        answer, cost = deps.ask_colleague(agent_id, question)
                    except Exception as exc:  # noqa: BLE001 — same advisory contract
                        logger.warning(
                            "team-step ask_colleague(%r) failed, skipping: %s", agent_id, exc,
                        )
                        continue
                    consult_count += 1
                    consult_cost += cost or 0.0
                    if answer:
                        consult_log.append(f"Hỏi {agent_id}: {question} -> {answer}")
                        block = f"[Tham vấn {agent_id}] {answer}"
                        consult_context = f"{consult_context}\n\n{block}" \
                            if consult_context else block

        # Fold the STATE-persisted consult context (this pass's answers AND a prior
        # failed pass's — paid-for advice must survive the recovery retry, review
        # finding M1) + the recover hint into what run_work sees.
        if consult_context:
            handoff = f"{handoff}\n\n{consult_context}" if handoff else consult_context
        if recover_hint:
            handoff = f"{handoff}\n\n{recover_hint}" if handoff else recover_hint

        # cost_usd accumulates ACROSS recovery passes (prior pass's consult spend must
        # not vanish when the retry overwrites the slice) — first pass has no prior,
        # so pre-v14 runs are byte-identical.
        prior_cost = state.get("cost_usd")
        try:
            result_text, cost = deps.run_work(title, handoff, deps.search_hook)
        except Exception as exc:  # noqa: BLE001 — v14 blocked-step tự cứu: ONE bounded
            # in-graph recovery pass before the failure propagates exactly as before.
            if state.get("recover_count", 0) >= MAX_RECOVER:
                raise
            logger.warning("team-step work failed, routing to recover: %s", exc)
            spent = (prior_cost or 0.0) + consult_cost
            return {
                # single-line + truncated: an exception string can embed newlines /
                # provider echo — it rides into the recover consult's brief, so it is
                # squashed to one short line first (review finding m1).
                "work_error": " ".join(str(exc).split())[:_WORK_ERROR_CHARS]
                or "lỗi không rõ",
                "cost_usd": spent if spent else None,
                "consult_count": consult_count, "consult_log": consult_log,
                "consult_context": consult_context,
            }
        total = (prior_cost or 0.0) + (cost or 0.0) + consult_cost
        return {
            "result_text": result_text, "cost_usd": total if total else None,
            "consult_count": consult_count, "consult_log": consult_log,
            "consult_context": consult_context,
            "work_error": "",
        }

    def self_check(state: TeamStepState) -> dict:
        writer = get_stream_writer()
        writer({"phase": PHASE_SELF_CHECK})
        result_text = state.get("result_text", "")
        acceptance = state.get("acceptance", "")
        passed, failures, confidence = deps.run_self_check(result_text, acceptance)
        reasons = list(state.get("check_reasons", ()))
        if failures:
            reasons.extend(failures)
        max_rework = state.get("max_rework", MAX_REWORK)
        rework_count = state.get("rework_count", 0)
        # Exhausted iff this check FAILED and the rework budget is already spent —
        # `route_after_check` (a conditional edge, which cannot itself write state)
        # reads this same pair of facts to pick "deliver" vs "rework"; setting the
        # flag HERE (not in a separate node) keeps the two decisions computed from
        # the identical snapshot, so they can never disagree.
        exhausted = (not passed) and rework_count >= max_rework
        return {
            "self_check_passed": passed, "check_failures": failures,
            "check_confidence": confidence, "check_reasons": reasons,
            "self_check_failed": exhausted,
        }

    def rework(state: TeamStepState) -> dict:
        writer = get_stream_writer()
        writer({"phase": PHASE_REWORK})
        new_count = state.get("rework_count", 0) + 1
        title = state.get("step_title", "")
        prior_output = state.get("result_text", "")
        failures = state.get("check_failures", [])
        result_text, cost = deps.run_rework(title, prior_output, failures)
        prior_cost = state.get("cost_usd")
        total_cost = (prior_cost or 0.0) + (cost or 0.0) if (prior_cost or cost) else None
        return {"result_text": result_text, "cost_usd": total_cost, "rework_count": new_count}

    def recover(state: TeamStepState) -> dict:
        """v14 blocked-step tự cứu: ONE best-effort colleague consult about the exact
        blocker, then route back to `work` for the bounded retry. Consult off/failed/
        no-target ⇒ a plain retry (still valid: transient LLM/API errors are the
        common case). NEVER raises — the retry's own failure is what terminates."""
        writer = get_stream_writer()
        writer({"phase": PHASE_RECOVER})
        title = state.get("step_title", "")
        error = state.get("work_error", "")
        consult_count = state.get("consult_count", 0)
        consult_log = list(state.get("consult_log", ()))
        prior_cost = state.get("cost_usd")
        consult_cost = 0.0
        hint = ""
        if deps.ask_colleague is not None and deps.propose_consults is not None \
                and consult_count < MAX_CONSULTS:
            if deps.set_attempt_id is not None:
                deps.set_attempt_id(state.get("attempt_id", ""))
            # Reuse the SAME propose seam pre-work consult uses, with the blocker folded
            # into the brief — one call, first target only (a recovery is one focused
            # question, not a survey). `error` is an exception string (system-origin,
            # truncated) — the propose prompt already treats briefs as data, not orders.
            stuck_brief = f"{title} — ĐANG BỊ KẸT, lỗi hệ thống: {error}"
            try:
                proposals = deps.propose_consults(stuck_brief, state.get("handoff_context", ""))
            except Exception as exc:  # noqa: BLE001 — consult is advisory, never fatal
                logger.warning("team-step recover propose_consults failed, skipping: %s", exc)
                proposals = []
            for agent_id, question in proposals[:1]:
                try:
                    answer, cost = deps.ask_colleague(agent_id, question)
                except Exception as exc:  # noqa: BLE001 — same advisory contract
                    logger.warning(
                        "team-step recover ask_colleague(%r) failed, skipping: %s",
                        agent_id, exc,
                    )
                    continue
                consult_count += 1
                consult_cost += cost or 0.0
                if answer:
                    consult_log.append(f"Gỡ kẹt, hỏi {agent_id}: {question} -> {answer}")
                    hint = f"[Gợi ý gỡ kẹt từ {agent_id}] {answer}"
        spent = (prior_cost or 0.0) + consult_cost
        return {
            "recover_count": state.get("recover_count", 0) + 1,
            "recover_hint": hint, "work_error": "",
            "consult_count": consult_count, "consult_log": consult_log,
            "cost_usd": spent if spent else None,
        }

    def deliver(state: TeamStepState) -> dict:
        result_text = state.get("result_text", "")
        version = state.get("version") or state.get("attempt_id", "")
        self_check_failed = bool(state.get("self_check_failed", False))
        if deps.external_write is not None:
            proceed = deps.external_write(result_text)
            if not proceed:
                return {"status": "awaiting_approval", "delivered": False, "room_message": ""}
        delivered, room_message = deps.deliver_step(result_text, version, self_check_failed)
        return {"status": "done", "delivered": delivered, "room_message": room_message}

    return perceive, work, self_check, rework, recover, deliver


def route_after_work(state: TeamStepState) -> str:
    """Conditional edge out of `work` (v14): a handled work failure (`work_error` set,
    recovery budget still open — `work` itself re-raises once the budget is spent, so
    this route never sees an over-budget failure) -> `recover`; the normal success
    path -> `self_check`, exactly the edge that was unconditional before v14."""
    if state.get("work_error"):
        return "recover"
    return "self_check"


def route_after_check(state: TeamStepState) -> str:
    """Conditional edge out of `self_check`: `passed` -> deliver; otherwise rework
    while budget remains; budget exhausted -> deliver anyway (flagged), never loop
    forever (R5). Reads ONLY `self_check_passed` + the rework counter — `check_confidence`
    is observability-only, never a routing input (binary pass/fail is the contract)."""
    if state.get("self_check_passed", False):
        return "deliver"
    max_rework = state.get("max_rework", MAX_REWORK)
    if state.get("rework_count", 0) < max_rework:
        return "rework"
    return "deliver"


def build_team_task_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    settings: Settings | None = None,
    context: ProfileContext = EMPTY,
    deps: TeamTaskDeps | None = None,
    step_title: str = "",
    data_dir: Any = None,
    task_id: str = "",
    step_seq: int = 1,
    step_deps: tuple[str, ...] = (),
    search_hook: SearchHook | None = None,
    self_id: str = "",
) -> CompiledStateGraph:
    """Build + compile the team-task step graph. `deps` defaults to real wiring.

    When `deps` is None, `settings`/`data_dir`/`task_id` are required (they wire the
    real handoff-artifact read/write + LLM calls); a caller that injects `deps`
    directly (tests) need not pass them. `self_id` (M33) is this step's OWN assignee —
    forwarded to `default_team_task_deps` to wire `ask_colleague`'s "never consult
    yourself" guard; blank (default) ⇒ consult stays off (see that function's
    docstring). A caller that injects `deps` directly controls `ask_colleague` itself
    and does not need this parameter.

    `checkpointer` is always `None` in production (`team_step_runner._run_graph` never
    passes one) — this graph is deliberately NOT checkpointed (see the module
    docstring's design note): every step attempt is a fresh, self-contained
    `.stream()` call, and retries mint a fresh `attempt_id` rather than resuming a
    saved one. The parameter stays (rather than being removed) only because
    `CompiledStateGraph.compile()` itself accepts it and a future caller with a
    genuine resumability need (none exists today) should not require a signature
    change to add one.
    """
    if deps is None:
        if settings is None or data_dir is None or not task_id:
            raise ValueError(
                "build_team_task_graph needs settings + data_dir + task_id when "
                "deps is not provided."
            )
        deps = default_team_task_deps(
            settings=settings, context=context, step_title=step_title, data_dir=data_dir,
            task_id=task_id, step_seq=step_seq, step_deps=step_deps, search_hook=search_hook,
            self_id=self_id,
        )
    perceive, work, self_check, rework, recover, deliver = _make_team_task_nodes(deps)

    builder = StateGraph(TeamStepState)
    builder.add_node("perceive", perceive)
    builder.add_node("work", work)
    builder.add_node("self_check", self_check)
    builder.add_node("rework", rework)
    builder.add_node("recover", recover)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "work")
    builder.add_conditional_edges(
        "work", route_after_work, {"self_check": "self_check", "recover": "recover"},
    )
    builder.add_conditional_edges(
        "self_check", route_after_check, {"deliver": "deliver", "rework": "rework"},
    )
    builder.add_edge("rework", "self_check")
    builder.add_edge("recover", "work")
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer)
