"""Action policy: allowlist + Lớp A hard-deny (PDR §5.2, §7.9).

Default-DENY: only explicitly-allowlisted actions pass, and the red-line
categories are hard-denied even if allowlisted. Includes adversarial payloads
from the Phase 0 code review (bypass attempts that must be blocked).
"""

from __future__ import annotations

import pytest

from src.actions.hard_block import BlockCategory, classify

# (action, expected category) — each must be blocked by a red-line check.
DENY_CASES = [
    # --- data loss: MCP ---
    ({"type": "mcp_tool", "server": "confluence", "tool": "deletePage", "args": {"id": "1"}},
     BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "jira", "tool": "deleteIssue", "args": {"key": "AB-1"}},
     BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "confluence", "tool": "trashPage", "args": {"id": "1"}},
     BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "body": "x"}}, BlockCategory.DATA_LOSS),  # no version
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "body": "x", "version": ""}}, BlockCategory.DATA_LOSS),  # blank version
    # H-NEW-2: string/negative/garbage versions are NOT valid versions
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "version": "0"}}, BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "version": -1}}, BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "version": "abc"}}, BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
      "args": {"id": "1", "version": True}}, BlockCategory.DATA_LOSS),
    # --- data loss: gh ---
    ({"type": "gh_cli", "argv": ["repo", "delete", "org/repo"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["release", "delete", "v1"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["issue", "delete", "42"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["pr", "create", "--force"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["push", "--force", "origin", "main"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["push", "+refs/heads/main"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "-X", "DELETE", "/repos/o/r/issues/1"]},
     BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "--method=PATCH", "/x"]}, BlockCategory.DATA_LOSS),
    # C-NEW-1: gh api glued verb + implicit POST via field flags
    ({"type": "gh_cli", "argv": ["api", "-XPOST", "/repos/x"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "-XDELETE", "/repos/x"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "repos/o/r/issues", "-f", "title=x"]},
     BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "repos/o/r/i", "-F", "n=@file"]}, BlockCategory.DATA_LOSS),
    ({"type": "gh_cli", "argv": ["api", "repos/o/r/i", "--raw-field", "a=b"]},
     BlockCategory.DATA_LOSS),
    # --- credential (realistic token lengths) ---
    ({"type": "mcp_tool", "server": "slack", "tool": "post_message",
      "args": {"channel": "C1", "text": "deploy with xoxb-FAKE1234"}},
     BlockCategory.CREDENTIAL),
    ({"type": "mcp_tool", "server": "slack", "tool": "post_message",
      "args": {"channel": "C1", "token": "anyvalue"}}, BlockCategory.CREDENTIAL),  # secret key
    # nested AWS access key id
    ({"type": "mcp_tool", "server": "slack", "tool": "post_message",
      "args": {"blocks": [{"text": "AKIAFFFFFFFFFFFFFFFF"}]}}, BlockCategory.CREDENTIAL),
    ({"type": "mcp_tool", "server": "slack", "tool": "post_message",
      "args": {"text": "-----BEGIN RSA PRIVATE KEY-----"}}, BlockCategory.CREDENTIAL),
    ({"type": "gh_cli", "argv": ["api", "-H", "Authorization: ghp_abcdefghij1234567890XYZ"]},
     BlockCategory.CREDENTIAL),
    # --- security ---
    ({"type": "mcp_tool", "server": "jira", "tool": "setPermission",
      "args": {"visibility": "public"}}, BlockCategory.SECURITY),
    ({"type": "mcp_tool", "server": "jira", "tool": "updateProjectRole",
      "args": {"role": "admin"}}, BlockCategory.SECURITY),
    ({"type": "mcp_tool", "server": "confluence", "tool": "addRestriction",
      "args": {"mode": "anonymous"}}, BlockCategory.SECURITY),
    ({"type": "gh_cli", "argv": ["repo", "edit", "--visibility=public"]}, BlockCategory.SECURITY),
    # --- not allowlisted (default deny) ---
    ({"type": "mcp_tool", "server": "jira", "tool": "someBrandNewTool", "args": {}},
     BlockCategory.NOT_ALLOWLISTED),
    ({"type": "gh_cli", "argv": ["pr", "close", "42"]},
     BlockCategory.NOT_ALLOWLISTED),  # Lớp B, not auto-allowed
    ({"type": "weird_type", "args": {}}, BlockCategory.NOT_ALLOWLISTED),
]

# Allowlisted, non-red-line actions that MUST pass.
ALLOW_CASES = [
    {"type": "mcp_tool", "server": "slack", "tool": "post_message",
     "args": {"channel": "C1", "text": "sprint update: 3 tasks done"}},
    {"type": "mcp_tool", "server": "confluence", "tool": "updatePage",
     "args": {"id": "1", "version": 5, "body": "report"}},
    {"type": "mcp_tool", "server": "jira", "tool": "addComment",
     "args": {"key": "AB-1", "body": "blocked on review"}},
    {"type": "gh_cli", "argv": ["pr", "list", "--state", "open"]},
    {"type": "gh_cli", "argv": ["pr", "create", "--title", "Report"]},
    {"type": "gh_cli", "argv": ["api", "/repos/o/r/pulls"]},  # read-only GET
    {"type": "gh_cli", "argv": ["api", "-X", "GET", "/repos/o/r/pulls"]},  # explicit GET
]


@pytest.mark.parametrize("action,category", DENY_CASES)
def test_policy_denies(action, category):
    verdict = classify(action)
    assert verdict.blocked is True
    assert verdict.category == category
    assert verdict.reason


@pytest.mark.parametrize("action", ALLOW_CASES)
def test_allowlisted_passes(action):
    assert classify(action).blocked is False


def test_non_dict_raises():
    with pytest.raises(TypeError):
        classify(["not", "a", "dict"])
