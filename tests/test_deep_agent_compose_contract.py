"""v42 §9 step-budget: deep_agent binds a compose-early contract to its system prompt.

Research-heavy deep_agent runs can exhaust the bounded recursion loop fetching sources and
never reach the final write_file — ~25% of benchmark runs stalled at "Let me compile the
report" with no report produced. The fix is a prompt contract (0 core code, bounded loop
kept as-is) instructing the agent to write the report to /work EARLY and refine in place.

These tests fake the `deepagents` / `langchain_*` imports so the seam is exercised without
the optional heavy deps — the assertion is on the `system_prompt` handed to
`create_deep_agent`, which must carry the contract appended to the shared team-step system.
"""

from __future__ import annotations

import sys
import types


def _install_fakes(monkeypatch, capture: dict):
    """Fake the lazy imports inside run_deep_agent_work so it runs dep-free.

    Records the `system_prompt` passed to create_deep_agent into `capture`.
    """
    # deepagents.create_deep_agent — records the system_prompt, returns a stub agent.
    fake_deepagents = types.ModuleType("deepagents")

    def _create_deep_agent(model, *, backend, system_prompt):
        capture["system_prompt"] = system_prompt
        return object()  # opaque agent; invoke is faked below

    fake_deepagents.create_deep_agent = _create_deep_agent
    monkeypatch.setitem(sys.modules, "deepagents", fake_deepagents)

    from src.runtime_backends import deep_agent_loop as dal

    # sanitize_bundle → identity passthrough, sanitize_ok True (an explicit `sanitize` callable is
    # passed to run_deep_agent_work by the caller, so the LlmClient default path is never hit).
    class _Bundle:
        persona = project = memory = capability = ""
        handoff = "handoff"

    import src.runtime_backends.deep_agent_sanitizer as san

    monkeypatch.setattr(san, "sanitize_bundle", lambda *_a, **_k: (_Bundle(), True))

    import src.runtime_backends.sandbox_backend as sb

    monkeypatch.setattr(sb, "build_sandbox_backend", lambda *_a, **_k: object())

    import src.runtime_backends.sandbox_teardown as td

    monkeypatch.setattr(td, "teardown_sandbox", lambda *_a, **_k: None)

    import src.runtime_backends.community_loop_core as clc

    monkeypatch.setattr(clc, "invoke_capped", lambda *_a, **_k: {"messages": []})
    monkeypatch.setattr(clc, "record_loop_result", lambda *_a, **_k: ("reply text", 0.0))

    # Read-back is a supplement; short-circuit it.
    monkeypatch.setattr(dal, "_merge_sandbox_artifacts", lambda _backend, text: text)

    # langchain_openai.ChatOpenAI — the constructor must not require real creds.
    fake_lc_openai = types.ModuleType("langchain_openai")
    fake_lc_openai.ChatOpenAI = lambda **_k: object()
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_lc_openai)


class _Ctx:
    persona = project = memory = capability = ""


class _Settings:
    openrouter_model = "x/y"
    openrouter_api_key = "k"


def _run(monkeypatch):
    capture: dict = {}
    _install_fakes(monkeypatch, capture)
    from src.runtime_backends.deep_agent_loop import run_deep_agent_work

    text, _cost = run_deep_agent_work(
        title="Nghiên cứu thị trường X",
        handoff="",
        context=_Ctx(),
        settings=_Settings(),
        sandbox_cfg={"provider": "docker", "network": False},
        loop_limit=16,
        sanitize=lambda s: s,  # explicit → skips the LlmClient default-sanitizer path
    )
    return capture, text


def test_compose_contract_appended_to_system_prompt(monkeypatch):
    from src.runtime_backends.deep_agent_loop import _DEEP_AGENT_COMPOSE_CONTRACT

    capture, _text = _run(monkeypatch)
    assert _DEEP_AGENT_COMPOSE_CONTRACT in capture["system_prompt"]
    # It must be an APPEND (the shared team-step system stays first, contract trails it).
    assert capture["system_prompt"].endswith(_DEEP_AGENT_COMPOSE_CONTRACT)


def test_contract_mentions_write_early_and_bounded_loop():
    from src.runtime_backends.deep_agent_loop import _DEEP_AGENT_COMPOSE_CONTRACT

    c = _DEEP_AGENT_COMPOSE_CONTRACT
    assert "write_file" in c  # names the actual tool
    assert "/work" in c  # the sandbox artifact dir the read-back scans
    # It is guidance, not a loop-cap change — no recursion number leaks into the prompt.
    assert "32" not in c and "recursion" not in c.lower()


def test_run_returns_reply(monkeypatch):
    _capture, text = _run(monkeypatch)
    assert text == "reply text"
