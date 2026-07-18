"""Slice 2: mpm agent run — spawn the worker (injected fake spawn, no real process)."""

from __future__ import annotations

import subprocess
import sys

from my_crew.entrypoints import mpm_run_cmd
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
    """Make load_registry (as seen by mpm_run_cmd) report the given agent ids."""
    monkeypatch.setattr(
        mpm_run_cmd, "load_registry",
        lambda: tuple(RegistryEntry(i, True) for i in ids),
    )


def _patch_detail(monkeypatch, detail):
    """Stub _supervise's run-event read so the printed outcome is deterministic."""
    monkeypatch.setattr("my_crew.runtime.service._last_run_event", lambda agent_id: detail)


def test_happy_exact_argv_and_exit_0(monkeypatch, capsys):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {"kind": "daily", "status": "delivered",
                                "delivered": True, "cost_usd": 0.001})
    record = []
    rc = mpm_run_cmd.run_agent(["acme", "--report", "daily"], spawn=_fake_spawn(record))
    assert rc == 0
    assert record[0] == [
        sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", "acme", "--report", "daily", "--audience", "internal",
    ]
    assert "delivered=True" in capsys.readouterr().out


def test_audience_external_in_argv(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {})
    record = []
    mpm_run_cmd.run_agent(
        ["acme", "--report", "okr", "--audience", "external"], spawn=_fake_spawn(record)
    )
    assert record[0][-4:] == ["--report", "okr", "--audience", "external"]


def test_dry_run_passthrough(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {})
    record = []
    mpm_run_cmd.run_agent(["acme", "--dry-run"], spawn=_fake_spawn(record))
    assert "--dry-run" in record[0]


def test_worker_nonzero_exit_1(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {"status": "not_delivered", "delivered": False})
    rc = mpm_run_cmd.run_agent(["acme", "--report", "daily"],
                              spawn=_fake_spawn([], exit_code=1))
    assert rc == 1


def test_timeout_exit_1_and_killed(monkeypatch, capsys):
    _patch_known(monkeypatch)
    record_procs = []

    def _spawn(argv):
        p = _FakeProc(hang=True)
        record_procs.append(p)
        return p

    rc = mpm_run_cmd.run_agent(["acme", "--report", "daily"], spawn=_spawn, timeout=1)
    assert rc == 1
    assert record_procs[0].killed is True
    assert "TIMEOUT" in capsys.readouterr().out


def test_unknown_agent_no_spawn(monkeypatch, capsys):
    _patch_known(monkeypatch, ids=("acme",))
    record = []
    rc = mpm_run_cmd.run_agent(["ghost", "--report", "daily"], spawn=_fake_spawn(record))
    assert rc == 1
    assert record == []  # never spawned
    assert "unknown agent" in capsys.readouterr().err


def test_bad_kind_exit_2_no_spawn(monkeypatch, capsys):
    _patch_known(monkeypatch)
    record = []
    rc = mpm_run_cmd.run_agent(["acme", "--report", "bogus"], spawn=_fake_spawn(record))
    assert rc == 2 and record == []
    assert "--report must be one of" in capsys.readouterr().err


def test_missing_id_exit_2_no_spawn(capsys):
    record = []
    rc = mpm_run_cmd.run_agent([], spawn=_fake_spawn(record))
    assert rc == 2 and record == []
    assert "usage:" in capsys.readouterr().err


def test_team_step_requires_the_full_task_step_attempt_triple(monkeypatch, capsys):
    _patch_known(monkeypatch)
    record = []
    rc = mpm_run_cmd.run_agent(
        ["acme", "--report", "team-step", "--task-id", "t1"], spawn=_fake_spawn(record)
    )
    assert rc == 2 and record == []
    err = capsys.readouterr().err
    assert "--report team-step requires --task-id --step-id --attempt-id" in err


def test_team_step_missing_all_three_flags_exit_2_no_spawn(monkeypatch, capsys):
    _patch_known(monkeypatch)
    record = []
    rc = mpm_run_cmd.run_agent(["acme", "--report", "team-step"], spawn=_fake_spawn(record))
    assert rc == 2 and record == []
    assert "requires --task-id --step-id --attempt-id" in capsys.readouterr().err


def test_team_step_happy_path_appends_the_triple_to_argv(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {"status": "delivered", "delivered": True, "cost_usd": 0.002})
    record = []
    rc = mpm_run_cmd.run_agent(
        [
            "acme", "--report", "team-step",
            "--task-id", "t1", "--step-id", "s2", "--attempt-id", "a3",
        ],
        spawn=_fake_spawn(record),
    )
    assert rc == 0
    assert record[0] == [
        sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", "acme", "--report", "team-step", "--audience", "internal",
        "--task-id", "t1", "--step-id", "s2", "--attempt-id", "a3",
    ]


def test_team_step_unknown_agent_still_rejected_before_spawn(monkeypatch, capsys):
    _patch_known(monkeypatch, ids=("acme",))
    record = []
    rc = mpm_run_cmd.run_agent(
        [
            "ghost", "--report", "team-step",
            "--task-id", "t1", "--step-id", "s2", "--attempt-id", "a3",
        ],
        spawn=_fake_spawn(record),
    )
    assert rc == 1
    assert record == []
    assert "unknown agent" in capsys.readouterr().err


def test_team_tick_is_a_valid_kind_with_no_triple_required(monkeypatch):
    _patch_known(monkeypatch)
    _patch_detail(monkeypatch, {})
    record = []
    rc = mpm_run_cmd.run_agent(["acme", "--report", "team-tick"], spawn=_fake_spawn(record))
    assert rc == 0
    assert record[0][-4:] == ["--report", "team-tick", "--audience", "internal"]
