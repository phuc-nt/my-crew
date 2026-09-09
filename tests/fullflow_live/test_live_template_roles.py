"""The shipped office crew, hired from templates, does the work its roles were built for.

Every other topology case seeds a hand-written pm fleet. None of them ever ran an agent
that was CREATED from `profiles/templates/*` — the researcher's `web_search` opt-in, the
qa reviewer preference, the template skill pool loaded live off `template_role` — so the
one path a real operator takes ("Tạo cả đội", enable, delegate) had no live witness.

R1/R2 share ONE journey (module fixture): hire the office crew onto a seeded fleet, enable
the new hires, delegate a brief that needs the web + a review, and read the evidence from
the store, the work orders and the transcripts. R3 is the personal-assistant template's
characteristic output — a morning briefing — driven in-process against a real model with
every external source switched off, so only the code-owned facts (time of day, weekday)
can appear.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from tests.fullflow_live.conftest import (
    _ENV_SETTINGS,
    MAX_COST_PER_CASE_USD,
    requires_search,
)
from tests.fullflow_live.topology import (
    SETTLE_TIMEOUT_S,
    boot,
    seed_home,
    step_texts,
    transcript_events,
    wait_until_settled,
    work_orders,
)

#: Members the office manifest hires that the seeded pm fleet does NOT already have.
#: `coordinator` and `analyst` exist in the seed (same ids), so the crew create must skip
#: them — the idempotency half of the contract, measured on the same call.
OFFICE_NEW_HIRES = frozenset({"researcher", "content", "qa"})
OFFICE_ALREADY_THERE = frozenset({"coordinator", "analyst"})

RESEARCHER_ID = "researcher"
QA_ID = "qa"
RESEARCHER_TEMPLATE_SKILL = "research-with-cited-sources"

#: Needs the web (→ researcher) and produces cited prose; the review row comes from the
#: lane itself (a sprint step always carries `needs_review`) and lands on the qa hire by
#: reviewer preference. Counts are lower bounds on purpose: the step's self-check grades
#: the draft against criteria written from this text, and "đúng 2 nguồn" turned a
#: five-source draft into `needs_decision` (measured); asking for QA inside the brief
#: likewise minted a criterion the researcher cannot meet within its own step.
BRIEF = (
    "Tìm ít nhất 2 nguồn web gần đây về xu hướng AI agent cho doanh nghiệp nhỏ "
    "và viết một đoạn ngắn khoảng 5 câu có dẫn link nguồn."
)


def _search_env() -> dict[str, str]:
    """The one provider key the environment has, as the seeded `.env` line."""
    providers = (("BRAVE_API_KEY", "brave_api_key"), ("TAVILY_API_KEY", "tavily_api_key"))
    for env_name, attr in providers:
        value = getattr(_ENV_SETTINGS, attr, "") or ""
        if value:
            return {env_name: value}
    return {}


@dataclasses.dataclass
class OfficeJourney:
    home: Path
    task_id: str
    final: dict
    created: list[str]
    skipped: list[str]


@pytest.fixture(scope="module")
def office_journey(tmp_path_factory, live_api_key_module):
    """Hire the office crew, enable it, delegate BRIEF, wait for the task to settle.

    Module-scoped on purpose: R1 and R2 read different evidence from the SAME run, and a
    second run would double the spend for no extra information.
    """
    home = tmp_path_factory.mktemp("office") / "home"
    seed_home(home, api_key=live_api_key_module, extra_env=_search_env())
    server = boot(home, api_key=live_api_key_module, seed=False)
    try:
        code, body = server.post("/api/crew/create?crew_id=office", {}, timeout=60)
        assert code == 200, f"crew create failed {code}: {body!r}"
        assert body.get("failed") == [], f"crew members failed to create: {body!r}"
        created = list(body.get("created") or [])
        skipped = list(body.get("skipped") or [])
        assert OFFICE_NEW_HIRES <= set(created), f"created={created!r}"
        assert OFFICE_ALREADY_THERE <= set(skipped), f"skipped={skipped!r}"

        # Template hires land disabled (tokens first); Resume is what puts them to work.
        for agent_id in created:
            code, body = server.patch(f"/api/agents/{agent_id}/enabled", {"enabled": True},
                                      timeout=30)
            assert code == 200, f"enable {agent_id} failed {code}: {body!r}"
            assert body.get("effective_enabled") is True, f"{agent_id} still gated: {body!r}"

        # Same bound as the cost-cap journey: the router's sprint intake reasons over
        # the brief and re-asks a garbage answer, so on a slow upstream a single
        # delegate legitimately runs past three minutes (measured 3:00+ once).
        code, body = server.post(
            "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=900
        )
        assert code == 200, f"delegate failed {code}: {body!r}"
        task_id = body.get("task_id")
        assert task_id, f"delegate returned no task_id: {body!r}"

        # The sprint step alone measured ~4 min; the review row it always mints runs after.
        final = wait_until_settled(server, task_id, timeout_s=SETTLE_TIMEOUT_S)
        yield OfficeJourney(home=home, task_id=task_id, final=final,
                            created=created, skipped=skipped)
    finally:
        server.stop()
    assert server.proc.poll() is not None


def _store_steps(home: Path, task_id: str) -> list:
    """The task's steps from the seeded home's OWN store — the HTTP projection carries no
    capability flags, and `needs_web` is exactly the fact R1 is about."""
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(home / ".data" / "team_tasks.sqlite3")
    try:
        task = store.get(task_id)
    finally:
        store.close()
    assert task is not None, f"task {task_id} missing from the seeded store"
    return list(task.steps)


@requires_search
def test_r1_office_crew_routes_web_work_to_the_researcher_and_review_to_qa(
    office_journey, journey_budget,
):
    final = office_journey.final
    cost = (final.get("cost") or {}).get("total_cost_usd") or 0.0
    # The task projection keeps its lifecycle under "state", not at the top level.
    state = (final.get("state") or {}).get("status")
    journey_budget.note_cost(cost, final)

    assert state in {"done", "delivered"}, f"office task ended {state!r}: {final!r}"
    failed = [s for s in final.get("steps") or [] if s.get("status") == "failed"]
    assert not failed, f"steps failed: {failed!r}"
    assert cost > 0, "a real fleet run must record spend"

    # -- the researcher owns every step that needs the web ---------------------------
    steps = _store_steps(office_journey.home, office_journey.task_id)
    web_steps = [s for s in steps if getattr(s, "needs_web", False)]
    assert web_steps, (
        "the coordinator planned no needs_web step for a brief that asks for web sources — "
        f"steps={[(s.step_id, s.assigned_to, s.title) for s in steps]!r}"
    )
    wrong_owner = [(s.step_id, s.assigned_to) for s in web_steps
                   if s.assigned_to != RESEARCHER_ID]
    assert not wrong_owner, f"needs_web steps not given to the researcher: {wrong_owner!r}"

    # -- and it really searched: the launcher's prefetch event, with real queries -----
    web_ids = {s.step_id for s in web_steps}
    orders = [o for o in work_orders(office_journey.home, office_journey.task_id)
              if o.get("step_id") in web_ids]
    assert orders, f"no work order for the researcher's steps {sorted(web_ids)!r}"
    searched = []
    for order in orders:
        events = transcript_events(office_journey.home, office_journey.task_id,
                                   order.get("transcript") or "")
        searched.extend(e for e in events
                        if e.get("t") == "prefetch" and any(e.get("queries") or []))
    assert searched, (
        "the researcher's transcripts carry no prefetch event with queries — the "
        "template's web_search opt-in never reached the launcher"
    )

    # -- the researcher's artifact cites its sources (a link, not a paraphrase) -------
    # Artifacts are named by row sequence (`step-<n>.json`), not by step id, so the web
    # steps' own `outcome_ref` is the only honest join.
    texts = step_texts(office_journey.home, office_journey.task_id)
    web_artifacts = {Path(s.outcome_ref).name for s in web_steps if s.outcome_ref}
    assert web_artifacts, f"web steps carry no outcome_ref: {[s.step_id for s in web_steps]!r}"
    cited = [name for name, text in texts.items()
             if name in web_artifacts and "http" in text]
    assert cited, (
        f"no researcher artifact contains a URL — looked at {sorted(web_artifacts)!r} "
        f"among artifacts={sorted(texts)!r}"
    )

    # -- review goes to the qa hire (reviewer preference by id) ----------------------
    reviews = [s for s in final.get("steps") or [] if s.get("step_type") == "review"]
    assert reviews, (
        "the delivered work had no review row (sprint always carries needs_review) — "
        f"steps={[(s.get('step_id'), s.get('step_type')) for s in final.get('steps') or []]!r}"
    )
    not_qa = [(s.get("step_id"), s.get("assigned_to")) for s in reviews
              if s.get("assigned_to") != QA_ID]
    assert not not_qa, f"review rows not held by qa: {not_qa!r}"


@requires_search
def test_r2_researcher_used_its_template_skill_on_the_live_step(office_journey):
    """The skill file shipped under `profiles/templates/researcher/skills/` is loaded off
    the hire's `template_role` and SELECTED for the step — the curator's usage ledger is
    the only place that selection is observable after the fact."""
    usage_path = (office_journey.home / ".data" / "agents" / RESEARCHER_ID
                  / "skill_usage.json")
    assert usage_path.exists(), (
        "no skill_usage.json for the researcher — either the template skill pool was not "
        "loaded for the hire or the step ran without naming its agent"
    )
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    entry = usage.get(RESEARCHER_TEMPLATE_SKILL) or {}
    assert int(entry.get("count") or 0) >= 1, (
        f"{RESEARCHER_TEMPLATE_SKILL!r} never selected: {usage!r}"
    )


# ------------------------------------------------------------------ personal assistant


_HHMM = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _briefing_config():
    """Telegram present (so `deliver` runs), token env deliberately absent, and every
    Google source OFF: the model must write from the code-owned day facts alone."""
    from my_crew.config.config_builders import build_reporting_config_from_dict
    from my_crew.config.telegram_config import TelegramConfig

    config = build_reporting_config_from_dict(
        {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C_TK",
         "slack_stakeholder_channel": "", "slack_external_channels": "",
         "gws_enabled": False}
    )
    telegram = TelegramConfig(
        bot_token_env="FULLFLOW_LIVE_ABSENT_BOT_TOKEN", chat_ids=("111",),
        ops_operator_id="111",
    )
    return dataclasses.replace(config, telegram=telegram)


def test_r3_personal_briefing_greets_the_real_time_of_day_and_invents_no_source(
    tmp_path, live_api_key,
):
    from my_crew.config.config_builders import build_settings_from_dict
    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("personal")
    graphs = importlib.import_module("domain_pack_personal.graphs")
    tools = importlib.import_module("domain_pack_personal.tools")
    settings = build_settings_from_dict({
        "openrouter_api_key": live_api_key, "data_dir": tmp_path, "dry_run": True,
    })
    started = datetime.now().astimezone()
    graph = pack.report_kinds["briefing"](None, config=_briefing_config(), settings=settings)
    result = graph.invoke({})
    finished = datetime.now().astimezone()

    assert result["delivered"] is True
    assert result["delivery_summary"] == "telegram=dry_run"
    cost = result.get("cost_usd")
    assert cost is not None and cost > 0, (
        f"cost_usd={cost!r} — the fallback text ran, not the model (the case would prove "
        "nothing about what the assistant writes)"
    )
    assert cost <= MAX_COST_PER_CASE_USD

    text = result["report_text"]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert 1 <= len(lines) <= 10, f"briefing is {len(lines)} lines: {text!r}"

    # Greeting matches the clock the snapshot carried (prompt: "chào đúng buổi").
    expected = {graphs._time_of_day_vi(started.hour), graphs._time_of_day_vi(finished.hour)}
    opening = "\n".join(lines[:2]).lower()
    assert any(word in opening for word in expected), (
        f"opening does not greet the {sorted(expected)!r} of day: {opening!r}"
    )
    # The weekday is a code-owned fact in the snapshot; it must survive into the text.
    assert any(day.lower() in text.lower() for day in tools._WEEKDAYS_VI), (
        f"no weekday in the briefing: {text!r}"
    )
    # With every calendar/mail/reminder source off, the ONLY clock time the assistant
    # can legitimately mention is "now"; any other HH:MM is an invented appointment.
    allowed = {started.strftime("%H:%M"), finished.strftime("%H:%M")}
    invented = [m.group(0) for m in _HHMM.finditer(text) if m.group(0) not in allowed]
    assert not invented, f"briefing invents clock times {invented!r}: {text!r}"
    for placeholder in ("(không có)", "(chưa cấu hình)"):
        assert placeholder not in text, f"raw placeholder leaked into the briefing: {text!r}"
