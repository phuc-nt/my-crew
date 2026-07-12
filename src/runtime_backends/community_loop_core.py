"""Shared post-invoke tail for the two langchain-family work loops.

Both `react_loop.run_react_work` (tools tier) and `deep_agent_loop.run_deep_agent_work`
(shell tier) end the same way: pull the final text off the result messages, sum token usage,
price it, and record telemetry. That tail lives here ONCE.

Deliberately NOT here: agent construction, system-prompt binding, and `invoke` — each tier
owns those. The tools tier passes its system prompt ONLY as a SystemMessage; the shell tier
binds `system_prompt=` on `create_deep_agent` (and also sends a SystemMessage). Folding that
into a shared builder would silently change what one of the tiers tells its model, so this
helper only accepts the already-invoked `result`.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

#: Env vars LangChain/LangSmith read to decide whether to attach a cloud tracer. We blank these
#: for the duration of a community-loop invoke so no worker-process turn (persona, tool outputs,
#: internal reads) egresses to LangSmith outside the Action Gateway — regardless of ambient env.
_TRACING_ENV_KEYS = (
    "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY",
)


@contextlib.contextmanager
def _tracing_off():
    """Temporarily force LangSmith tracing off, restoring the prior env on exit.

    An explicit `callbacks=[]` on the invoke is NOT enough: LangChain's CallbackManager still
    injects a LangChainTracer from the env when tracing is enabled. Blanking the env for the
    invoke is what actually suppresses the tracer (verified: 0 handlers configured).

    Assumes one loop invoke per process at a time: it mutates `os.environ` and restores it, so two
    overlapping invokes in the SAME process would clobber each other's restore. Team steps run as
    separate worker subprocesses today, so that does not happen; a future in-process fan-out over
    multiple loops would need per-invoke isolation instead.
    """
    saved = {k: os.environ.get(k) for k in _TRACING_ENV_KEYS}
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGSMITH_API_KEY", None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def invoke_capped(agent: Any, messages: list, *, recursion_limit: int) -> dict:
    """Invoke a langchain-family agent with a hard recursion cap, degrading on overflow.

    A loop that exhausts its cap raises `GraphRecursionError`; left uncaught it propagates to the
    team-step runner and marks the whole step FAILED, discarding any work done. Instead we catch
    it and return an empty result so the step's self_check/deliver still run. The invoke runs with
    LangSmith tracing forced off (see `_tracing_off`) so no turn egresses outside the gateway.
    """
    from langchain_core.messages import AIMessage
    from langgraph.errors import GraphRecursionError

    config = {"recursion_limit": recursion_limit}
    try:
        with _tracing_off():
            return agent.invoke({"messages": messages}, config=config)
    except GraphRecursionError:
        logger.warning(
            "community loop hit recursion_limit=%d; degrading to an empty result so the step "
            "runs self_check/deliver instead of failing outright", recursion_limit,
        )
        # No usable output — return an empty assistant turn (not the echoed prompt) so
        # record_loop_result yields text="" and the step delivers nothing rather than FAILED.
        return {"messages": [*messages, AIMessage(content="")]}


def record_loop_result(
    result: dict, *, model_name: str, telemetry: Any = None
) -> tuple[str, float | None]:
    """Turn a loop's invoke result into the `(text, cost_usd)` run_work tuple.

    Cost is estimated from summed `usage_metadata` tokens × the per-model price table
    (the LangChain OpenRouter path surfaces no provider cost). Missing usage/price → None,
    never fabricated; the monthly budget tracker remains the hard backstop. `telemetry`
    (optional StepTelemetry) receives the token counts + cost provenance; absent = no-op.
    """
    from src.llm.model_pricing import estimate_cost
    from src.runtime.step_telemetry import sum_usage_metadata

    messages = result["messages"]
    final = messages[-1]
    text = getattr(final, "content", "") or ""
    in_tok, out_tok = sum_usage_metadata(messages)
    cost = estimate_cost(model_name, in_tok, out_tok)
    if telemetry is not None:
        telemetry.record(input_tokens=in_tok, output_tokens=out_tok, cost_source="estimated")
    return str(text), cost
