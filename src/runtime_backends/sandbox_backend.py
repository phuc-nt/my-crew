"""Sandbox backends for the deep-agent runtime (v20.5 Phase 2).

The deep-agent runtime lets the LLM run shell freely — but ONLY inside an isolated sandbox, so
a hostile/injected command cannot read the CEO's tokens or delete real data. Two providers, on
a positive allowlist (red-team C3 — never `local`/`localshell`, which run host shell with
`.env`/SSH access):

- **fake** — test-only. Runs `execute` in a throwaday temp dir with a SCRUBBED env (proves the
  wiring + env boundary logic), NO OS isolation. Never a production backend.
- **docker** — self-hosted local container. `execute` runs inside `docker run` with NO tokens
  in its env, NO mount of the host home/.env, and the workdir isolated. No third-party service,
  no data egress to a provider. Requires Docker (Desktop/colima) on the host.

deepagents' `BaseSandbox` needs only 4 sync abstracts implemented (`id`, `execute`,
`download_files`, `upload_files`); the async filesystem methods derive from them. We keep files
in-sandbox (download/upload minimal) — the deep-agent's job is to produce a text result that
goes back through `deliver → external_write → gateway` (Phase 0), not to write host files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class SandboxDenied(RuntimeError):
    """A sandbox backend was refused (bad provider, or Docker unavailable)."""


#: Env var NAMES that must NEVER reach a sandbox (tokens/secrets). The container gets only a
#: minimal PATH-like env; this list is the explicit deny set the token-free test asserts against.
_TOKEN_ENV_NAMES = frozenset({
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ATLASSIAN_API_TOKEN",
    "SLACK_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "SMTP_PASSWORD", "TAVILY_API_KEY",
    "BRAVE_API_KEY", "LANGSMITH_API_KEY", "GITHUB_TOKEN", "E2B_API_KEY",
})


def _scrubbed_sandbox_env() -> dict[str, str]:
    """The ONLY env a sandbox receives — a minimal PATH, no tokens (red-team C2/H1).

    Env-scrub happens HERE (at the backend), not via a host-subprocess helper: deepagents'
    `execute` has no env parameter, so the boundary is the provider subclass's own provisioning.
    """
    return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


def build_sandbox_backend(cfg: dict | None):
    """Resolve a deep-agent sandbox backend from `RuntimeCaps.sandbox`, or fail-closed.

    Positive allowlist (red-team C3): only `fake`/`docker`. A None cfg, a `local`/unknown
    provider, or an unavailable Docker daemon all raise `SandboxDenied` — the deep-agent runtime
    then refuses to run (never degrades to host shell).
    """
    if not cfg or not cfg.get("provider"):
        raise SandboxDenied(
            "deep_agent cần sandbox config (provider) — fail-closed, không host shell."
        )
    provider = str(cfg["provider"]).strip()
    if provider == "fake":
        return FakeSandboxBackend()
    if provider == "docker":
        return DockerSandboxBackend(image=cfg.get("image", "python:3.12-slim"))
    raise SandboxDenied(
        f"sandbox provider {provider!r} không được phép (chỉ fake|docker; "
        f"local/localshell/unknown bị từ chối để không đọc .env host)."
    )


def _base_sandbox_cls():
    """deepagents BaseSandbox — imported lazily (optional dep)."""
    from deepagents.backends.sandbox import BaseSandbox

    return BaseSandbox


def _make_fake():
    BaseSandbox = _base_sandbox_cls()
    from deepagents.backends.protocol import ExecuteResponse

    class _Fake(BaseSandbox):
        """Test-only backend: temp-dir shell, scrubbed env, NO OS isolation."""

        def __init__(self):
            self._dir = tempfile.mkdtemp(prefix="mycrew-fake-sandbox-")
            self._env_seen: dict[str, str] = {}

        @property
        def id(self) -> str:
            return f"fake:{os.path.basename(self._dir)}"

        def execute(self, command: str, *, timeout: int | None = None) -> Any:
            env = _scrubbed_sandbox_env()
            self._env_seen = dict(env)  # recorded for the token-free test
            try:
                proc = subprocess.run(
                    command, shell=True, cwd=self._dir, env=env, capture_output=True,
                    text=True, timeout=timeout or 30,
                )
                return ExecuteResponse(output=proc.stdout + proc.stderr, exit_code=proc.returncode)
            except subprocess.TimeoutExpired:
                return ExecuteResponse(output="(timeout)", exit_code=124)

        def download_files(self, paths: list[str]) -> list:
            return []

        def upload_files(self, files: list[tuple[str, bytes]]) -> list:
            return []

        def teardown(self) -> None:
            shutil.rmtree(self._dir, ignore_errors=True)

    return _Fake


def _make_docker():
    BaseSandbox = _base_sandbox_cls()
    from deepagents.backends.protocol import ExecuteResponse

    class _Docker(BaseSandbox):
        """Self-hosted Docker sandbox: shell runs in a container, no tokens, no host mount."""

        def __init__(self, image: str):
            import docker  # optional dep

            self._image = image
            self._client = docker.from_env()  # raises if Docker daemon unavailable
            # A long-lived container per step; torn down by the teardown reaper (Phase 3).
            self._container = self._client.containers.run(
                image, command="sleep 3600", detach=True, network_disabled=False,
                environment=_scrubbed_sandbox_env(),  # NO tokens (red-team C2/H1)
                # No host mount: the container cannot read the CEO's .env / SSH keys (C3).
                working_dir="/work", tty=False,
            )

        @property
        def id(self) -> str:
            return f"docker:{self._container.short_id}"

        def execute(self, command: str, *, timeout: int | None = None) -> Any:
            # exec inside the container; env already scrubbed at container creation.
            res = self._container.exec_run(["sh", "-c", command], workdir="/work", demux=False)
            out = res.output.decode("utf-8", errors="replace") if res.output else ""
            return ExecuteResponse(output=out, exit_code=res.exit_code)

        def download_files(self, paths: list[str]) -> list:
            return []

        def upload_files(self, files: list[tuple[str, bytes]]) -> list:
            return []

        def teardown(self) -> None:
            try:
                self._container.remove(force=True)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass

    return _Docker


def FakeSandboxBackend():  # noqa: N802 — factory reads as a class to callers
    """Construct the fake (test) sandbox backend."""
    return _make_fake()()


def DockerSandboxBackend(image: str = "python:3.12-slim"):  # noqa: N802
    """Construct the Docker (self-hosted) sandbox backend. Raises if Docker is unavailable."""
    try:
        return _make_docker()(image)
    except Exception as exc:  # noqa: BLE001 — Docker daemon missing / unreachable
        raise SandboxDenied(
            f"Docker sandbox không khả dụng ({exc}). Cài + chạy Docker (Desktop/colima) hoặc "
            f"dùng agent_runtime khác."
        ) from exc


def assert_not_host_shell(backend: Any) -> None:
    """Guard: the backend must not be a host-shell backend (red-team C3).

    deepagents' LocalShellBackend/FilesystemBackend-with-host-exec read the host filesystem;
    our allowlist never builds them, but assert defensively so a future path cannot slip one in.
    """
    name = type(backend).__name__
    if "LocalShell" in name or name == "FilesystemBackend":
        raise SandboxDenied(f"backend {name!r} chạy shell trên host — không được cho deep_agent.")
