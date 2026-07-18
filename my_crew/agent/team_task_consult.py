"""`ask_colleague`: the M33 consult seam a team-task step's `work` node calls into.

Decision C (red-team 2026-07-10, see `plans/260710-1347-v13-team-self-operation/plan.md`):
consult is a synchronous, read-only "role-play consultation" over a colleague's PUBLIC
persona FILES — `SOUL.md` + `PROJECT.md` (via `my_crew.profile.loader.load_profile`) — NOT
the sibling-memory system (`my_crew.agent.sibling_memory.read_sibling_facts` /
`my_crew.agent.store.get_store`). Two reasons sibling-memory was deliberately dropped, not
merely unused here:

  1. `get_store` defaults to a fresh `InMemoryStore()` per process (`my_crew/agent/store.py`)
     — a team-step worker is a DETACHED subprocess, so any Store read there sees an
     empty store every time on the default backend. Wiring consult through it would be
     dead code dressed as a feature.
  2. `read_sibling_facts` is gated by `project_group` (M3-P9's red line: an agent only
     reads facts from siblings in its OWN project group). A roster-wide "ask any
     colleague" consult has no such scope — routing it through sibling-memory would
     silently WIDEN that red line to the whole fleet, which was never approved.

Reading the two Markdown files directly sidesteps both problems: they are internal-only
BY CONSTRUCTION (never contain external audience content, same guarantee every other
`persona`/`project` injection in this codebase relies on — see `profile.context`), they
always exist (loader returns "" for an absent file, never raises), and touching them
does not "read cross-agent memory" in any sense the red line cares about — it is the
SAME kind of file-read `default_team_task_deps` already does for the ASKING agent's own
persona, just aimed at a colleague's directory instead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.config.settings import Settings

logger = logging.getLogger(__name__)

#: Hard ceiling on consults per step attempt (`team_task_graph.TeamStepState.consult_count`,
#: reset per attempt like `rework_count`) — an advisory feature must stay bounded, not
#: become an unbounded tool-calling loop (KISS v1: one heuristic pre-work hook, not a
#: full agentic loop).
MAX_CONSULTS = 2


#: Room event body fields kept short enough that `office_event_projection`'s truncation
#: never has to bite mid-word for a typical topic line — the projection module still
#: enforces the real ~120-char cut, this is just a friendly pre-trim.
_SUMMARY_CHARS = 120


def _summarize(text: str) -> str:
    """First line / first ~120 chars of `text`, NEVER the raw file/answer content
    beyond that — this is what rides into the room event body (see the module
    docstring: room events are a template summary, not a content mirror)."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    if len(line) > _SUMMARY_CHARS:
        return line[:_SUMMARY_CHARS] + "…"
    return line


def ask_colleague(
    agent_id: str, question: str, *, settings: Settings, self_id: str,
    room_id: str = "", attempt_id: str = "",
) -> tuple[str, float]:
    """Ask `agent_id` (a colleague, never `self_id`) one question; returns `(answer, cost_usd)`.

    Guard (authz, same roster gate `team_task_roster.is_assignable` re-verifies at
    dispatch time): `agent_id` must be in `assignable_staff()` (already excludes the
    coordinator + admin agent) AND must not equal `self_id`. Either guard failing is a
    SKIP, not an error — consult is advisory, never a step-blocking gate. Skip returns
    `("", 0.0)`, identical to the fail-degrade path below, so a caller cannot tell "not
    allowed" from "failed" — both mean "no answer, carry on." No room event is appended
    on a guard-skip (nothing happened worth recording).

    Fail-degrade (profile deleted mid-run, disk error, malformed persona, LLM error,
    anything else): caught here, logged, `("", 0.0)` returned — this function must NEVER
    raise out to the `work` node (mirrors `default_team_task_deps._run_work`'s
    `search_hook` contract, `team_task_graph.py`'s module docstring). A broken consult
    must not burn the step's retry budget or fail delivery.

    RO by construction: only `load_profile` (file read) + one `LlmClient.complete` call
    happen here — no `Store`, no `get_store`, no `sibling_memory` import, no write of any
    kind (see the module docstring for why sibling-memory is deliberately excluded). The
    ONE write this function performs is the room-event append below, and that is a
    template SUMMARY (`_summarize`, ~120 char, first line only) — never the raw SOUL.md/
    PROJECT.md content and never the raw answer text, matching the PII firewall every
    other office-room writer in this codebase honors (`office_event_projection`'s
    write-time allowlist re-enforces the same cap server-side, independent of this
    trim, so a future caller of `append_office_event` that skips this helper still
    cannot leak raw content through the `consult` kind).

    `room_id`/`attempt_id`, when given (the real wiring always passes both — see
    `default_team_task_deps`), append a `consult` room event via
    `office_room_append.append_office_event` (try/degrade — an append failure never
    blocks the answer from reaching the caller). Blank `room_id` (e.g. a bare unit
    test of this function) skips the room append entirely.
    """
    from my_crew.agent.team_task_roster import assignable_staff

    if agent_id == self_id:
        return "", 0.0
    if not any(a == agent_id for a, _ in assignable_staff()):
        return "", 0.0

    answer = ""
    cost = 0.0
    try:
        from my_crew.llm.client import LlmClient
        from my_crew.llm.team_task_prompt import build_consult_messages
        from my_crew.profile.loader import load_profile
        from my_crew.runtime.agent_paths import agent_data_dir

        colleague = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
        llm = LlmClient(settings)
        result = llm.complete(
            build_consult_messages(
                colleague_soul=colleague.soul, colleague_project=colleague.project,
                question=question,
            )
        )
        answer, cost = result.content, (result.cost_usd or 0.0)
    except Exception as exc:  # noqa: BLE001 — consult is advisory, must never fail the step
        logger.warning(
            "consult ask_colleague(%r) failed, degrading to no-answer: %s", agent_id, exc,
        )

    if room_id:
        try:
            from my_crew.runtime.office_room_append import append_office_event

            append_office_event(
                room_id, author=self_id, kind="consult",
                body={
                    "from": self_id, "to": agent_id,
                    "question_summary": _summarize(question),
                    "answer_summary": _summarize(answer),
                    "attempt_id": attempt_id,
                },
                also_office=True,
            )
        except Exception as exc:  # noqa: BLE001 — belt-and-suspenders on top of
            # `append_office_event`'s OWN try/degrade: this function's contract
            # ("must NEVER raise out to the `work` node") must hold even if a future
            # change to that helper (or a test double standing in for it) stops
            # honoring its own degrade promise.
            logger.warning(
                "consult room-event append failed (room=%s), continuing: %s", room_id, exc,
            )
    return answer, cost
