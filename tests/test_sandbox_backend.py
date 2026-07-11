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

    def _boom(image):
        raise RuntimeError("Cannot connect to the Docker daemon")

    monkeypatch.setattr(sb, "_make_docker", lambda: _boom)
    with pytest.raises(sb.SandboxDenied, match="Docker sandbox không khả dụng"):
        sb.DockerSandboxBackend()
