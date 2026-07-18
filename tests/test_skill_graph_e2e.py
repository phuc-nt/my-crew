"""M3-P10 Slice 3: entry-point wiring + end-to-end skill injection (offline).

Proves the candidate-pool → selector → compose chain is wired through the REAL deps
of all 3 report kinds, without a network/LLM: a recording fake `LlmClient` captures
the messages each `_compose`/`_narrate` builds, and we assert the chosen skill body
reaches the INTERNAL prompt but NEVER the external one (the P5 red line). Also proves
`build_skill_context` is allocation-free (no `LlmClient`) for a no-skills profile.
"""

from __future__ import annotations

import pytest

from my_crew.agent.okr_analyzer import OkrRollup
from my_crew.agent.okr_report_graph import default_okr_deps
from my_crew.agent.report_graph import default_report_deps
from my_crew.agent.resource_report_graph import default_resource_deps
from my_crew.llm.client import LlmResult
from my_crew.profile.context import ProfileContext
from my_crew.skills.models import Skill
from my_crew.skills.skill_pool import build_skill_context, load_skill_pool
from my_crew.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

_FLAG = Skill("flag-risk", "phát hiện rủi ro", "BODY-FLAG-RISK-MARKER", ("daily",))
_POOL = (_FLAG,)
_PICK_FLAG = lambda skills, kind: ["flag-risk"]  # noqa: E731 — tiny fake selector

_RISKS = [Risk("blocker", "high", "SCRUM-1", "kẹt", "gỡ", ("SCRUM-1",))]
_OKR = OkrRollup(
    objectives=(Objective("Obj", (KeyResult("KR", ("E-1",), None, 40.0),), 40.0),),
    problems=(),
    at_risk=(),
)
_RES = ResourceReport((AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0)
_COST = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 6, 0.0)


class _RecordingLlm:
    """Captures the messages it is asked to complete; returns a canned narrative."""

    def __init__(self, *_a, **_k):
        self.captured: list[list[dict[str, str]]] = []

    def complete(self, messages):
        self.captured.append(messages)
        return LlmResult("<p>canned</p>", "fake", 0, 0, 0.0)


class _Config:
    slack_external_channels = frozenset()


def _gateway(settings, tmp_path):
    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.audit.audit_log import AuditLog

    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


def _patch_llm(monkeypatch):
    """Patch every site that constructs an LlmClient with the recording fake."""
    rec = _RecordingLlm()
    factory = lambda *_a, **_k: rec  # noqa: E731
    monkeypatch.setattr("my_crew.llm.client.LlmClient", factory)
    monkeypatch.setattr("my_crew.agent.report_graph.LlmClient", factory)
    return rec


def _ctx(audience_skills=True):
    if not audience_skills:
        return ProfileContext()
    return ProfileContext(skills=_POOL, skill_selector=_PICK_FLAG)


def _blob(messages):
    return "".join(m["content"] for m in messages)


# --- load_skill_pool ---


def test_load_skill_pool_filters():
    pool = load_skill_pool(("flag-risk",))
    assert len(pool) == 1 and pool[0].name == "flag-risk"


def test_load_skill_pool_empty():
    assert load_skill_pool(()) == ()


def test_load_skill_pool_drops_unknown():
    # An unknown name is warned + dropped; a valid sibling still loads.
    pool = load_skill_pool(("flag-risk", "no-such-skill"))
    assert [s.name for s in pool] == ["flag-risk"]


# --- report graph: internal injects, external does not ---


def test_report_internal_injects_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(), audience="internal",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


def test_report_external_no_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert not any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


# --- OKR graph ---


def test_okr_internal_injects_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_okr_deps(
        config=_Config(), settings=s, context=_ctx(), gateway=_gateway(s, tmp_path)
    )
    deps.compose(_OKR)
    assert any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


def test_okr_external_no_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_okr_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_OKR)
    assert not any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


# --- resource graph ---


def test_resource_internal_injects_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_resource_deps(
        config=_Config(), settings=s, context=_ctx(), gateway=_gateway(s, tmp_path)
    )
    deps.compose(_RES, _COST)
    assert any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


def test_resource_external_no_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_resource_deps(
        config=_Config(), settings=s, context=_ctx(), audience="external",
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RES, _COST)
    assert not any("BODY-FLAG-RISK-MARKER" in _blob(m) for m in rec.captured)


# --- empty pool == today (no skill body anywhere) ---


def test_empty_pool_no_skill_body(monkeypatch, settings_factory, tmp_path):
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    deps = default_report_deps(
        config=_Config(), settings=s, context=_ctx(audience_skills=False),
        audience="internal", gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    assert not any("pm_skills" in _blob(m) for m in rec.captured)


# --- build_skill_context: no-skills profile builds no LlmClient (no key needed) ---


class _NoKeySettings:
    openrouter_api_key = ""  # a missing key MUST NOT matter for a no-skills profile


class _Loaded:
    def __init__(self, skills):
        self.skills = skills


def test_build_skill_context_no_skills_returns_none():
    skills, selector = build_skill_context(_Loaded(()), _NoKeySettings())
    assert skills == () and selector is None  # no LlmClient constructed, no key needed


def test_build_skill_context_with_skills_builds_selector(monkeypatch, settings_factory):
    _patch_llm(monkeypatch)  # so the real LlmClient ctor (which needs a key) isn't hit
    skills, selector = build_skill_context(_Loaded(("flag-risk",)), settings_factory())
    assert [s.name for s in skills] == ["flag-risk"]
    assert selector is not None


@pytest.mark.parametrize("audience", ["internal", "external"])
def test_build_skill_context_drives_red_line_end_to_end(
    monkeypatch, settings_factory, tmp_path, audience
):
    # The full wiring: build_skill_context loads the REAL bundled flag-risk body, paired
    # with a deterministic selector → ProfileContext → deps.compose. Internal injects the
    # real bundled body; external injects nothing.
    rec = _patch_llm(monkeypatch)
    s = settings_factory(dry_run=True)
    skills, _selector = build_skill_context(_Loaded(("flag-risk",)), s)
    ctx = ProfileContext(skills=skills, skill_selector=_PICK_FLAG)
    deps = default_report_deps(
        config=_Config(), settings=s, context=ctx, audience=audience,
        gateway=_gateway(s, tmp_path),
    )
    deps.compose(_RISKS)
    injected = any("pm_skills" in _blob(m) for m in rec.captured)
    assert injected == (audience == "internal")
