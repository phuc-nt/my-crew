"""M3-P12 S3 (D3): mpm agent automate — parse + run, propose enqueues, --dry-run no-op."""

from __future__ import annotations

import pytest

from src.actions.action_gateway import ActionGateway
from src.audit.audit_log import AuditLog
from src.config.config_builders import build_settings_from_dict
from src.entrypoints import mpm_automate_cmd
from src.runtime.registry import RegistryEntry

_GOOD_YAML = """\
name: blocker-note
steps:
  - read: jira.issues
    args: {}
    as: issues
  - analyze: summarize_blockers
    using: [issues]
    as: note
  - propose: slack.post
    args: {channel: stakeholders, text: "{{note}}"}
"""

_BAD_YAML = """\
name: bad
steps:
  - read: evil.exec
    as: x
"""


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Registry + profile + injected gateway/read-tools/analyze so the cmd runs offline."""
    monkeypatch.setattr(
        mpm_automate_cmd, "load_registry", lambda: (RegistryEntry("acme", True),)
    )

    class _Loaded:
        settings = build_settings_from_dict(
            {"dry_run": False, "trust_mode": "guarded", "data_dir": str(tmp_path)}
        )

        class config:  # noqa: N801 — minimal stand-in
            slack_external_channels = frozenset({"stakeholders"})

    monkeypatch.setattr(mpm_automate_cmd, "_load_agent", lambda aid: _Loaded())

    gw = ActionGateway(
        _Loaded.settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        external_channels=frozenset({"stakeholders"}),
    )
    reads = {"jira.issues": lambda args: [{"key": "SCRUM-1"}]}
    analyze = lambda p, v: "Blocker: SCRUM-1"  # noqa: E731
    return gw, reads, analyze


def _write(tmp_path, content):
    p = tmp_path / "wf.yaml"
    p.write_text(content)
    return str(p)


def test_automate_propose_enqueues(wired, tmp_path, capsys):
    gw, reads, analyze = wired
    path = _write(tmp_path, _GOOD_YAML)
    rc = mpm_automate_cmd.run_automate(
        ["acme", path], gateway=gw, read_tools=reads, analyze_fn=analyze
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "pending_approval" in out
    assert "executed" not in out  # NEVER auto-executes
    assert len(gw.pending_approvals()) == 1


def test_automate_dry_run_no_enqueue(wired, tmp_path, capsys):
    gw, reads, analyze = wired
    path = _write(tmp_path, _GOOD_YAML)
    rc = mpm_automate_cmd.run_automate(
        ["acme", path, "--dry-run"], gateway=gw, read_tools=reads, analyze_fn=analyze
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out and "would enqueue" in out
    assert gw.pending_approvals() == []  # nothing enqueued


def test_automate_unknown_agent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        mpm_automate_cmd, "load_registry", lambda: (RegistryEntry("acme", True),)
    )
    path = _write(tmp_path, _GOOD_YAML)
    rc = mpm_automate_cmd.run_automate(["ghost", path])
    assert rc == 1
    assert "unknown agent" in capsys.readouterr().err


def test_automate_bad_yaml_validation_error(wired, tmp_path, capsys):
    gw, reads, analyze = wired
    path = _write(tmp_path, _BAD_YAML)
    rc = mpm_automate_cmd.run_automate(
        ["acme", path], gateway=gw, read_tools=reads, analyze_fn=analyze
    )
    assert rc == 1
    assert "invalid automation.yaml" in capsys.readouterr().err


def test_automate_missing_file(wired, capsys):
    gw, reads, analyze = wired
    rc = mpm_automate_cmd.run_automate(
        ["acme", "/no/such/wf.yaml"], gateway=gw, read_tools=reads, analyze_fn=analyze
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_automate_bad_invocation(capsys):
    rc = mpm_automate_cmd.run_automate(["acme"])  # missing yaml path
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_automate_dispatch_via_mpm(monkeypatch):
    from src.entrypoints import mpm

    called = {}

    def _fake(rest, **k):
        called["rest"] = rest
        return 0

    monkeypatch.setattr("src.entrypoints.mpm_automate_cmd.run_automate", _fake)
    rc = mpm.main(["agent", "automate", "acme", "wf.yaml", "--dry-run"])
    assert rc == 0
    assert called["rest"] == ["acme", "wf.yaml", "--dry-run"]


def test_real_analyze_fn_reads_llm_result_content(monkeypatch):
    """Regression: the real analyze_fn must read LlmResult.content (NOT .text).

    Live E2E caught `_analyze` accessing a non-existent `.text`; the fake `analyze_fn` in
    other tests hid it. This exercises the real `_build_analyze_fn` against a fake LlmClient
    whose `.complete()` returns a real `LlmResult` shape.
    """
    from src.llm.client import LlmResult

    class _FakeClient:
        def __init__(self, settings):
            pass

        def complete(self, messages, *, model=None):
            return LlmResult(
                content="summary OK", model="x", prompt_tokens=1,
                completion_tokens=1, cost_usd=0.0,
            )

    monkeypatch.setattr("src.llm.client.LlmClient", _FakeClient)
    analyze = mpm_automate_cmd._build_analyze_fn(settings=object())
    out = analyze("a prompt", {"issues": []})
    assert out == "summary OK"
