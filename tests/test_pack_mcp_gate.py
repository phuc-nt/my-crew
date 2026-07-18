"""v20 Phase 5: pack-declared MCP spawn gate (red-team SEC#4) + template-pack structure.

A community pack can declare its own MCP servers, but an MCP server is spawned as a real
subprocess with the agent's env. The gate is default-DENY: only operator-approved absolute
dist paths spawn, and the subprocess env is scrubbed of tokens.
"""

from __future__ import annotations

import pytest

from my_crew.packs.pack_mcp_gate import (
    PackMcpDenied,
    assert_pack_mcp_allowed,
    scrubbed_pack_mcp_env,
)


def test_relative_path_denied():
    with pytest.raises(PackMcpDenied, match="tương đối"):
        assert_pack_mcp_allowed("evil", "srv", "./node_modules/evil/index.js")


def test_empty_dist_denied():
    with pytest.raises(PackMcpDenied, match="trống"):
        assert_pack_mcp_allowed("evil", "srv", "")


def test_absolute_but_not_allowlisted_denied(monkeypatch):
    monkeypatch.delenv("PACK_MCP_ALLOWED_DIST", raising=False)
    # Default-deny: an absolute path not on the allowlist is refused (empty allowlist = deny all).
    with pytest.raises(PackMcpDenied, match="allowlist"):
        assert_pack_mcp_allowed("evil", "srv", "/opt/evil/index.js")


def test_allowlisted_path_permitted(monkeypatch, tmp_path):
    dist = tmp_path / "server.js"
    dist.write_text("// ok", encoding="utf-8")
    monkeypatch.setenv("PACK_MCP_ALLOWED_DIST", str(dist))
    assert_pack_mcp_allowed("good", "srv", str(dist))  # no raise


def test_scrubbed_env_excludes_tokens(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "tok")
    monkeypatch.setenv("MY_DECLARED_VAR", "value")
    env = scrubbed_pack_mcp_env(required_env=["MY_DECLARED_VAR"])
    assert "OPENROUTER_API_KEY" not in env  # token NOT inherited
    assert "ATLASSIAN_API_TOKEN" not in env
    assert env.get("MY_DECLARED_VAR") == "value"  # only declared var passes


def test_template_pack_excluded_from_discovery():
    from my_crew.packs.registry import discover_domains

    assert "_template" not in discover_domains()
