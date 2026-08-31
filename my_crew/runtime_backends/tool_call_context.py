"""Who is calling a read tool, and from where — the context the policy shim never had.

The shim in `read_only_toolset` runs `hard_block.classify` on every read call, but it
sees only the tool name and its args. A Lớp B audit could therefore not answer "which
agent, on which step, on which round did this fire" — the trail had a verdict and no
subject.

Why a ContextVar rather than a parameter: the tools are bound ONCE, before the loop
starts (`build_read_toolset` → `build_typed_specs`), so there is no per-call seam to
thread an argument through — by the time a callable runs, the builder's arguments are
long out of scope. The round number in particular only exists as a local in
`thin_tool_loop`'s `for` statement. An ambient value the loop updates per round is the
only thing both loops can supply, and `react_loop` hands iteration to LangChain
entirely, so a parameter would be unavailable there at any price.

This is deliberately NOT `step_recorder`'s recorder var, which is the closest existing
carrier. That one is switched off wholesale by `settings.step_transcripts`, and an
audit trail that disappears when someone turns off a debugging aid is not an audit
trail. This var is always live.

Nothing here decides anything. It carries identity for the record; the allow/deny
verdict remains entirely `hard_block.classify`'s.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ToolCallContext:
    """Identity of the run a tool call belongs to. Every field optional: plenty of call
    paths (a CLI report run, a bare toolset in a test) have no step or task at all, and
    those must still be able to call tools."""

    agent_id: str = ""
    task_id: str = ""
    step_id: str = ""
    #: Which round of the work loop. -1 = unknown/not in a counted loop, kept distinct
    #: from 0, which is a real first round.
    iteration: int = -1


#: The empty context — what an unattributed call reports.
NO_CONTEXT = ToolCallContext()

_current: ContextVar[ToolCallContext] = ContextVar("tool_call_context", default=NO_CONTEXT)


def current_tool_call_context() -> ToolCallContext:
    """The context in force, or `NO_CONTEXT` outside any step."""
    return _current.get()


@contextlib.contextmanager
def tool_call_context(
    *, agent_id: str = "", task_id: str = "", step_id: str = "", iteration: int = -1
) -> Iterator[None]:
    """Install identity for the duration of the block."""
    token = _current.set(
        ToolCallContext(
            agent_id=agent_id, task_id=task_id, step_id=step_id, iteration=iteration
        )
    )
    try:
        yield
    finally:
        _current.reset(token)


@contextlib.contextmanager
def tool_call_iteration(iteration: int) -> Iterator[None]:
    """Set just the round number, keeping whatever identity is already in force.

    The loop knows its round but not the step's identity (it is handed a bound toolset,
    not the step); the runner knows the identity but not the round. Each sets the half
    it holds.
    """
    token = _current.set(replace(_current.get(), iteration=iteration))
    try:
        yield
    finally:
        _current.reset(token)
