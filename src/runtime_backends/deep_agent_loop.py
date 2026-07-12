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
    *, title: str, handoff: str, context, settings, sandbox_cfg, loop_limit: int,
    telemetry=None, sanitize=None,
) -> tuple[str, float | None]:
    """Run one team-step's work as a deepagents loop inside a hardened sandbox.

    `telemetry` (optional StepTelemetry) receives summed token counts + cost provenance;
    cost still returns on the tuple. Absent collector = no-op (byte-identical behavior).

    `sanitize` (optional Sanitizer) redacts internal-sensitive tokens from the agent's input
    (context fields + handoff) before it reaches the sandbox prompt; defaults to an LLM sanitizer
    built from `settings`. If sanitization fails, the sandbox is forced network-OFF so
    un-sanitized internal data can never egress — the sanitizer is the trust boundary that makes
    a network-on deep_agent safe.
    """
    from deepagents import create_deep_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from src.config.settings import OPENROUTER_BASE_URL
    from src.llm.team_task_prompt import build_team_step_messages
    from src.runtime_backends.community_loop_core import invoke_capped, record_loop_result
    from src.runtime_backends.deep_agent_sanitizer import make_llm_sanitizer, sanitize_bundle
    from src.runtime_backends.sandbox_backend import build_sandbox_backend
    from src.runtime_backends.sandbox_teardown import teardown_sandbox

    # Sanitize the internal input channels (context fields + handoff) BEFORE deciding on network:
    # the network flag is ANDed with sanitize success, so an opt-in only takes effect on a clean
    # bundle. Persona (SOUL.md) is sanitized too — it can name real people. company_docs withheld.
    if sanitize is None:
        from src.llm.client import LlmClient
        sanitize = make_llm_sanitizer(LlmClient(settings))
    bundle, sanitize_ok = sanitize_bundle(
        sanitize,
        persona=getattr(context, "persona", "") or "",
        project=getattr(context, "project", "") or "",
        memory=getattr(context, "memory", "") or "",
        capability=getattr(context, "capability", "") or "",
        handoff=handoff or "",
    )

    # Network AND-gate: opt-in ONLY takes effect when the input was sanitized. On failure, force
    # network off via an adjusted per-run cfg (reuses Phase 2's cfg.get("network") seam).
    net_opt_in = bool((sandbox_cfg or {}).get("network"))
    effective_network = net_opt_in and sanitize_ok
    run_cfg = {**(sandbox_cfg or {}), "network": effective_network}

    # Fail-closed: raises SandboxDenied on None/local/unknown (red-team C3). The shell has no
    # backend to run on otherwise — deepagents' execute returns an error, but we refuse earlier.
    backend = build_sandbox_backend(run_cfg)

    msgs = build_team_step_messages(
        step_title=title, handoff_context=bundle.handoff,
        persona=bundle.persona, project=bundle.project,
        memory=bundle.memory, capability=bundle.capability,
    )
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    user = next((m["content"] for m in msgs if m["role"] == "user"), title)

    model = ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    try:
        # Shell tier binds the system prompt on the agent AND sends it as a SystemMessage (its
        # built-in tools read the bound prompt); both derive from the sanitized bundle.
        agent = create_deep_agent(model, backend=backend, system_prompt=system)
        result = invoke_capped(
            agent,
            [SystemMessage(content=system), HumanMessage(content=user)],
            recursion_limit=max(2, loop_limit * 2),  # bounded loop
        )
        return record_loop_result(
            result, model_name=settings.openrouter_model, telemetry=telemetry
        )
    finally:
        teardown_sandbox(backend)  # C6: best-effort container teardown on the normal path
