"""M3-P11 S1: config-driven extra MCP servers (Linear) — selection + backward-compat.

P8-style selection tests: a declared `integrations.linear` block reaches the right
`McpServerSpec`; missing dist/env raise the clear lazy-validate errors; no block ⇒ empty
`extra_servers` (byte-identical to pre-P11). Tokens come from os.environ by name, never yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from my_crew.config.config_builders import build_reporting_config_from_dict
from my_crew.profile.loader_mapping import build_reporting_dict


def _linear_dict(mcp_dist: str = "/tmp/linear/dist/index.js") -> dict:
    """A from_dict input declaring one Linear extra server."""
    return {
        "extra_servers": [
            {"name": "linear", "mcp_dist": mcp_dist, "required_env": ["LINEAR_API_TOKEN"]}
        ]
    }


def test_no_integrations_block_empty_extra_servers():
    """Backward-compat: no extra_servers ⇒ {} (no behavior change vs pre-P11)."""
    c = build_reporting_config_from_dict({})
    assert c.extra_servers == {}


def test_declared_linear_reaches_right_spec(monkeypatch):
    monkeypatch.setenv("LINEAR_API_TOKEN", "lin_secret_token")
    c = build_reporting_config_from_dict(_linear_dict())
    spec = c.extra_servers["linear"]
    assert spec.name == "linear"
    assert spec.dist_path == Path("/tmp/linear/dist/index.js")
    assert spec.required_env_keys == ("LINEAR_API_TOKEN",)
    # Env VALUE pulled from os.environ by the declared NAME.
    assert spec.env["LINEAR_API_TOKEN"] == "lin_secret_token"


def test_token_value_never_in_parsed_yaml_dict():
    """The profile-derived dict carries env NAMES only, never token VALUES."""
    yaml_doc = {
        "integrations": {"linear": {"mcp_dist": "/x/dist.js", "required_env": ["LINEAR_API_TOKEN"]}}
    }
    d = build_reporting_dict(yaml_doc)
    entry = d["extra_servers"][0]
    assert entry["required_env"] == ["LINEAR_API_TOKEN"]
    # No 'token'/'secret'/value key — only the name list.
    assert "token" not in str(entry).lower().replace("linear_api_token", "")


def test_missing_dist_validate_raises(monkeypatch):
    monkeypatch.setenv("LINEAR_API_TOKEN", "x")
    c = build_reporting_config_from_dict(_linear_dict("/no/such/path/index.js"))
    with pytest.raises(FileNotFoundError, match="linear"):
        c.extra_servers["linear"].validate()


def test_missing_env_validate_raises(monkeypatch, tmp_path):
    dist = tmp_path / "index.js"
    dist.write_text("// stub")
    monkeypatch.delenv("LINEAR_API_TOKEN", raising=False)
    c = build_reporting_config_from_dict(_linear_dict(str(dist)))
    with pytest.raises(RuntimeError, match="LINEAR_API_TOKEN"):
        c.extra_servers["linear"].validate()


def test_loader_maps_integrations_block(monkeypatch):
    """profile.yaml `integrations:` → the from_dict `extra_servers` list shape."""
    monkeypatch.delenv("LINEAR_MCP_DIST", raising=False)
    yaml_doc = {
        "integrations": {
            "linear": {"mcp_dist": "/built/linear.js", "required_env": ["LINEAR_API_TOKEN"]}
        }
    }
    d = build_reporting_dict(yaml_doc)
    assert d["extra_servers"] == [
        {"name": "linear", "mcp_dist": "/built/linear.js", "required_env": ["LINEAR_API_TOKEN"]}
    ]


def test_loader_mcp_dist_falls_back_to_env(monkeypatch):
    """Empty yaml mcp_dist ⇒ <NAME>_MCP_DIST env."""
    monkeypatch.setenv("LINEAR_MCP_DIST", "/env/linear.js")
    yaml_doc = {"integrations": {"linear": {"mcp_dist": "", "required_env": ["LINEAR_API_TOKEN"]}}}
    d = build_reporting_dict(yaml_doc)
    assert d["extra_servers"][0]["mcp_dist"] == "/env/linear.js"


def test_loader_no_integrations_omits_key():
    """No integrations block ⇒ key omitted (from_dict defaults to {})."""
    d = build_reporting_dict({})
    assert "extra_servers" not in d
