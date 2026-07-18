"""v41 P1: configurable sandbox lease — deep_agent no longer dies at the hard 600s.

deep_agent + a slow model runs 565-612s; the old container `sleep 600` + auto_remove
killed it mid-run (→ 404 on the next exec, 2/4 benchmark runs dead). The lease is now a
constant (default 1800, cap 3600), configurable per agent, and the reaper's orphan
threshold is the MAX of the step lease and the sandbox lease so a valid long run is never
reaped mid-exec.
"""

from __future__ import annotations

import pytest

from my_crew.runtime_backends.sandbox_backend import (
    SANDBOX_LEASE_MAX_S,
    SANDBOX_LEASE_S,
    _clamp_lease,
)


def test_default_lease_is_1800():
    assert SANDBOX_LEASE_S == 1800
    assert SANDBOX_LEASE_MAX_S == 3600


@pytest.mark.parametrize("given,expected", [
    (None, 1800),      # default
    (900, 900),        # honoured
    (5000, 3600),      # clamped to max
    (10, 60),          # clamped to min
    (1800, 1800),
])
def test_clamp_lease(given, expected):
    assert _clamp_lease(given) == expected


def test_reaper_threshold_is_max_of_step_and_sandbox_lease():
    from my_crew.runtime.team_task_store import DEFAULT_LEASE_TTL_S
    from my_crew.runtime_backends.sandbox_reaper import _default_ttl_s

    # A container living >step-lease (600) but within its sandbox lease (1800) must not be
    # reapable — the threshold takes the longer of the two.
    assert _default_ttl_s() == max(DEFAULT_LEASE_TTL_S, SANDBOX_LEASE_S)
    assert _default_ttl_s() >= SANDBOX_LEASE_S  # ≥ 1800, so a 660s container is safe


def test_reaper_does_not_reap_valid_long_container(monkeypatch):
    """A still-running container aged 700s (past the 600 step-lease, within the 1800 sandbox
    lease) is NOT reaped — the bug was reaping it at ~780s."""
    from datetime import UTC, datetime, timedelta

    from my_crew.runtime_backends import sandbox_reaper

    now = datetime.now(UTC)

    class _Container:
        def __init__(self, age_s):
            self.attrs = {"Created": (now - timedelta(seconds=age_s)).isoformat()}
            self.removed = False

        def remove(self, **kw):
            self.removed = True

    young = _Container(700)   # within sandbox lease → keep
    old = _Container(2000)    # past sandbox lease + grace → reap

    class _Client:
        def __init__(self):
            self.containers = self

        def list(self, **kw):
            return [young, old]

    reaped = sandbox_reaper.reap_orphaned_sandboxes(client=_Client())
    assert young.removed is False   # valid long run untouched (the fix)
    assert old.removed is True      # genuine orphan still reaped
    assert reaped == 1


def test_docker_backend_sleep_uses_lease(monkeypatch):
    """The container command carries the configured lease, not a hard 600."""
    import importlib.util

    if importlib.util.find_spec("docker") is None:
        pytest.skip("docker sdk not installed")

    from my_crew.runtime_backends import sandbox_backend

    captured = {}

    class _FakeContainer:
        short_id = "abc123"

    class _FakeContainers:
        def run(self, image, **kw):
            captured.update(kw)
            return _FakeContainer()

    class _FakeDocker:
        def __init__(self):
            self.containers = _FakeContainers()

    monkeypatch.setattr("docker.from_env", lambda *a, **k: _FakeDocker())
    sb = sandbox_backend.build_sandbox_backend(
        {"provider": "docker", "network": False, "lease_seconds": 1200})
    assert captured["command"] == "sleep 1200"
    sb.teardown()
