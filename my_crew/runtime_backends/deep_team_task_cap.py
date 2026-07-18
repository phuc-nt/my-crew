"""v43: a hard cap on how many `task` delegations one deep_team deep_agent run may make.

deepagents ships a built-in `task(description, subagent_type)` tool (SubAgentMiddleware) but NO
built-in cap on how many times it may be called. Left unbounded, a deep_agent could delegate many
subagents — each running its OWN fresh recursion budget — and the combined wall-time can exceed the
sandbox container lease (`SANDBOX_LEASE_S`), getting SIGKILL'd mid-compose and losing the result.

This middleware counts `task` tool calls and refuses past `max_calls` with an error `ToolMessage`
instructing the model to compose the report now from what it has (compose-early + the /work
read-back mean a partial report already exists). The prompt clause advises the same bound, so the
hard refusal is a backstop, not the primary control.

Per-run scope: a fresh `TaskCapMiddleware` instance is constructed inside each `run_deep_agent_work`
call, so the counter is per-run. It is NOT per-thread-safe by construction, though: LangGraph's
`ToolNode` executes all tool calls from one model turn via a ThreadPoolExecutor, so if the model
emits two `task` calls in the same turn, `wrap_tool_call` runs concurrently on separate threads. The
counter's read-modify-write is therefore guarded by a `threading.Lock` (same pattern as
`UsageMetadataCallbackHandler`), so the cap holds even under parallel tool calling.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

#: The tool name deepagents registers for subagent delegation.
_TASK_TOOL_NAME = "task"


def _build_middleware_base():
    """Resolve the AgentMiddleware base class (imported from langchain).

    NOTE: this runs at CLASS-DEFINITION time (`class TaskCapMiddleware(_build_middleware_base())`),
    so importing THIS module does import langchain. langchain is loaded lazily overall only because
    this module's sole import site is inside the `if deep_team:` branch of `run_deep_agent_work` —
    i.e. deferred by IMPORT SITE, not by class construction. Keep it that way (no eager top-level
    import of `deep_team_task_cap`).
    """
    from langchain.agents.middleware.types import AgentMiddleware

    return AgentMiddleware


class TaskCapMiddleware(_build_middleware_base()):  # type: ignore[misc]
    """Refuse `task` tool calls beyond `max_calls` in one run."""

    def __init__(self, *, max_calls: int) -> None:
        super().__init__()
        self._max_calls = int(max_calls)
        self._count = 0
        # ToolNode runs parallel tool calls from one turn on a thread pool, so the counter's
        # check-then-increment must be atomic or the cap can be exceeded under parallel calls.
        self._lock = threading.Lock()

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Count `task` calls; refuse past the cap. Non-`task` tools pass through untouched.

        Signature matches `AgentMiddleware.wrap_tool_call(self, request, handler)`:
        `request.tool_call` is the ToolCall dict (`name`/`args`/`id`); `handler(request)` runs the
        tool and returns a `ToolMessage | Command`. To refuse, we return an error `ToolMessage`
        WITHOUT calling the handler (so the subagent never runs), carrying the model-visible reason.
        """
        from langchain_core.messages import ToolMessage

        tool_call = getattr(request, "tool_call", None) or {}
        name = tool_call.get("name") if isinstance(tool_call, dict) else None
        if name != _TASK_TOOL_NAME:
            return handler(request)  # not a delegation — never counted or blocked

        # Atomically claim one delegation slot: check + increment under the lock so two threads
        # (parallel `task` calls in one turn) cannot both pass the cap check before incrementing.
        with self._lock:
            over_cap = self._count >= self._max_calls
            if not over_cap:
                self._count += 1
        if over_cap:
            logger.info(
                "deep_team: task delegation cap (%d) reached — refusing further delegation",
                self._max_calls,
            )
            return ToolMessage(
                content=(
                    f"Đã đạt giới hạn giao việc cho trợ lý con ({self._max_calls} lần). "
                    "Hãy TỰ tổng hợp và viết báo cáo cuối NGAY BÂY GIỜ từ những gì đã có "
                    "(kể cả các file trong /work), không giao thêm."
                ),
                tool_call_id=tool_call.get("id", "") if isinstance(tool_call, dict) else "",
                status="error",
            )

        return handler(request)
