"""v20.5 Phase 0: team-step external_write → gateway.

Verifies the previously-unwired `external_write` hook now routes a team-step's egress through
the Action Gateway (Lớp A/B + audit), and that agents without the opt-in stay byte-identical
(external_write None / no-op).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from my_crew.profile.loader import load_profile


def _profile(tmp_path: Path, agent_id: str, yaml_body: str) -> None:
    d = tmp_path / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(textwrap.dedent(yaml_body), encoding="utf-8")


# --- loader parse -------------------------------------------------------------------


def test_absent_egress_is_none(tmp_path):
    _profile(tmp_path, "a1", "name: A1\n")
    loaded = load_profile("a1", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert loaded.team_step_egress is None


def test_egress_channel_parsed(tmp_path):
    _profile(tmp_path, "a2", "name: A2\nteam_step_egress:\n  channel: C123\n")
    loaded = load_profile("a2", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert loaded.team_step_egress == {"channel": "C123"}


def test_egress_needs_channel(tmp_path):
    _profile(tmp_path, "a3", "name: A3\nteam_step_egress:\n  poll: 5\n")
    with pytest.raises(RuntimeError, match="needs a Slack channel"):
        load_profile("a3", profiles_dir=tmp_path, data_dir=tmp_path / ".data")


def test_egress_bad_type(tmp_path):
    _profile(tmp_path, "a4", "name: A4\nteam_step_egress: notamap\n")
    with pytest.raises(RuntimeError, match="must be a mapping"):
        load_profile("a4", profiles_dir=tmp_path, data_dir=tmp_path / ".data")


# --- external_write hook routes through the gateway ---------------------------------


class _FakeGatewayResult:
    def __init__(self, status):
        self.status = status
        self.approval_id = None


def test_external_write_routes_executed(monkeypatch):
    # A successful gateway post → hook returns True (deliver proceeds).
    from my_crew.runtime import team_step_egress as mod

    seen = {}

    def _fake_deliver(text, **kw):
        seen["text"] = text
        seen["channel"] = kw.get("channel")
        seen["rationale"] = kw.get("rationale")
        return _FakeGatewayResult("executed")

    monkeypatch.setattr("my_crew.actions.slack_write.deliver_report", _fake_deliver)
    hook = mod.make_external_write(
        gateway=object(), config=object(), agent_id="noi-dung",
        channel="C1", report_date="2026-07-11",
    )
    assert hook("Nội dung bài viết hoàn chỉnh.") is True
    assert seen["channel"] == "C1"
    assert "noi-dung" in seen["rationale"]  # audit rationale carries the agent id


def test_external_write_pending_approval_returns_false(monkeypatch):
    # A Lớp B queue (pending_approval) → hook returns False (deliver → awaiting_approval).
    from my_crew.runtime import team_step_egress as mod

    monkeypatch.setattr(
        "my_crew.actions.slack_write.deliver_report",
        lambda text, **kw: _FakeGatewayResult("pending_approval"),
    )
    hook = mod.make_external_write(object(), object(), "a", "C1", "2026-07-11")
    assert hook("some external post") is False


def test_external_write_lop_a_deny_returns_false(monkeypatch):
    # A Lớp A hard-deny (denied) → hook returns False (step does not silently succeed).
    from my_crew.runtime import team_step_egress as mod

    monkeypatch.setattr(
        "my_crew.actions.slack_write.deliver_report",
        lambda text, **kw: _FakeGatewayResult("denied"),
    )
    hook = mod.make_external_write(object(), object(), "a", "C1", "2026-07-11")
    assert hook("post") is False


def test_external_write_empty_text_noop(monkeypatch):
    # Empty result → nothing to gate; returns True without calling deliver.
    from my_crew.runtime import team_step_egress as mod

    called = {"n": 0}

    def _spy(text, **kw):
        called["n"] += 1
        return _FakeGatewayResult("executed")

    monkeypatch.setattr("my_crew.actions.slack_write.deliver_report", _spy)
    hook = mod.make_external_write(object(), object(), "a", "C1", "2026-07-11")
    assert hook("   ") is True
    assert called["n"] == 0
