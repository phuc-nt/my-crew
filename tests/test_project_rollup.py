"""v8 M22: project-rollup analyzer + external-block + status-API leak guard (red-team B3).

Load-bearing:
- Groups project agents with their latest report_summary; fleet-read agents excluded
  (capability-based, not domain-name) so the roll-up never recurses into admin.
- A never-run agent shows "chưa có báo cáo".
- project-rollup refuses an external audience (would leak internal summaries).
- report_summary never appears in the fleet-status API payloads.
"""

from __future__ import annotations

import pytest

from my_crew.packs.registry import _load_pack_module

_az = _load_pack_module("admin", "analyzers")
build_project_rollup = _az.build_project_rollup


def _agent(agent_id, project, reports, summary=None, ts="2026-07-04T08:00:00+00:00",
           status="delivered"):
    last = None
    if summary is not None or status != "delivered":
        last = {"ts": ts, "status": status, "report_summary": summary or ""}
    return {"agent_id": agent_id, "project": project, "reports": tuple(reports),
            "last_run": last}


def test_groups_project_agents_with_summary():
    payload = {"agents": [
        _agent("hr", "HR-1", ("headcount",), "Đội 12 người."),
        _agent("pm", "SCRUM", ("daily",), "Sprint 80%."),
    ], "alerts": []}
    r = build_project_rollup(payload)
    by_id = {row["agent_id"]: row for row in r.rows}
    assert by_id["hr"]["project"] == "HR-1" and "12 người" in by_id["hr"]["summary"]
    assert by_id["pm"]["project"] == "SCRUM"
    assert r.kind == "project-rollup"


def test_excludes_fleet_read_agents_by_capability():
    # admin serves project-rollup/cost-rollup → must NOT appear in its own roll-up (no
    # recursion), and the exclusion is by report-kind capability, not domain name.
    payload = {"agents": [
        _agent("pm", "SCRUM", ("daily",), "x"),
        _agent("admin", None, ("cost-rollup", "project-rollup")),
        _agent("overseer2", None, ("audit-digest",)),  # a second fleet-reader, no domain hint
    ], "alerts": []}
    ids = {row["agent_id"] for row in build_project_rollup(payload).rows}
    assert ids == {"pm"}


def test_never_run_agent_shows_placeholder():
    payload = {"agents": [_agent("fresh", "NEW", ("daily",))], "alerts": []}
    row = build_project_rollup(payload).rows[0]
    assert row["summary"] == "chưa có báo cáo" and row["last_status"] == "chưa chạy"


def test_agent_without_project_labelled():
    payload = {"agents": [_agent("x", None, ("daily",), "s")], "alerts": []}
    assert build_project_rollup(payload).rows[0]["project"] == "(chưa gán project)"


# --- external block ---


def test_project_rollup_refuses_external_audience():
    from my_crew.config.config_builders import (
        build_reporting_config_from_dict,
        build_settings_from_dict,
    )

    graphs = _load_pack_module("admin", "graphs")
    cfg = build_reporting_config_from_dict({"name": "admin"})
    settings = build_settings_from_dict({})
    with pytest.raises(ValueError, match="internal-only"):
        graphs.build_fleet_graph("project-rollup", config=cfg, settings=settings,
                                 audience="external")


# --- red-team B3: report_summary must NOT leak through the fleet-status API ---


def test_report_summary_stripped_from_status_views(tmp_path, monkeypatch):
    import json as _json

    from my_crew.server import agent_views

    # a run event carrying a summary
    ev = {"ts": "2026-07-04T08:00:00+00:00", "agent_id": "hr", "kind": "daily",
          "audience": "internal", "status": "delivered", "cost_usd": 0.01,
          "delivered": True, "report_summary": "NỘI DUNG NHẠY CẢM báo cáo"}
    monkeypatch.setattr("my_crew.server.agent_views.read_last_run_event", lambda aid: ev)

    public = agent_views._public_last_run("hr")
    assert "report_summary" not in public
    assert public["status"] == "delivered" and public["kind"] == "daily"
    # and not present anywhere in the serialized form
    assert "NHẠY CẢM" not in _json.dumps(public, ensure_ascii=False)


def test_report_summary_stripped_from_timeline(tmp_path, monkeypatch):
    # The timeline endpoint (/api/agents/{id}/runs) is a SECOND allowlist over run events —
    # it must also drop report_summary (independent code path from _public_last_run).
    import json as _json

    from my_crew.server import visualize_views

    ev = {"ts": "2026-07-04T08:00:00+00:00", "kind": "daily", "audience": "internal",
          "status": "delivered", "cost_usd": 0.01, "delivered": True,
          "report_summary": "NỘI DUNG NHẠY CẢM trong timeline"}
    monkeypatch.setattr("my_crew.server.visualize_views.read_run_events", lambda aid, **k: [ev])
    monkeypatch.setattr("my_crew.server.visualize_views._require_agent", lambda aid: None)
    out = visualize_views.runs_view("hr")
    assert all("report_summary" not in r for r in out["runs"])
    assert "NHẠY CẢM" not in _json.dumps(out, ensure_ascii=False)
