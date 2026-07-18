"""v20.5: Docker sandbox LIVE tests — shell runs in a real container, token-free, no host mount.

These exercise the actual Docker backend against a running daemon; they SKIP cleanly when Docker
is unavailable (CI without Docker, or a dev box with the daemon down). This is the isolation
proof the fake backend cannot give — a real container with a scrubbed env and no host filesystem.
"""

from __future__ import annotations

import importlib.util
import os
import shutil

import pytest

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    import subprocess

    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not (_HAS_DEEPAGENTS and _docker_available()),
    reason="needs deepagents + a running Docker daemon",
)


@pytest.fixture()
def docker_backend():
    from my_crew.runtime_backends.sandbox_backend import build_sandbox_backend

    be = build_sandbox_backend({"provider": "docker"})
    yield be
    be.teardown()


def test_shell_runs_in_a_linux_container(docker_backend):
    # The sandbox is a Linux container, not the host (macOS) — uname proves it.
    res = docker_backend.execute("uname -s")
    assert res.exit_code == 0
    assert "Linux" in res.output


def test_container_env_is_token_free(monkeypatch, docker_backend):
    # A token in the HOST env must NOT be visible inside the container (red-team C2/H1).
    monkeypatch.setenv("OPENROUTER_API_KEY", "FAKE-must-not-leak")
    res = docker_backend.execute("env | grep -i OPENROUTER || echo NONE")
    assert "OPENROUTER" not in res.output
    assert "NONE" in res.output


def test_container_cannot_read_host_env_file(docker_backend):
    # The container has no host mount, so the CEO's repo .env is unreachable (red-team C3).
    host_env = os.path.join(os.getcwd(), ".env")
    res = docker_backend.execute(f"cat {host_env} 2>&1 | head -1 || echo NO_ACCESS")
    assert "No such file" in res.output or "NO_ACCESS" in res.output


def test_multi_command_autonomy(docker_backend):
    # The agent can chain commands + write/read files inside the container workdir.
    res = docker_backend.execute(
        "python3 -c 'print(7*191)' && echo saved > /work/x.txt && cat /work/x.txt"
    )
    assert "1337" in res.output
    assert "saved" in res.output
