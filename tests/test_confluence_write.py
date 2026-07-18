"""Confluence write: page-result parsing + create_report_page through the gateway."""

from __future__ import annotations

import pytest

from my_crew.actions import confluence_write
from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.confluence_write import create_report_page, parse_created_page
from my_crew.audit.audit_log import AuditLog

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


class _Cfg:
    """Minimal ReportingConfig stub: only the fields create_report_page reads."""

    confluence_space_id = "65846"
    confluence_space_key = "MPM"
    atlassian_site_name = "phucnt0.atlassian.net"
    confluence_server = None


def _gateway(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(**kw), audit_log=AuditLog(tmp_path / "a.jsonl")
    )


def test_create_report_page_dry_run(settings_factory, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        confluence_write, "make_create_page_handler", lambda c: lambda a: called.append(a) or "x"
    )
    gw = _gateway(settings_factory, tmp_path, dry_run=True)
    result, page = create_report_page(
        "Báo cáo", "<p>body</p>", gateway=gw, config=_Cfg(), report_date="2026-06-21"
    )
    assert result.status == "dry_run"
    assert called == []  # handler not called under dry-run
    assert page is None


def test_create_report_page_empty_body_raises(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path)
    with pytest.raises(ValueError, match="empty"):
        create_report_page("t", "   ", gateway=gw, config=_Cfg(), report_date="2026-06-21")


def test_create_report_page_executed_returns_url(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(
        confluence_write,
        "make_create_page_handler",
        lambda c: lambda a: "created page id=131273 url=https://site/wiki/spaces/MPM/pages/131273/X",
    )
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    result, page = create_report_page(
        "t", "<p>x</p>", gateway=gw, config=_Cfg(), report_date="2026-06-21"
    )
    assert result.status == "executed"
    assert page is not None
    assert page.page_id == "131273"
    assert page.url == "https://site/wiki/spaces/MPM/pages/131273/X"
