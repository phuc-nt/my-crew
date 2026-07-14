"""v43 Phase 1: deep_team wires a curated, moat-safe general-purpose subagent spec.

When `deep_team=True`, run_deep_agent_work passes exactly one DECLARATIVE `SubAgent` spec (no
`runnable`/`backend`/`url` — those are the CompiledSubAgent/AsyncSubAgent forms that could carry a
non-sandbox backend and break the moat). When False (default), no `subagents`/`middleware` kwargs
are passed → byte-identical to pre-v43.
"""

from __future__ import annotations

import sys
import types


def _install_fakes(monkeypatch, capture: dict):
    """Fake the lazy imports inside run_deep_agent_work so it runs dep-free; capture the kwargs
    passed to create_deep_agent (subagents/middleware) + the bound system prompt."""
    fake_deepagents = types.ModuleType("deepagents")

    def _create_deep_agent(model, *, backend, system_prompt, **kwargs):
        capture["system_prompt"] = system_prompt
        capture["kwargs"] = kwargs
        return object()

    fake_deepagents.create_deep_agent = _create_deep_agent
    monkeypatch.setitem(sys.modules, "deepagents", fake_deepagents)

    from src.runtime_backends import deep_agent_loop as dal

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
    monkeypatch.setattr(clc, "record_loop_result", lambda *_a, **_k: ("reply", 0.0))
    monkeypatch.setattr(dal, "_merge_sandbox_artifacts", lambda _b, text: text)

    fake_lc_openai = types.ModuleType("langchain_openai")
    fake_lc_openai.ChatOpenAI = lambda **_k: object()
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_lc_openai)


class _Ctx:
    persona = project = memory = capability = ""


class _Settings:
    openrouter_model = "x/y"
    openrouter_api_key = "k"


def _run(monkeypatch, *, deep_team):
    capture: dict = {}
    _install_fakes(monkeypatch, capture)
    from src.runtime_backends.deep_agent_loop import run_deep_agent_work

    run_deep_agent_work(
        title="t", handoff="", context=_Ctx(), settings=_Settings(),
        sandbox_cfg={"provider": "docker", "network": False}, loop_limit=16,
        sanitize=lambda s: s, deep_team=deep_team,
    )
    return capture


def test_deep_team_false_passes_no_subagents(monkeypatch):
    cap = _run(monkeypatch, deep_team=False)
    assert "subagents" not in cap["kwargs"]
    assert "middleware" not in cap["kwargs"]


def test_deep_team_true_passes_one_declarative_general_purpose_spec(monkeypatch):
    cap = _run(monkeypatch, deep_team=True)
    subs = cap["kwargs"]["subagents"]
    assert isinstance(subs, list) and len(subs) == 1
    spec = subs[0]
    assert spec["name"] == "general-purpose"
    assert spec["description"] and spec["system_prompt"]
    # compose-early discipline replicated one level down (subagent writes /work early)
    assert "/work" in spec["system_prompt"]


def test_deep_team_subagent_spec_is_moat_safe(monkeypatch):
    """The spec must be declarative only — NO key that could carry a non-sandbox backend."""
    cap = _run(monkeypatch, deep_team=True)
    spec = cap["kwargs"]["subagents"][0]
    for forbidden in ("runnable", "backend", "url", "graph_id"):
        assert forbidden not in spec


def test_deep_team_true_attaches_task_cap_middleware(monkeypatch):
    from src.runtime_backends.deep_team_task_cap import TaskCapMiddleware

    cap = _run(monkeypatch, deep_team=True)
    mws = cap["kwargs"]["middleware"]
    assert len(mws) == 1 and isinstance(mws[0], TaskCapMiddleware)


def test_deep_team_true_appends_delegation_clause_to_prompt(monkeypatch):
    from src.runtime_backends.deep_agent_loop import _DEEP_TEAM_DELEGATION_CLAUSE

    cap = _run(monkeypatch, deep_team=True)
    assert _DEEP_TEAM_DELEGATION_CLAUSE in cap["system_prompt"]


def test_deep_team_false_omits_delegation_clause(monkeypatch):
    from src.runtime_backends.deep_agent_loop import _DEEP_TEAM_DELEGATION_CLAUSE

    cap = _run(monkeypatch, deep_team=False)
    assert _DEEP_TEAM_DELEGATION_CLAUSE not in cap["system_prompt"]
