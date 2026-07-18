"""Action policy: allowlist + Lớp A hard-deny (PDR §5.2, §7.9).

Default-DENY: only explicitly-allowlisted actions pass, and the red-line
categories are hard-denied even if allowlisted. Includes adversarial payloads
from the Phase 0 code review (bypass attempts that must be blocked).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from my_crew.actions.hard_block import (
    BlockCategory,
    _attachment_verdict,
    classify,
)

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
    # --- M3-P11: a NEW known server (linear) does not weaken the Lớp A red line ---
    ({"type": "mcp_tool", "server": "linear", "tool": "linear_deleteIssue",
      "args": {"id": "ISS-1"}}, BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "linear", "tool": "linear_archiveProject",
      "args": {"id": "P-1"}}, BlockCategory.DATA_LOSS),
    ({"type": "mcp_tool", "server": "linear", "tool": "linear_createComment",
      "args": {"issueId": "ISS-1", "body": "token ghp_abcdefghij1234567890XYZ"}},
     BlockCategory.CREDENTIAL),
    # an unlisted linear tool is still default-deny
    ({"type": "mcp_tool", "server": "linear", "tool": "linear_makeAdmin", "args": {}},
     BlockCategory.NOT_ALLOWLISTED),
    # --- M3-P11 (D2): email_send red line — secret/empty-recipient/empty-body denied ---
    ({"type": "email_send", "to": "x@y.com", "subject": "r",
      "body": "deploy with ghp_abcdefghij1234567890XYZ"}, BlockCategory.CREDENTIAL),
    ({"type": "email_send", "to": "", "subject": "r", "body": "hi"},
     BlockCategory.NOT_ALLOWLISTED),
    ({"type": "email_send", "to": "x@y.com", "subject": "r", "body": "  "},
     BlockCategory.NOT_ALLOWLISTED),
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
    # M3-P11: a well-formed email_send passes Lớp A (it is then Lớp B-queued by the gateway).
    {"type": "email_send", "to": "lead@team.com", "subject": "Daily", "body": "3 done"},
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


# --- email attachment confinement (Lớp A): the artifact-dir red line ---


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    return root


def _xlsx(root: Path, name: str = "resource-2026-07-10.xlsx") -> Path:
    p = root / name
    p.write_bytes(b"PK\x03\x04")
    return p


def test_attachment_absent_is_allowed(tmp_path):
    assert _attachment_verdict(None, _root(tmp_path)) is None


def test_attachment_inside_dir_is_allowed(tmp_path):
    root = _root(tmp_path)
    assert _attachment_verdict(str(_xlsx(root)), root) is None


def test_attachment_traversal_denied(tmp_path):
    root = _root(tmp_path)
    (tmp_path / "secret.xlsx").write_bytes(b"PK")
    v = _attachment_verdict(str(root / ".." / "secret.xlsx"), root)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_absolute_elsewhere_denied(tmp_path):
    v = _attachment_verdict("/etc/passwd", _root(tmp_path))
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_symlink_escape_denied(tmp_path):
    """An in-dir symlink pointing OUT must be denied — resolve() follows the link.

    This guards the subtlest bypass: if a refactor swapped resolve() for a
    non-dereferencing call, this file would carry an out-of-dir target while
    looking in-dir. resolve() + is_relative_to keeps it closed.
    """
    root = _root(tmp_path)
    outside = tmp_path / "secret.xlsx"
    outside.write_bytes(b"PK")
    link = root / "evil.xlsx"
    os.symlink(outside, link)
    v = _attachment_verdict(str(link), root)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_missing_file_denied(tmp_path):
    root = _root(tmp_path)
    v = _attachment_verdict(str(root / "never-written.xlsx"), root)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_non_xlsx_denied(tmp_path):
    root = _root(tmp_path)
    (root / "report.txt").write_bytes(b"x")
    v = _attachment_verdict(str(root / "report.txt"), root)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_dir_with_xlsx_suffix_denied(tmp_path):
    root = _root(tmp_path)
    (root / "fake.xlsx").mkdir()  # a directory, not a file
    v = _attachment_verdict(str(root / "fake.xlsx"), root)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_fail_closed_without_root(tmp_path):
    v = _attachment_verdict(str(_xlsx(_root(tmp_path))), None)
    assert v and v.category == BlockCategory.SECURITY


def test_attachment_empty_path_denied(tmp_path):
    v = _attachment_verdict("   ", _root(tmp_path))
    assert v and v.category == BlockCategory.SECURITY
