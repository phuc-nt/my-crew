"""Graph-invoke config builder — the single DRY seam for per-run RunnableConfig.

M3-P12 (B4): all graph invoke/stream sites (worker, cli, server run-manager) build the
same `{"configurable": {"thread_id": ...}}` config. This module centralizes that so an
opt-in LangSmith tracer's `callbacks` list is attached in ONE place.

Default OFF ⇒ `invoke_config` returns exactly the pre-P12 literal (no `callbacks` key),
so a non-tracing run is byte-identical. The tracer is lazy-imported INSIDE `build_callbacks`
so the OFF path never imports langsmith/tracer modules.

B4 is observability-only: it attaches read-only callbacks to graph execution and never
touches the Action Gateway, never proposes or executes a write.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.config.settings import Settings

logger = logging.getLogger(__name__)


def tracing_env_on() -> bool:
    """True when the env is configured for LangSmith — V2 flag truthy OR API key present.

    The single source of truth for the env side of the tracing gate, shared by the
    settings-path (`tracing_enabled`) and the server env-only path (`invoke_config_env`),
    so every invoke seam agrees on the same env signal.
    """
    return _truthy(os.environ.get("LANGCHAIN_TRACING_V2")) or bool(
        os.environ.get("LANGSMITH_API_KEY")
    )


def tracing_enabled(settings: Settings) -> bool:
    """True only when the profile flag is on AND the env is configured.

    Requiring the env (LangSmith api key / tracing env) means a profile flag alone never
    silently "enables" tracing that then can't ship — keeps the OFF default predictable.
    """
    return bool(getattr(settings, "tracing", False)) and tracing_env_on()


def build_callbacks(settings: Settings) -> list[Any] | None:
    """Return the tracer callbacks list when enabled, else None (caller omits the key).

    Lazy-imports the LangChain tracer so the disabled path imports nothing extra.
    Construction is offline (no flush/network); a failure degrades to None (no tracing)
    rather than breaking the run.
    """
    if not tracing_enabled(settings):
        return None
    try:
        from langchain_core.tracers import LangChainTracer

        return [LangChainTracer()]
    except Exception as exc:  # noqa: BLE001 — tracing must never break a run
        logger.warning("tracing enabled but tracer setup failed; running untraced: %s", exc)
        return None


def invoke_config(thread_id: str, settings: Settings) -> dict[str, Any]:
    """Build the per-run RunnableConfig. Byte-identical to the pre-P12 literal when OFF.

    OFF ⇒ `{"configurable": {"thread_id": thread_id}}` (no `callbacks` key).
    ON  ⇒ the same dict plus `"callbacks": [LangChainTracer()]`.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    callbacks = build_callbacks(settings)
    if callbacks is not None:
        config["callbacks"] = callbacks
    return config


def invoke_config_env(thread_id: str) -> dict[str, Any]:
    """Env-only variant for the localhost server, whose per-run Settings is not in scope.

    The server's RunManager is one-per-process and must NOT store a run's Settings (that
    would leak across runs). Tracing for the server is gated purely on the process env
    (`LANGCHAIN_TRACING_V2` / `LANGSMITH_API_KEY`) — the same env LangSmith itself reads —
    so no Settings is needed. OFF ⇒ byte-identical literal; ON ⇒ adds `callbacks`.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if tracing_env_on():
        try:
            from langchain_core.tracers import LangChainTracer

            config["callbacks"] = [LangChainTracer()]
        except Exception as exc:  # noqa: BLE001 — tracing must never break a run
            logger.warning("server tracing enabled but tracer setup failed: %s", exc)
    return config


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in ("1", "true", "yes", "on")
