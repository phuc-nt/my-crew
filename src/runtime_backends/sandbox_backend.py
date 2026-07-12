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

import logging
import os
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

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
        # Network is OFF by default; only an explicit opt-in in the sandbox config turns it on.
        # A deep_agent's shell has no legitimate need for the internet (research scraping goes
        # through the read-only tool-calling engine), so an open network is pure exfil surface.
        network = bool(cfg.get("network"))
        return DockerSandboxBackend(image=cfg.get("image", "python:3.12-slim"), network=network)
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
        """Self-hosted Docker sandbox: shell runs in a hardened container, no tokens, no host mount.

        Isolation is layered. Two of those layers are NON-NEGOTIABLE and never dropped:
        - **network** is off unless the agent explicitly opted in — an open network is exfil.
        - **privilege** (`cap_drop=ALL`, `no-new-privileges`, non-root `nobody`) blocks container
          escape; network-off does not substitute for it (an escaped root reaches the host
          regardless of its network namespace).
        Resource/filesystem limits (`mem_limit`/`pids_limit`/`read_only`/`tmpfs`) are best-effort:
        some Docker daemons (notably Docker Desktop on macOS) reject them, so they degrade with a
        loud warning. But if the daemon rejects a privilege/network kwarg, we FAIL CLOSED rather
        than run an unsafe container.
        """

        def __init__(self, image: str, network: bool = False):
            import docker  # optional dep

            self._image = image
            self._client = docker.from_env()  # raises if Docker daemon unavailable
            # HOME is set on the container's OWN env only (not the shared scrubbed-env helper,
            # which the fake backend runs as a host subprocess): a non-root read-only container
            # needs a writable HOME (=/work, a tmpfs) for pip/tools; the host must not get it.
            container_env = {**_scrubbed_sandbox_env(), "HOME": "/work"}
            # HARD group — present in every run attempt, never dropped. No host mount (C3).
            # `sleep 600` + auto_remove: the container self-terminates within the lease window and
            # Docker removes it, so a self-exited/normally-exited container needs no reaper. The
            # label lets the reaper find a STILL-RUNNING orphan (SIGKILL'd worker) by our own tag.
            from src.runtime_backends.sandbox_reaper import SANDBOX_LABEL, SANDBOX_LABEL_VALUE
            base_kwargs = {
                "command": "sleep 600", "detach": True, "network_disabled": not network,
                "environment": container_env, "working_dir": "/work", "tty": False,
                "cap_drop": ["ALL"], "user": "nobody", "security_opt": ["no-new-privileges"],
                "labels": {SANDBOX_LABEL: SANDBOX_LABEL_VALUE}, "auto_remove": True,
            }
            # DEGRADABLE group — resource/filesystem limits that some daemons reject.
            # tmpfs mounts are world-writable (mode 1777, like /tmp): the container runs as the
            # non-root `nobody`, and a default-root-owned tmpfs would deny it writes to its own
            # workdir/home. 1777 (sticky, world-writable) lets `nobody` write while read_only keeps
            # the rest of the root filesystem immutable.
            degradable_kwargs = {
                "mem_limit": "512m", "pids_limit": 256, "read_only": True,
                "tmpfs": {"/tmp": "rw,mode=1777", "/work": "rw,mode=1777"},
            }
            self._container = self._run_hardened(base_kwargs, degradable_kwargs)

        def _run_hardened(self, base_kwargs: dict, degradable_kwargs: dict):
            """Start the container with full hardening; degrade ONLY the resource/fs limits.

            One retry: full set → (on daemon reject) base-only. The HARD group rides both attempts,
            so a resource/fs quirk never strips privilege or network isolation. A failure of the
            base attempt means a HARD kwarg was rejected → fail closed (never a privileged box).
            """
            import docker

            try:
                return self._client.containers.run(self._image, **base_kwargs, **degradable_kwargs)
            except (docker.errors.APIError, TypeError) as exc:
                logger.warning(
                    "sandbox resource/fs hardening degraded on this Docker daemon; dropped %s: %s",
                    sorted(degradable_kwargs), exc,
                )
                try:
                    return self._client.containers.run(self._image, **base_kwargs)
                except (docker.errors.APIError, TypeError) as exc2:
                    raise SandboxDenied(
                        "Docker daemon từ chối một guardrail bắt buộc (cap_drop/no-new-privileges"
                        f"/non-root/network) — fail-closed, không chạy container thiếu cách ly: "
                        f"{exc2}"
                    ) from exc2

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


def DockerSandboxBackend(image: str = "python:3.12-slim", network: bool = False):  # noqa: N802
    """Construct the Docker (self-hosted) sandbox backend. Raises if Docker is unavailable.

    `network` is off by default; the caller passes True only when the agent opted in via the
    sandbox config (and, in the deep_agent path, only when input sanitization succeeded).
    """
    try:
        return _make_docker()(image, network)
    except SandboxDenied:
        raise  # a rejected HARD guardrail already fails closed with a precise message
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
