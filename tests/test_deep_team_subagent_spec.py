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

    from my_crew.runtime_backends import deep_agent_loop as dal

    class _Bundle:
        persona = project = memory = capability = ""
        handoff = "handoff"

    import my_crew.runtime_backends.deep_agent_sanitizer as san

    monkeypatch.setattr(san, "sanitize_bundle", lambda *_a, **_k: (_Bundle(), True))

    import my_crew.runtime_backends.sandbox_backend as sb

    monkeypatch.setattr(sb, "build_sandbox_backend", lambda *_a, **_k: object())

    import my_crew.runtime_backends.sandbox_teardown as td

    monkeypatch.setattr(td, "teardown_sandbox", lambda *_a, **_k: None)

    import my_crew.runtime_backends.community_loop_core as clc

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


def _run(monkeypatch, *, deep_team, deep_team_max_calls=None):
    capture: dict = {}
    _install_fakes(monkeypatch, capture)
    from my_crew.runtime_backends.deep_agent_loop import run_deep_agent_work

    run_deep_agent_work(
        title="t", handoff="", context=_Ctx(), settings=_Settings(),
        sandbox_cfg={"provider": "docker", "network": False}, loop_limit=16,
        sanitize=lambda s: s, deep_team=deep_team, deep_team_max_calls=deep_team_max_calls,
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
    from my_crew.runtime_backends.deep_team_task_cap import TaskCapMiddleware

    cap = _run(monkeypatch, deep_team=True)
    mws = cap["kwargs"]["middleware"]
    assert len(mws) == 1 and isinstance(mws[0], TaskCapMiddleware)


def test_deep_team_true_appends_delegation_clause_to_prompt(monkeypatch):
    from my_crew.runtime_backends.deep_agent_loop import _deep_team_delegation_clause

    cap = _run(monkeypatch, deep_team=True)
    # default cap 3 → the clause built at cap 3 must be present
    assert _deep_team_delegation_clause(3) in cap["system_prompt"]


def test_deep_team_false_omits_delegation_clause(monkeypatch):
    from my_crew.runtime_backends.deep_agent_loop import _deep_team_delegation_clause

    cap = _run(monkeypatch, deep_team=False)
    assert _deep_team_delegation_clause(3) not in cap["system_prompt"]


# --- v44: deep_team_max_calls override ---------------------------------------------------

def test_default_cap_is_3_backward_compat(monkeypatch):
    """`deep_team: true` with no override → cap 3 in BOTH middleware and prompt (v43 behavior)."""
    cap = _run(monkeypatch, deep_team=True)  # no override
    assert cap["kwargs"]["middleware"][0]._max_calls == 3
    from my_crew.runtime_backends.deep_agent_loop import _deep_team_delegation_clause

    assert _deep_team_delegation_clause(3) in cap["system_prompt"]


def test_override_syncs_middleware_and_prompt(monkeypatch):
    """deep_team_max_calls=5 → middleware AND the prompt clause both say 5 (never drift)."""
    cap = _run(monkeypatch, deep_team=True, deep_team_max_calls=5)
    assert cap["kwargs"]["middleware"][0]._max_calls == 5
    from my_crew.runtime_backends.deep_agent_loop import _deep_team_delegation_clause

    assert _deep_team_delegation_clause(5) in cap["system_prompt"]
    assert _deep_team_delegation_clause(3) not in cap["system_prompt"]


def test_override_clamped(monkeypatch):
    """A huge/tiny override is clamped so wall-time can't blow the lease."""
    from my_crew.runtime_backends.deep_agent_loop import _MAX_TASK_CALLS_CEILING, _MIN_TASK_CALLS

    hi = _run(monkeypatch, deep_team=True, deep_team_max_calls=99)
    assert hi["kwargs"]["middleware"][0]._max_calls == _MAX_TASK_CALLS_CEILING
    lo = _run(monkeypatch, deep_team=True, deep_team_max_calls=0)
    assert lo["kwargs"]["middleware"][0]._max_calls == _MIN_TASK_CALLS


def test_override_ignored_when_deep_team_off(monkeypatch):
    """deep_team=False → no middleware regardless of the cap field."""
    cap = _run(monkeypatch, deep_team=False, deep_team_max_calls=7)
    assert "middleware" not in cap["kwargs"]
