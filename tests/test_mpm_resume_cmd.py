"""M2-P5 Slice 3: mpm agent resume — spawn worker --resume (injected fake spawn)."""

from __future__ import annotations

import subprocess
import sys

from my_crew.entrypoints import mpm, mpm_resume_cmd
from my_crew.runtime.registry import RegistryEntry


class _FakeProc:
    def __init__(self, exit_code=0, hang=False):
        self._exit_code = exit_code
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
        return self._exit_code

    def kill(self):
        self.killed = True


def _fake_spawn(record, *, exit_code=0, hang=False):
    def _spawn(argv):
        record.append(argv)
        return _FakeProc(exit_code=exit_code, hang=hang)

    return _spawn


def _patch_known(monkeypatch, ids=("acme",)):
    monkeypatch.setattr(
        mpm_resume_cmd, "load_registry",
        lambda: tuple(RegistryEntry(i, True) for i in ids),
    )


def _patch_detail(monkeypatch, detail):
    monkeypatch.setattr("my_crew.runtime.service._last_run_event", lambda agent_id: detail)


def test_resume_approve_exact_argv_exit_0(monkeypatch, capsys):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {"status": "delivered", "delivered": True})
    record = []
    rc = mpm_resume_cmd.run_resume(
        ["acme", "acme:daily:external", "--decision", "approve"], spawn=_fake_spawn(record)
    )
    assert rc == 0
    assert record[0] == [
        sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", "acme", "--resume",
        "--thread", "acme:daily:external", "--decision", "approve",
    ]
    assert "delivered=True" in capsys.readouterr().out


def test_resume_reject_worker_exit_1(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {"status": "rejected", "delivered": False})
    rc = mpm_resume_cmd.run_resume(
        ["acme", "acme:okr:external", "--decision", "reject"],
        spawn=_fake_spawn([], exit_code=1),
    )
    assert rc == 1


def test_resume_bad_decision_no_spawn_exit_2(monkeypatch, capsys):
    _patch_known(monkeypatch)
    record = []
    rc = mpm_resume_cmd.run_resume(
        ["acme", "acme:daily:external", "--decision", "maybe"], spawn=_fake_spawn(record)
    )
    assert rc == 2
    assert record == []  # never spawned


def test_resume_unknown_agent_no_spawn(monkeypatch, capsys):
    _patch_known(monkeypatch, ids=("acme",))
    record = []
    rc = mpm_resume_cmd.run_resume(
        ["ghost", "ghost:daily:external", "--decision", "approve"], spawn=_fake_spawn(record)
    )
    assert rc == 1
    assert record == []


def test_resume_missing_args_exit_2(capsys):
    rc = mpm_resume_cmd.run_resume(["acme"])
    assert rc == 2


def test_mpm_dispatch_routes_resume(monkeypatch):
    # `mpm agent resume ...` reaches run_resume.
    called = {}

    def _fake(rest, **k):
        called["rest"] = rest
        return 0

    monkeypatch.setattr("my_crew.entrypoints.mpm_resume_cmd.run_resume", _fake)
    rc = mpm.main(["agent", "resume", "acme", "acme:daily:external", "--decision", "approve"])
    assert rc == 0
    assert called["rest"] == ["acme", "acme:daily:external", "--decision", "approve"]
