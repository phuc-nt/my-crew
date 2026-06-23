"""Slice 3: sprint parsing + daily/weekly prompt + cli/cron kind dispatch."""

from __future__ import annotations

from datetime import date

from src.entrypoints.cli import _parse_report_kind
from src.llm.report_prompt import REPORT_TITLES, build_detail_messages
from src.tools.jira_read import parse_sprint
from src.tools.models import Risk

RISKS = [Risk(kind="blocker", severity="high", subject="AB-1", detail="d", suggested_action="a")]


def test_parse_sprint_real_shape():
    raw = {
        "id": 2,
        "name": "SCRUM Sprint 0",
        "state": "active",
        "startDate": "2026-06-21T15:51:18.494Z",
        "endDate": "2026-07-05T15:51:18.494Z",
    }
    s = parse_sprint(raw)
    assert s.id == "2"
    assert s.name == "SCRUM Sprint 0"
    assert s.state == "active"
    assert s.start_date == date(2026, 6, 21)
    assert s.end_date == date(2026, 7, 5)


def test_parse_sprint_missing_id_raises():
    import pytest

    with pytest.raises(ValueError, match="missing 'id'"):
        parse_sprint({"name": "x"})


def test_daily_prompt_is_short_no_sprint():
    msg = build_detail_messages(RISKS, report_date="2026-06-22", kind="daily")[1]["content"]
    assert "DAILY STANDUP" in msg
    assert "Sprint:" not in msg


def test_weekly_prompt_has_sprint_review_and_context():
    ctx = "Sprint: S0 (active), 2026-06-21 → 2026-07-05."
    msg = build_detail_messages(
        RISKS, report_date="2026-06-22", kind="weekly", sprint_context=ctx
    )[1]["content"]
    assert "SPRINT REVIEW" in msg
    assert "Sprint: S0" in msg


def test_report_titles():
    assert REPORT_TITLES["daily"] == "Daily Standup"
    assert REPORT_TITLES["weekly"] == "Sprint Review"


def test_cli_parse_report_kind():
    assert _parse_report_kind([]) == "daily"
    assert _parse_report_kind(["--daily"]) == "daily"
    assert _parse_report_kind(["--weekly"]) == "weekly"


# --- Slice D: OKR section embedded in the weekly report (fault-isolated) ---


def _okr_rollup(config):
    from src.agent.okr_analyzer import OkrRollup
    from src.tools.models import KeyResult, Objective

    obj = Objective("Tăng retention",
                    (KeyResult("KR1", ("E-1",), None, progress_pct=60.0),), progress_pct=60.0)
    return OkrRollup(objectives=(obj,), problems=(), at_risk=())


class _OkrCfg:
    """ReportingConfig stub: only the fields the weekly OKR helpers read."""

    def __init__(self, page_id):
        self.okr_confluence_page_id = page_id
        self.okr_behind_threshold = 0.5


def test_weekly_okr_section_omitted_when_unconfigured():
    from src.agent import okr_weekly_section as okr

    assert okr.weekly_okr_section("2026-06-22", _OkrCfg(None)) == ""


def test_weekly_okr_section_rendered_when_configured(monkeypatch):
    from src.agent import okr_weekly_section as okr

    monkeypatch.setattr(okr, "build_okr_rollup", _okr_rollup)
    out = okr.weekly_okr_section("2026-06-22", _OkrCfg("12345"))
    assert "<h2>OKR Status" in out
    assert "60%" in out  # deterministic number from the rollup


def test_weekly_okr_section_survives_fetch_failure(monkeypatch):
    from src.agent import okr_weekly_section as okr

    def boom(config):
        raise RuntimeError("confluence down")

    monkeypatch.setattr(okr, "build_okr_rollup", boom)
    out = okr.weekly_okr_section("2026-06-22", _OkrCfg("12345"))
    assert "Không lấy được dữ liệu OKR" in out  # note, not a raise
    # Raw exception text must NOT leak into the page body (H1): generic note only.
    assert "confluence down" not in out
    assert "<" not in out.replace("<p>", "").replace("</p>", "")  # no injected markup


def test_weekly_okr_slack_line(monkeypatch):
    from src.agent import okr_weekly_section as okr

    monkeypatch.setattr(okr, "build_okr_rollup", _okr_rollup)
    line = okr.weekly_okr_slack_line(_OkrCfg("12345"))
    assert "OKR: 60%" in line and line.startswith("\n•")


def test_weekly_okr_slack_line_empty_when_unconfigured():
    from src.agent import okr_weekly_section as okr

    assert okr.weekly_okr_slack_line(_OkrCfg(None)) == ""


def test_cron_no_key_returns_one(monkeypatch, tmp_path):
    # cron reaches the kind dispatch then exits 1 cleanly with no key (no network).
    import src.config.settings as settings_mod
    from src.entrypoints.cron import main as cron_main

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Also clear stakeholder/external channel vars so a CI runner that exports a
    # mismatched pair can't make the always-on config build error before the key gate.
    monkeypatch.delenv("SLACK_STAKEHOLDER_CHANNEL", raising=False)
    monkeypatch.delenv("SLACK_EXTERNAL_CHANNELS", raising=False)
    monkeypatch.setattr(settings_mod, "REPO_ROOT", tmp_path)  # empty dir -> no .env
    assert cron_main(["--weekly"]) == 1
    assert cron_main(["--daily"]) == 1
