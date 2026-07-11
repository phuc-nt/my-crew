"""AgentRuntimeConfig — the parsed `agent_runtime:` profile block (v20; caps v20.5).

TOP-LEVEL profile key, deliberately NOT nested under the infra `runtime:` block (checkpointer /
store / postgres_dsn / tracing).

v20.5 adds per-runtime guardrail caps via `caps()`:
  - `runtime_loop_limit` — the tool-calling / deep-agent RECURSION cap (react super-steps). This
    is DISTINCT from `task_decomposition.MAX_STEPS` (the DAG-decomposition ceiling used by the
    cost estimator); the two must never be conflated (red-team F8). Default per kind.
  - `cost_cap_usd` — OBSERVABILITY ONLY in v20.5. The real per-task hard stop is
    `company.team_task_cap_usd`, enforced task-level in the coordinator; a per-runtime value
    cannot lower a shared per-task cap without a per-agent enforcement seam that does not exist
    yet, so we record the intent but do NOT claim enforcement (red-team C4). None ⇒ use company cap.
  - `sandbox` — the deep-agent sandbox config (`{provider: fake|modal|e2b}`), REQUIRED for
    deep_agent (Phase 2/3), rejected on other kinds.
"""

from __future__ import annotations

from dataclasses import dataclass

_KNOWN_KINDS = {"native", "create_agent", "deep_agent"}
# Positive allowlist of sandbox providers (red-team C3). `fake` = test-only (no isolation);
# `docker` = self-hosted local container (no third-party service, no data egress to a provider).
# `local`/`localshell` and any unknown provider are REJECTED — they map to host-shell backends
# that read the CEO's .env/SSH keys.
_ALLOWED_SANDBOX_PROVIDERS = {"fake", "docker"}

# The tool-calling react loop's historical cap (v20). Kept as the create_agent default so an
# `import MAX_LOOP_STEPS` still resolves and behavior is byte-identical when no cap is set.
MAX_LOOP_STEPS = 8


@dataclass(frozen=True)
class RuntimeCaps:
    """Resolved per-runtime guardrail caps (see module docstring)."""

    runtime_loop_limit: int
    cost_cap_usd: float | None  # observability-only in v20.5
    sandbox: dict | None


#: Default caps per kind. Freedom rises native < create_agent < deep_agent, so does the loop
#: budget; deep_agent additionally REQUIRES a sandbox (enforced at parse).
_DEFAULT_CAPS: dict[str, RuntimeCaps] = {
    "native": RuntimeCaps(runtime_loop_limit=0, cost_cap_usd=None, sandbox=None),
    "create_agent": RuntimeCaps(runtime_loop_limit=MAX_LOOP_STEPS, cost_cap_usd=None, sandbox=None),
    "deep_agent": RuntimeCaps(runtime_loop_limit=16, cost_cap_usd=None, sandbox=None),
}


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Which loop backend runs an agent + optional per-runtime caps. Absent ⇒ native."""

    kind: str = "native"
    runtime_loop_limit: int | None = None  # None ⇒ default per kind
    cost_cap_usd: float | None = None  # observability-only (v20.5)
    sandbox: dict | None = None  # deep_agent only

    def caps(self) -> RuntimeCaps:
        """Resolve effective caps: explicit override wins over the per-kind default."""
        base = _DEFAULT_CAPS.get(self.kind, _DEFAULT_CAPS["native"])
        return RuntimeCaps(
            runtime_loop_limit=(
                self.runtime_loop_limit if self.runtime_loop_limit is not None
                else base.runtime_loop_limit
            ),
            cost_cap_usd=self.cost_cap_usd if self.cost_cap_usd is not None else base.cost_cap_usd,
            sandbox=self.sandbox if self.sandbox is not None else base.sandbox,
        )


def parse_agent_runtime_config(raw: object) -> AgentRuntimeConfig:
    """Validate the optional `agent_runtime:` block. Absent/empty ⇒ native.

    Accepts a bare string (`agent_runtime: native`) or a mapping with optional caps. Fail-loud
    (RuntimeError) on shape errors, unknown kind, negative caps, or a `sandbox` on a non-deep
    runtime / an unknown sandbox provider.
    """
    if raw is None or raw == {} or raw == "":
        return AgentRuntimeConfig()
    if isinstance(raw, str):
        kind = raw.strip() or "native"
        return _validated(AgentRuntimeConfig(kind=kind))
    if not isinstance(raw, dict):
        raise RuntimeError("profile agent_runtime: must be a string or a mapping {kind: ...}.")

    kind = str(raw.get("kind") or "native").strip() or "native"
    loop = raw.get("runtime_loop_limit")
    if loop is not None and (not isinstance(loop, int) or isinstance(loop, bool) or loop < 0):
        raise RuntimeError("profile agent_runtime.runtime_loop_limit must be an int >= 0.")
    cost = raw.get("cost_cap_usd")
    _bad_cost = not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0
    if cost is not None and _bad_cost:
        raise RuntimeError("profile agent_runtime.cost_cap_usd must be a number >= 0.")
    sandbox = raw.get("sandbox")
    if sandbox is not None:
        if not isinstance(sandbox, dict):
            raise RuntimeError("profile agent_runtime.sandbox must be a mapping {provider: ...}.")
        provider = str(sandbox.get("provider") or "").strip()
        if provider not in _ALLOWED_SANDBOX_PROVIDERS:
            raise RuntimeError(
                f"profile agent_runtime.sandbox.provider {provider!r} không hợp lệ "
                f"(known: {sorted(_ALLOWED_SANDBOX_PROVIDERS)})."
            )
    return _validated(
        AgentRuntimeConfig(
            kind=kind,
            runtime_loop_limit=loop,
            cost_cap_usd=float(cost) if cost is not None else None,
            sandbox=sandbox,
        )
    )


def _validated(cfg: AgentRuntimeConfig) -> AgentRuntimeConfig:
    """Cross-field validation: known kind + sandbox only on deep_agent."""
    if cfg.kind not in _KNOWN_KINDS:
        raise RuntimeError(
            f"profile agent_runtime: unknown kind {cfg.kind!r} (known: {sorted(_KNOWN_KINDS)})."
        )
    if cfg.sandbox is not None and cfg.kind != "deep_agent":
        raise RuntimeError(
            f"profile agent_runtime.sandbox chỉ dùng cho deep_agent (kind={cfg.kind!r})."
        )
    return cfg
