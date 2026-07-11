"""The deepagents work loop for the deep-agent runtime (v20.5 Phase 3).

Runs `create_deep_agent` whose shell/`execute` is bound to a token-free sandbox backend
(Docker self-hosted, or fake for tests). Returns `(result_text, cost)` matching the
`TeamTaskDeps.run_work` contract, so the surrounding team-step graph (self_check / rework /
deliver → external_write → gateway from Phase 0) is untouched.

Safety wiring (all red-team fixes converge here):
- **Sandbox-only shell** (C2/C3): `backend=` is our fail-closed sandbox; no backend ⇒ SandboxDenied.
- **PII gate** (H2/H3): the context is stripped to external-audience-safe before it reaches the
  agent, so internal memory/company_docs cannot be exfiltrated from the sandbox.
- **Loop cap** (C5): `recursion_limit` is bound to the runtime's `runtime_loop_limit`.
- **Teardown** (C6): the sandbox is torn down on the normal path (best-effort; the container's
  own idle ceiling is the SIGKILL backstop).
- **Built-in tools confined** (H4): deepagents' write_file/execute/subagent tools all operate
  THROUGH the sandbox backend — they touch the container, never the host or the gateway. The
  step's only company egress is the text result → deliver → gateway.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_deep_agent_work(
    *, title: str, handoff: str, context, settings, sandbox_cfg, loop_limit: int
) -> tuple[str, float | None]:
    """Run one team-step's work as a deepagents loop inside a token-free sandbox."""
    from deepagents import create_deep_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from src.config.settings import OPENROUTER_BASE_URL
    from src.llm.team_task_prompt import build_team_step_messages
    from src.runtime_backends.deep_agent_pii_gate import gate_context_for_sandbox
    from src.runtime_backends.sandbox_backend import build_sandbox_backend
    from src.runtime_backends.sandbox_teardown import teardown_sandbox

    # Fail-closed: raises SandboxDenied on None/local/unknown (red-team C3). The shell has no
    # backend to run on otherwise — deepagents' execute returns an error, but we refuse earlier.
    backend = build_sandbox_backend(sandbox_cfg)

    # PII gate: external-audience-safe context (red-team H2) — no internal memory/company_docs
    # can reach the sandbox-with-egress.
    safe_ctx = gate_context_for_sandbox(context) if context is not None else context

    msgs = build_team_step_messages(
        step_title=title, handoff_context=handoff,
        persona=getattr(safe_ctx, "persona", ""), project=getattr(safe_ctx, "project", ""),
        memory="", capability="",  # gated out
    )
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    user = next((m["content"] for m in msgs if m["role"] == "user"), title)

    model = ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    try:
        agent = create_deep_agent(model, backend=backend, system_prompt=system)
        result = agent.invoke(
            {"messages": [SystemMessage(content=system), HumanMessage(content=user)]},
            config={"recursion_limit": max(2, loop_limit * 2)},  # C5: bounded loop
        )
        final = result["messages"][-1]
        text = getattr(final, "content", "") or ""
        return str(text), None  # cost unpriced-but-bounded; monthly budget_tracker is backstop
    finally:
        teardown_sandbox(backend)  # C6: best-effort container teardown on the normal path
