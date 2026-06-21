"""Confluence write: page-result parsing + create_report_page through the gateway."""

from __future__ import annotations

import pytest

from src.actions import confluence_write
from src.actions.action_gateway import ActionGateway
from src.actions.confluence_write import create_report_page, parse_created_page
from src.audit.audit_log import AuditLog

# Real shape from the Confluence MCP server (verified 2026-06-21).
REAL_CREATE_RESULT = [
    {"type": "text", "text": '✅ Page "X" created successfully!'},
    {"type": "text", "text": "📄 Page ID: 131273"},
    {"type": "text", "text": "🔗 View page: /spaces/MPM/pages/131273/X"},
    {"type": "text", "text": "📊 Page details: Space ID 65846, Version 1"},
]


def test_parse_real_shape():
    page = parse_created_page(
        REAL_CREATE_RESULT, site_name="phucnt0.atlassian.net", space_key="MPM"
    )
    assert page.page_id == "131273"
    assert page.url == "https://phucnt0.atlassian.net/wiki/spaces/MPM/pages/131273/X"


def test_parse_url_fallback_from_parts():
    # No /spaces path in response -> build from site + space + id.
    res = [{"type": "text", "text": "📄 Page ID: 999"}]
    page = parse_created_page(res, site_name="site.atlassian.net", space_key="MPM")
    assert page.page_id == "999"
    assert page.url == "https://site.atlassian.net/wiki/spaces/MPM/pages/999"


def test_parse_no_site_keeps_relative():
    page = parse_created_page(REAL_CREATE_RESULT, site_name=None, space_key="MPM")
    assert page.url == "/spaces/MPM/pages/131273/X"


def _reporting_cfg_stub(tmp_path, monkeypatch):
    """Patch get_reporting_config so create_report_page has space/site without .env."""
    from src.config import reporting_config as rc

    class _Cfg:
        confluence_space_id = "65846"
        confluence_space_key = "MPM"
        atlassian_site_name = "phucnt0.atlassian.net"
        confluence_server = None

    monkeypatch.setattr(rc, "get_reporting_config", lambda: _Cfg())
    monkeypatch.setattr(confluence_write, "get_reporting_config", lambda: _Cfg())


def test_create_report_page_dry_run(settings_factory, tmp_path, monkeypatch):
    _reporting_cfg_stub(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(
        confluence_write, "_create_page_handler", lambda a: called.append(a) or "x"
    )
    gw = ActionGateway(
        settings=settings_factory(dry_run=True), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    result, page = create_report_page(
        "Báo cáo", "<p>body</p>", gateway=gw, report_date="2026-06-21"
    )
    assert result.status == "dry_run"
    assert called == []  # handler not called under dry-run
    assert page is None


def test_create_report_page_empty_body_raises(settings_factory, tmp_path, monkeypatch):
    _reporting_cfg_stub(tmp_path, monkeypatch)
    gw = ActionGateway(settings=settings_factory(), audit_log=AuditLog(tmp_path / "a.jsonl"))
    with pytest.raises(ValueError, match="empty"):
        create_report_page("t", "   ", gateway=gw, report_date="2026-06-21")


def test_create_report_page_executed_returns_url(settings_factory, tmp_path, monkeypatch):
    _reporting_cfg_stub(tmp_path, monkeypatch)
    monkeypatch.setattr(
        confluence_write,
        "_create_page_handler",
        lambda a: "created page id=131273 url=https://site/wiki/spaces/MPM/pages/131273/X",
    )
    gw = ActionGateway(
        settings=settings_factory(dry_run=False), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    result, page = create_report_page("t", "<p>x</p>", gateway=gw, report_date="2026-06-21")
    assert result.status == "executed"
    assert page is not None
    assert page.page_id == "131273"
    assert page.url == "https://site/wiki/spaces/MPM/pages/131273/X"
