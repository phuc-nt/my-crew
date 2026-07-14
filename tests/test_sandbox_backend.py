"""v20.5 Phase 2: sandbox backend — fail-closed allowlist + token-free env + host-shell guard.

deepagents is an optional dep; these tests skip cleanly when it is not installed. The Docker
backend is not exercised here (needs a running daemon) — the fake backend proves the WIRING +
env-scrub boundary; real OS isolation is a Docker-provider E2E (Phase 5 / when Docker is up).
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None
pytestmark = pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")


def test_fail_closed_rejects_none_and_bad_providers():
    from src.runtime_backends.sandbox_backend import SandboxDenied, build_sandbox_backend

    for bad in (None, {}, {"provider": "local"}, {"provider": "localshell"},
                {"provider": "modal"}, {"provider": "e2b"}, {"provider": "unknown"}):
        with pytest.raises(SandboxDenied):
            build_sandbox_backend(bad)


def test_fake_backend_builds_and_runs():
    from src.runtime_backends.sandbox_backend import build_sandbox_backend

    fb = build_sandbox_backend({"provider": "fake"})
    assert fb.id.startswith("fake:")
    res = fb.execute("echo hello")
    assert res.exit_code == 0
    assert "hello" in res.output
    fb.teardown()


def test_fake_backend_env_is_token_free():
    from src.runtime_backends.sandbox_backend import (
        _TOKEN_ENV_NAMES,
        build_sandbox_backend,
    )

    fb = build_sandbox_backend({"provider": "fake"})
    # dump the sandbox env; assert NO secret env name is present (red-team C2/H1).
    res = fb.execute("env")
    for token in _TOKEN_ENV_NAMES:
        assert token not in res.output, f"{token} leaked into sandbox env"
    fb.teardown()


def test_assert_not_host_shell_blocks_localshell():
    from deepagents.backends import LocalShellBackend

    from src.runtime_backends.sandbox_backend import SandboxDenied, assert_not_host_shell

    with pytest.raises(SandboxDenied, match="host"):
        assert_not_host_shell(LocalShellBackend(virtual_mode=False))


def test_docker_unavailable_fails_closed(monkeypatch):
    # If Docker is not running, the docker provider raises SandboxDenied (never host shell).
    from src.runtime_backends import sandbox_backend as sb

    def _boom(image, network=False):
        raise RuntimeError("Cannot connect to the Docker daemon")

    monkeypatch.setattr(sb, "_make_docker", lambda: _boom)
    with pytest.raises(sb.SandboxDenied, match="Docker sandbox không khả dụng"):
        sb.DockerSandboxBackend()


# --- Docker container hardening (injected fake client; no real daemon) -----------------


class _FakeContainer:
    short_id = "deadbeef"

    def remove(self, force=False):
        pass


class _FakeDockerClient:
    """Captures the kwargs of each containers.run call; optionally raises to test degrade."""

    def __init__(self, *, raise_on=None):
        # raise_on: a set of kwarg keys whose PRESENCE triggers an APIError (simulating a daemon
        # that rejects those kwargs). None ⇒ never raise.
        self._raise_on = raise_on or set()
        self.runs: list[dict] = []

        class _Containers:
            def __init__(self, outer):
                self._outer = outer

            def run(self, image, **kwargs):
                self._outer.runs.append(kwargs)
                import docker
                if self._outer._raise_on & set(kwargs):
                    raise docker.errors.APIError("daemon rejects a kwarg")
                return _FakeContainer()

        self.containers = _Containers(self)


def _patch_docker(monkeypatch, client):
    """Make `import docker` inside sandbox_backend yield a module whose from_env returns `client`
    and whose errors.APIError is a real exception class."""
    import sys
    import types

    fake = types.ModuleType("docker")
    fake.from_env = lambda *a, **k: client
    errors = types.ModuleType("docker.errors")

    class APIError(Exception):
        pass

    errors.APIError = APIError
    fake.errors = errors
    monkeypatch.setitem(sys.modules, "docker", fake)
    monkeypatch.setitem(sys.modules, "docker.errors", errors)


def test_docker_network_off_by_default(monkeypatch):
    from src.runtime_backends import sandbox_backend as sb

    client = _FakeDockerClient()
    _patch_docker(monkeypatch, client)
    sb.build_sandbox_backend({"provider": "docker"})
    assert client.runs[-1]["network_disabled"] is True  # off unless opted in


def test_docker_network_opt_in(monkeypatch):
    from src.runtime_backends import sandbox_backend as sb

    client = _FakeDockerClient()
    _patch_docker(monkeypatch, client)
    sb.build_sandbox_backend({"provider": "docker", "network": True})
    assert client.runs[-1]["network_disabled"] is False  # opt-in flips it on


def test_docker_execute_degrades_on_transient_exec_error(monkeypatch):
    """v43: a Docker exec error (e.g. 404 when the container was concurrently removed while
    parallel subagent execs race it) must degrade to a non-zero ExecuteResponse, NOT raise and
    abort the whole run — mirrors upload/download per-call guards."""
    from src.runtime_backends import sandbox_backend as sb

    class _BoomContainer(_FakeContainer):
        def exec_run(self, *a, **k):
            raise RuntimeError("404 Client Error: No such container")

    client = _FakeDockerClient()
    # swap the container the run() returns for one whose exec_run raises
    client.containers.run = lambda image, **kw: _BoomContainer()  # type: ignore[assignment]
    _patch_docker(monkeypatch, client)

    backend = sb.build_sandbox_backend({"provider": "docker"})
    res = backend.execute("ls /work")
    assert res.exit_code == 1
    assert "sandbox exec error" in res.output  # degraded, not raised


def test_docker_hardening_kwargs_present(monkeypatch):
    from src.runtime_backends import sandbox_backend as sb

    client = _FakeDockerClient()
    _patch_docker(monkeypatch, client)
    sb.build_sandbox_backend({"provider": "docker"})
    run = client.runs[-1]
    assert run["cap_drop"] == ["ALL"]
    assert run["user"] == "nobody"
    assert run["security_opt"] == ["no-new-privileges"]
    assert run["mem_limit"] == "512m" and run["pids_limit"] == 256
    assert run["read_only"] is True
    # tmpfs is world-writable (1777) so the non-root `nobody` can write its workdir/home.
    assert run["tmpfs"] == {"/tmp": "rw,mode=1777", "/work": "rw,mode=1777"}
    # v41: lease is configurable (default 1800s) — was a hard 600 that killed slow deep_agent runs.
    from src.runtime_backends.sandbox_backend import SANDBOX_LEASE_S

    assert run["command"] == f"sleep {SANDBOX_LEASE_S}"
    # HOME is on the container env only; token-free preserved.
    assert run["environment"]["HOME"] == "/work"


def test_docker_shared_scrubbed_env_has_no_home(monkeypatch):
    # M4: the shared helper (used by the fake backend's host subprocess) must NOT gain HOME.
    from src.runtime_backends.sandbox_backend import _scrubbed_sandbox_env

    assert "HOME" not in _scrubbed_sandbox_env()


def test_docker_degrade_keeps_privilege_and_network(monkeypatch):
    # A daemon that rejects a resource/fs kwarg (pids_limit) → retry drops ONLY resource/fs;
    # privilege + network survive.
    from src.runtime_backends import sandbox_backend as sb

    client = _FakeDockerClient(raise_on={"pids_limit"})
    _patch_docker(monkeypatch, client)
    sb.build_sandbox_backend({"provider": "docker"})
    assert len(client.runs) == 2  # full attempt failed, base-only retry succeeded
    retry = client.runs[-1]
    assert "pids_limit" not in retry and "mem_limit" not in retry  # resource/fs dropped
    assert retry["cap_drop"] == ["ALL"]  # privilege survives
    assert retry["security_opt"] == ["no-new-privileges"]
    assert retry["user"] == "nobody"
    assert retry["network_disabled"] is True  # network survives


def test_docker_hard_kwarg_rejection_fails_closed(monkeypatch):
    # A daemon that rejects a HARD privilege kwarg (cap_drop) → both attempts fail → SandboxDenied
    # (never a privileged container).
    from src.runtime_backends import sandbox_backend as sb

    client = _FakeDockerClient(raise_on={"cap_drop"})
    _patch_docker(monkeypatch, client)
    with pytest.raises(sb.SandboxDenied, match="guardrail bắt buộc"):
        sb.build_sandbox_backend({"provider": "docker"})
