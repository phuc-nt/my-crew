"""M3-P11 S1: Linear READ helpers over a config-driven extra MCP server.

Fake `call_tool` (no live key, no spawn). Verifies the verbatim tool names are called
and the "linear not declared" setup error is clear. READ bypasses the Action Gateway.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders import build_reporting_config_from_dict
from my_crew.tools import linear_read


def _config_with_linear(monkeypatch):
    monkeypatch.setenv("LINEAR_API_TOKEN", "x")
    return build_reporting_config_from_dict(
        {
            "extra_servers": [
                {"name": "linear", "mcp_dist": "/x/index.js", "required_env": ["LINEAR_API_TOKEN"]}
            ]
        }
    )


def test_get_issues_calls_verbatim_tool(monkeypatch):
    config = _config_with_linear(monkeypatch)
    calls = []

    def fake_call_tool(spec, tool_name, args):
        calls.append((spec.name, tool_name, args))
        return [{"id": "ISS-1", "title": "demo"}]

    monkeypatch.setattr(linear_read, "call_tool", fake_call_tool)
    result = linear_read.get_issues(config)
    assert result == [{"id": "ISS-1", "title": "demo"}]
    assert calls == [("linear", "linear_getIssues", {})]


def test_search_issues_passes_query(monkeypatch):
    config = _config_with_linear(monkeypatch)
    captured = {}

    def fake_call_tool(spec, tool_name, args):
        captured["tool"] = tool_name
        captured["args"] = args
        return []

    monkeypatch.setattr(linear_read, "call_tool", fake_call_tool)
    linear_read.search_issues(config, "overdue")
    assert captured["tool"] == "linear_searchIssues"
    assert captured["args"]["query"] == "overdue"


def test_get_epics_calls_projects_tool(monkeypatch):
    config = _config_with_linear(monkeypatch)
    captured = {}

    monkeypatch.setattr(
        linear_read, "call_tool", lambda spec, tool, args: captured.update(tool=tool) or []
    )
    linear_read.get_epics(config)
    assert captured["tool"] == "linear_getProjects"


def test_not_declared_raises_clear_error():
    config = build_reporting_config_from_dict({})  # no linear
    with pytest.raises(RuntimeError, match="linear MCP server not declared"):
        linear_read.get_issues(config)
