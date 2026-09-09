"""The tool-calling tiers see the agent's skills + company docs, like the native tier.

Before this, `run_thin_loop` / `run_react_work` / `run_deep_agent_work` reused the native
team-step prompt builder but handed it only persona/project/memory/capability. An agent
whose steps always routed to `create_agent` or `deep_agent` (every template role pinned
to a tool tier) therefore never saw a single skill from its pool, and the skill curator
counted each of those skills as "never used". These tests pin the fix at the three call
sites AND at the shared helper, so a tier that drops the kwargs again fails loudly.
"""

from __future__ import annotations

import json

from my_crew.company_docs.store import CompanyDoc
from my_crew.profile.context import ProfileContext
from my_crew.runtime_backends.team_step_prompt_extras import (
    team_step_prompt_extras,
    team_step_skills_text,
)
from my_crew.skills.models import Skill

_SKILL_BODY = "Luôn nêu rõ giả định trước khi kết luận số liệu."
_DOC_BODY = "Giờ làm việc công ty: 9h–18h, nghỉ trưa 12h–13h."


def _skill(name: str = "analyze-with-stated-assumptions") -> Skill:
    return Skill(name=name, description="d", body=_SKILL_BODY, applies_to=("team-step",))


def _ctx(*, agent_id: str | None = None, with_docs: bool = False) -> ProfileContext:
    docs = (CompanyDoc(slug="gio-lam", title="Giờ làm", updated="", body=_DOC_BODY),)
    return ProfileContext(
        persona="persona", project="", memory="", capability="",
        skills=(_skill(),), skill_selector=lambda skills, kind: [s.name for s in skills],
        company_docs=docs if with_docs else (), agent_id=agent_id,
    )


class _BareCtx:
    """What the loop tiers' own unit tests hand in: no skill pool, no selector."""

    persona = "persona"
    project = memory = capability = ""


# ---------------------------------------------------------------------------- helper


def test_bare_context_yields_empty_extras_like_an_agent_with_no_pool():
    assert team_step_prompt_extras(_BareCtx()) == {"skills": "", "company_docs": ""}
    assert team_step_skills_text(_BareCtx()) == ""


def test_extras_render_the_selected_skill_and_the_opted_in_docs():
    extras = team_step_prompt_extras(_ctx(with_docs=True))
    assert _SKILL_BODY in extras["skills"] and extras["skills"].startswith("<pm_skills>")
    assert _DOC_BODY in extras["company_docs"]
    assert extras["company_docs"].startswith("<company_docs>")


def test_selecting_a_skill_on_a_tool_tier_records_usage_for_the_curator(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda aid: tmp_path / "data" / aid,
    )
    team_step_skills_text(_ctx(agent_id="agent-a"))
    usage = json.loads((tmp_path / "data" / "agent-a" / "skill_usage.json").read_text())
    assert usage["analyze-with-stated-assumptions"]["count"] == 1


def test_no_agent_id_means_no_usage_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda aid: tmp_path / "data" / aid,
    )
    assert _SKILL_BODY in team_step_skills_text(_ctx(agent_id=None))
    assert not (tmp_path / "data").exists()


# --------------------------------------------------------------------------- thin loop


def test_thin_loop_work_prompt_carries_the_skill_and_the_docs():
    """Skills/docs ride in the USER message (same slot as on the native tier — the
    system message is persona + the shared step contract only)."""
    from my_crew.runtime_backends.thin_tool_loop import run_thin_loop
    from tests.test_thin_tool_loop import _FakeLlm, _settings, _text_turn

    llm = _FakeLlm([_text_turn("xong")])
    run_thin_loop(
        title="Phân tích doanh thu", handoff="", context=_ctx(with_docs=True),
        settings=_settings(), tools_map={}, max_steps=2, llm=llm,
    )
    first_call = llm.tool_calls[0]["messages"]
    user = first_call[1]["content"]
    assert first_call[1]["role"] == "user"
    assert _SKILL_BODY in user
    assert _DOC_BODY in user
    assert _SKILL_BODY not in first_call[0]["content"]


# --------------------------------------------------------------------------- deep tier


def _run_deep(monkeypatch, *, network: bool, sanitize):
    from my_crew.runtime_backends.deep_agent_loop import run_deep_agent_work
    from tests.test_deep_agent_compose_contract import _install_fakes, _Settings

    capture: dict = {}
    # The compose harness stubs `sanitize_bundle`; the network-on case below needs the
    # real one so the skills section is proven to go THROUGH the sanitizer.
    import my_crew.runtime_backends.deep_agent_sanitizer as san

    real_sanitize_bundle = san.sanitize_bundle
    _install_fakes(monkeypatch, capture)
    monkeypatch.setattr(san, "sanitize_bundle", real_sanitize_bundle)
    # The harness discards the invoke; keep the human message — that is where skills land.
    import my_crew.runtime_backends.community_loop_core as clc

    def _invoke(agent, messages, **_kw):
        capture["user"] = messages[1].content
        return {"messages": []}

    monkeypatch.setattr(clc, "invoke_capped", _invoke)
    run_deep_agent_work(
        title="Nghiên cứu", handoff="", context=_ctx(with_docs=True), settings=_Settings(),
        sandbox_cfg={"provider": "docker", "network": network}, loop_limit=4,
        sanitize=sanitize,
    )
    return capture["user"]


def test_deep_tier_network_off_gets_the_skill_but_never_the_company_docs(monkeypatch):
    user = _run_deep(monkeypatch, network=False, sanitize=lambda s: (s, True))
    assert _SKILL_BODY in user
    # Internal docs stay withheld on the one tier that can egress them.
    assert _DOC_BODY not in user


def test_deep_tier_network_on_routes_the_skill_through_the_sanitizer(monkeypatch):
    seen: list[str] = []

    def _sanitize(payload: str):
        seen.append(payload)
        return payload.replace("giả định", "[đã lược]"), True

    user = _run_deep(monkeypatch, network=True, sanitize=_sanitize)
    assert "===KENH:skills===" in seen[0] and _SKILL_BODY in seen[0]
    assert "[đã lược]" in user and _SKILL_BODY not in user


# ---------------------------------------------------------------------------- sanitizer


def test_sanitize_bundle_round_trips_the_skills_section():
    from my_crew.runtime_backends.deep_agent_sanitizer import sanitize_bundle

    bundle, ok = sanitize_bundle(
        lambda s: (s, True), persona="p", project="", memory="", capability="",
        handoff="h", skills="<pm_skills>\nx\n</pm_skills>",
    )
    assert ok and bundle.skills == "<pm_skills>\nx\n</pm_skills>"
    assert bundle.persona == "p" and bundle.handoff == "h"


def test_sanitize_bundle_skills_default_keeps_old_callers_whole():
    from my_crew.runtime_backends.deep_agent_sanitizer import sanitize_bundle

    bundle, ok = sanitize_bundle(
        lambda s: (s, True), persona="p", project="", memory="", capability="", handoff="",
    )
    assert ok and bundle.skills == ""
