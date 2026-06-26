"""M3-P9 A3 Slice 3: entry-point wiring + end-to-end sibling injection (offline).

Proves the sibling read → selector → compose chain is wired through the REAL deps of
all 3 report kinds, without a network/LLM: a recording fake `LlmClient` captures the
messages each `_compose`/`_narrate` builds, and we assert a sibling's fact reaches the
INTERNAL prompt but NEVER the external one (the P5 red line). Also proves
`build_sibling_context` is allocation-free (no `LlmClient`) for a no-project profile.
"""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from src.agent.memory_node import _NAMESPACE_KIND
from src.agent.okr_analyzer import OkrRollup
from src.agent.okr_report_graph import default_okr_deps
from src.agent.report_graph import default_report_deps
from src.agent.resource_report_graph import default_resource_deps
from src.agent.sibling_memory import build_sibling_context
from src.llm.client import LlmResult
from src.profile.context import ProfileContext
from src.runtime.registry import RegistryEntry
from src.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

MARKER = "SIBLING-FACT-MARKER"
_KEEP_MARKER = lambda facts, kind: [f for f in facts if MARKER in f]  # noqa: E731

_RISKS = [Risk("blocker", "high", "SCRUM-1", "kẹt", "gỡ", ("SCRUM-1",))]
_OKR = OkrRollup(
    objectives=(Objective("Obj", (KeyResult("KR", ("E-1",), None, 40.0),), 40.0),),
    problems=(),
    at_risk=(),
)
_RES = ResourceReport((AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0)
_COST = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 6, 0.0)


class _RecordingLlm:
    def __init__(self, *_a, **_k):
        self.captured: list[list[dict[str, str]]] = []

    def complete(self, messages):
        self.captured.append(messages)
        return LlmResult("<p>canned</p>", "fake", 0, 0, 0.0)


class _Config:
    slack_external_channels = frozenset()


def _gateway(settings, tmp_path):
    from src.actions.action_gateway import ActionGateway
    from src.audit.audit_log import AuditLog

    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


def _patch_llm(monkeypatch):
    rec = _RecordingLlm()
    factory = lambda *_a, **_k: rec  # noqa: E731
    monkeypatch.setattr("src.llm.client.LlmClient", factory)
    monkeypatch.setattr("src.agent.report_graph.LlmClient", factory)
    return rec


def _ctx(with_sibling=True):
    if not with_sibling:
        return ProfileContext()
    return ProfileContext(
        sibling_facts=(f"{MARKER}: A đã chốt sprint 5",),
        sibling_selector=_KEEP_MARKER,
        sibling_project="acme",
    )


def _blob(messages):
    return "".join(m["content"] for m in messages)


# --- report graph ---


def test_report_internal_injects_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(), audience="internal",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert any(MARKER in _blob(m) and "project: acme" in _blob(m) for m in rec.captured)


def test_report_external_omits_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert not any(MARKER in _blob(m) or "project: acme" in _blob(m) for m in rec.captured)


# --- OKR graph ---


def test_okr_internal_injects_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_okr_deps(
        config=_Config(), settings=s, context=_ctx(), gateway=_gateway(s, tmp_path)
    )
    deps.compose(_OKR)
    assert any(MARKER in _blob(m) for m in rec.captured)


def test_okr_external_omits_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_okr_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_OKR)
    assert not any(MARKER in _blob(m) for m in rec.captured)


# --- resource graph ---


def test_resource_internal_injects_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_resource_deps(
        config=_Config(), settings=s, context=_ctx(), gateway=_gateway(s, tmp_path)
    )
    deps.compose(_RES, _COST)
    assert any(MARKER in _blob(m) for m in rec.captured)


def test_resource_external_omits_sibling(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_resource_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RES, _COST)
    assert not any(MARKER in _blob(m) for m in rec.captured)


# --- backward-compat: no sibling context ⇒ no marker / label anywhere ---


def test_no_sibling_context_no_marker(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(with_sibling=False),
        audience="internal", gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert not any(MARKER in _blob(m) or "Bộ nhớ agent khác" in _blob(m) for m in rec.captured)


# --- build_sibling_context end-to-end: reads a real sibling's Store facts ---


def _write_profile(profiles, agent_id, yaml_text):
    d = profiles / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(yaml_text, encoding="utf-8")


class _NoKeySettings:
    openrouter_api_key = ""


def test_build_sibling_context_no_project_allocation_free(monkeypatch):
    monkeypatch.setattr("src.llm.client.LlmClient", _boom_llm)

    class _Loaded:
        profile_id = "A"
        project_group = None

    facts, selector = build_sibling_context(_Loaded(), _NoKeySettings(), InMemoryStore(), ())
    assert facts == () and selector is None  # no LlmClient, no key needed


def _boom_llm(*_a, **_k):
    raise AssertionError("LlmClient must NOT be constructed on the no-op path")


def test_build_sibling_context_reads_real_sibling_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("src.llm.client.LlmClient", lambda *_a, **_k: _RecordingLlm())
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "A", "name: A\nproject: acme\n")
    _write_profile(profiles, "B", "name: B\nproject: acme\n")
    store = InMemoryStore()
    store.put(("B", _NAMESPACE_KIND), "k0", {"fact": f"{MARKER}: B fact", "ts": "t"})
    registry = (RegistryEntry("A", True), RegistryEntry("B", True))

    class _Loaded:
        profile_id = "A"
        project_group = "acme"

    facts, selector = build_sibling_context(
        _Loaded(), _settings_with_key(), store, registry,
        profiles_dir=profiles, data_dir=tmp_path / ".d",
    )
    assert facts == (f"{MARKER}: B fact",)  # A read B's stored fact
    assert selector is not None  # real selector paired (S2 wiring)


def _settings_with_key():
    class _S:
        openrouter_api_key = "k"
        openrouter_model = "test/model"

    return _S()
