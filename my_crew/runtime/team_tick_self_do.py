"""The real `self_do_step` seam — one content call in which the coordinator writes a
step's result in a worker's place.

Same shape as `make_judge_stuck_step`: a factory closing over the coordinator's
profile and `settings`, its own `LlmClient`, and a never-raises posture — the caller
(`coordinator_nodes.self_resolve._self_do_step`) treats an exception or `None` as
"not attempted" and moves down its ladder. The prompt is the worker's own step prompt
(`build_team_step_messages`) so the fallback result has the same shape a worker's
would; the persona is the coordinator's, since it is the coordinator speaking.

No API key ⇒ the factory itself returns `None`, and the coordinator then never
attempts to do work — the ladder skips straight to skip-with-gap or a conclusion.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _memory_text(loaded: Any) -> str:
    try:
        from my_crew.memory.provider import resolve_memory_text

        return resolve_memory_text(loaded) or ""
    except Exception:  # noqa: BLE001 — memory is context, not a precondition
        return ""


def _capability_text(loaded: Any) -> str:
    try:
        from my_crew.profile.capability_block import build_capability_block

        return build_capability_block(loaded, None) or ""
    except Exception:  # noqa: BLE001
        return ""


def make_self_do_step(loaded: Any, settings: Any):
    """Build the `CoordinatorDeps.self_do_step` callable, or `None` without an API
    key (no model ⇒ the coordinator has nothing to write with)."""
    if not getattr(settings, "openrouter_api_key", None):
        return None

    def _self_do(task: Any, step: Any, handoff: str) -> tuple[str, float | None] | None:
        from my_crew.llm.client import LlmClient
        from my_crew.llm.team_task_prompt import build_team_step_messages

        messages = build_team_step_messages(
            step_title=getattr(step, "title", "") or "",
            handoff_context=handoff,
            persona=getattr(loaded, "soul", "") or "",
            project=getattr(loaded, "project", "") or "",
            memory=_memory_text(loaded) if loaded is not None else "",
            capability=_capability_text(loaded) if loaded is not None else "",
        )
        result = LlmClient(settings).complete(messages, role="content")
        content = (result.content or "").strip()
        if not content:
            logger.warning(
                "team-tick: coordinator self-do returned empty content for step %s",
                getattr(step, "step_id", ""),
            )
            return None
        return content, result.cost_usd

    return _self_do
