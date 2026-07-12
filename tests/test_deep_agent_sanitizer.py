"""Sanitize a deep_agent's input + fail-closed network gate.

The sanitizer is the trust boundary for a network-capable deep_agent: internal-sensitive tokens
are redacted from BOTH the context fields and the handoff before they can reach the sandbox
prompt, and if the pass fails the sandbox is forced network-off so un-sanitized data never
egresses. These tests use fake sanitizers (no LLM) to lock that contract deterministically.
"""

from __future__ import annotations

import importlib.util

import pytest

from src.runtime_backends.deep_agent_sanitizer import sanitize_bundle

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None


def _identity(text):
    return text, True


def _fail(_text):
    return "", False


def test_sanitize_bundle_all_channels_pass_through_on_ok():
    bundle, ok = sanitize_bundle(
        _identity, persona="P", project="p", memory="m", capability="c", handoff="h"
    )
    assert ok is True
    assert (bundle.project, bundle.memory, bundle.capability, bundle.handoff) == (
        "p", "m", "c", "h",
    )


def test_sanitize_bundle_redacts_marker_in_every_channel():
    def _redact(text):
        return text.replace("SECRET", "[hidden]"), True

    bundle, ok = sanitize_bundle(
        _redact, persona="SECRET-p", project="SECRET-a", memory="SECRET-b", capability="SECRET-c",
        handoff="SECRET-d",
    )
    assert ok is True
    for field in (bundle.project, bundle.memory, bundle.capability, bundle.handoff):
        assert "SECRET" not in field


def test_sanitize_bundle_any_failure_taints_whole_bundle():
    # A sanitizer that fails only on the handoff still makes the whole bundle ok=False.
    def _fail_handoff(text):
        return ("", False) if text == "handoff-text" else (text, True)

    _bundle, ok = sanitize_bundle(
        _fail_handoff, persona="p", project="p", memory="m", capability="c", handoff="handoff-text",
    )
    assert ok is False


def test_sanitize_bundle_empty_fields_skip_and_stay_ok():
    # Empty channels are skipped (no call); ok stays True.
    called = []

    def _track(text):
        called.append(text)
        return text, True

    _bundle, ok = sanitize_bundle(
        _track, persona="", project="", memory="", capability="", handoff=""
    )
    assert ok is True
    assert called == []  # nothing to sanitize → no sanitizer calls


@pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")
def test_run_deep_agent_work_forces_network_off_on_sanitize_failure(monkeypatch):
    # THE C1 GUARANTEE: sanitize failure → the sandbox is built with network OFF even when the
    # agent opted into network. We capture the cfg handed to build_sandbox_backend.
    import src.runtime_backends.deep_agent_loop as loop

    captured = {}

    class _FakeBackend:
        def teardown(self):
            pass

    def _fake_build(cfg):
        captured["cfg"] = cfg
        return _FakeBackend()

    class _FakeAgent:
        def invoke(self, _state, config=None):
            return {"messages": [type("M", (), {"content": "done", "usage_metadata": None})()]}

    monkeypatch.setattr("src.runtime_backends.sandbox_backend.build_sandbox_backend", _fake_build)
    monkeypatch.setattr("deepagents.create_deep_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda *a, **k: object())
    monkeypatch.setattr("src.runtime_backends.sandbox_teardown.teardown_sandbox", lambda b: None)

    class _Settings:
        openrouter_model = "x/y"
        openrouter_api_key = "k"

    class _Ctx:
        persona = "p"
        project = "proj"
        memory = "mem"
        capability = "cap"

    loop.run_deep_agent_work(
        title="t", handoff="h", context=_Ctx(), settings=_Settings(),
        sandbox_cfg={"provider": "fake", "network": True}, loop_limit=4,
        sanitize=_fail,  # sanitize FAILS
    )
    assert captured["cfg"]["network"] is False  # network forced off despite opt-in


@pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")
def test_run_deep_agent_work_keeps_network_on_when_sanitize_ok(monkeypatch):
    # Sanitize success + opt-in → network stays on (the sanitized bundle is safe to egress).
    import src.runtime_backends.deep_agent_loop as loop

    captured = {}

    class _FakeBackend:
        def teardown(self):
            pass

    def _fake_build(cfg):
        captured["cfg"] = cfg
        return _FakeBackend()

    class _FakeAgent:
        def invoke(self, _state, config=None):
            return {"messages": [type("M", (), {"content": "done", "usage_metadata": None})()]}

    monkeypatch.setattr("src.runtime_backends.sandbox_backend.build_sandbox_backend", _fake_build)
    monkeypatch.setattr("deepagents.create_deep_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda *a, **k: object())
    monkeypatch.setattr("src.runtime_backends.sandbox_teardown.teardown_sandbox", lambda b: None)

    class _Settings:
        openrouter_model = "x/y"
        openrouter_api_key = "k"

    class _Ctx:
        persona = "p"
        project = "proj"
        memory = "mem"
        capability = "cap"

    loop.run_deep_agent_work(
        title="t", handoff="h", context=_Ctx(), settings=_Settings(),
        sandbox_cfg={"provider": "fake", "network": True}, loop_limit=4,
        sanitize=_identity,  # sanitize OK
    )
    assert captured["cfg"]["network"] is True


@pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")
def test_deep_agent_recursion_limit_is_double_loop_limit(monkeypatch):
    # The effective recursion_limit handed to the deepagents invoke is loop_limit*2 (LangGraph
    # counts a tool round as ~2 super-steps). Documented in config; asserted here at the invoke.
    import src.runtime_backends.deep_agent_loop as loop

    seen = {}

    class _FakeBackend:
        def teardown(self):
            pass

    class _FakeAgent:
        def invoke(self, _state, config=None):
            seen["recursion_limit"] = (config or {}).get("recursion_limit")
            return {"messages": [type("M", (), {"content": "done", "usage_metadata": None})()]}

    monkeypatch.setattr(
        "src.runtime_backends.sandbox_backend.build_sandbox_backend", lambda cfg: _FakeBackend()
    )
    monkeypatch.setattr("deepagents.create_deep_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda *a, **k: object())
    monkeypatch.setattr("src.runtime_backends.sandbox_teardown.teardown_sandbox", lambda b: None)

    class _Settings:
        openrouter_model = "x/y"
        openrouter_api_key = "k"

    loop.run_deep_agent_work(
        title="t", handoff="h", context=None, settings=_Settings(),
        sandbox_cfg={"provider": "fake"}, loop_limit=8, sanitize=_identity,
    )
    assert seen["recursion_limit"] == 16  # loop_limit(8) * 2
