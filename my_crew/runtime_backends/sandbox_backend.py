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

deepagents' `BaseSandbox` needs 4 sync abstracts (`id`, `execute`, `download_files`,
`upload_files`); the async filesystem methods derive from them. `upload_files`/`download_files`
back deepagents' `write_file`/`read_file` tools — they MUST return one response per input
(v40: a `[]` stub crashed the middleware's per-file assert whenever the agent wrote a file).
Files stay IN-SANDBOX, confined to `/work`: a path escaping `/work` (absolute-elsewhere, `..`,
symlink) is refused with an error-response, never written to the host. The deep-agent's final
result still goes back as TEXT through `deliver → external_write → gateway` (Phase 0); the
sandbox filesystem is scratch space for the agent's own read/write during a run.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

#: A safe in-sandbox filename: letters/digits/`._-` segments joined by `/`. Anything with a
#: shell metacharacter (`; $ ` | & ( ) < >` space …) is rejected — the docker backend
#: interpolates the path into a `sh -c` command, so this is the injection guard.
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$")

#: How long a deep-agent sandbox container lives before it self-terminates (`sleep N`).
#: v41: deep_agent + a slow model runs 565-612s — the old hard 600s auto-removed the
#: container mid-run (→ 404 on the next exec). 1800s (30 min) clears that with headroom;
#: a hard ceiling (SANDBOX_LEASE_MAX_S) stops a wedged run from holding a container forever.
#: The sandbox reaper's orphan threshold accounts for this so a valid long run is never
#: reaped (see sandbox_reaper._orphan_threshold_s).
SANDBOX_LEASE_S = 1800
SANDBOX_LEASE_MAX_S = 3600
_SANDBOX_LEASE_MIN_S = 60

#: The default sandbox container image. v47: named so the health/pre-pull tooling references the
#: same string the backend runs, instead of duplicating the literal.
SANDBOX_DEFAULT_IMAGE = "python:3.12-slim"


def _clamp_lease(seconds: int | None) -> int:
    """A configured lease clamped to [min, max]; None ⇒ the default."""
    if seconds is None:
        return SANDBOX_LEASE_S
    return max(_SANDBOX_LEASE_MIN_S, min(int(seconds), SANDBOX_LEASE_MAX_S))


#: Container memory ceiling (a Docker `mem_limit` string). Default keeps the resource-safety
#: posture — a runaway deep_agent shell can't exhaust host RAM. v44: configurable per-company so a
#: known-heavy research profile can opt UP (e.g. "1g"), but the default stays capped. Stays in the
#: DEGRADABLE kwargs group (dropped whole-set if the daemon rejects it — e.g. Docker Desktop/macoS).
SANDBOX_MEM_LIMIT = "512m"
_SANDBOX_MEM_MIN_BYTES = 256 * 1024 * 1024   # 256m floor — below this the interpreter starves
_SANDBOX_MEM_MAX_BYTES = 4 * 1024 * 1024 * 1024  # 4g ceiling — bound blast radius even when raised
_MEM_UNIT_BYTES = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _mem_to_bytes(value: str) -> int | None:
    """Parse a Docker mem string ("512m"/"1g"/"1073741824"/"512M") → bytes; None if unparseable."""
    s = str(value).strip().lower()
    if not s:
        return None
    unit = s[-1]
    try:
        if unit in _MEM_UNIT_BYTES:
            return int(float(s[:-1]) * _MEM_UNIT_BYTES[unit])
        return int(s)  # bare bytes
    except (TypeError, ValueError):
        return None


def _clamp_mem(value: str | None) -> str:
    """A configured mem_limit clamped to [min, max]; None/garbage ⇒ the default 512m.

    Returned as a Docker-friendly `<N>m` string (bytes rounded to whole MiB). Clamping bounds the
    OOM blast radius even when an operator sets a huge value, and keeps a typo from disabling the
    ceiling entirely (garbage ⇒ default, never unbounded)."""
    if value is None:
        return SANDBOX_MEM_LIMIT
    b = _mem_to_bytes(value)
    if b is None:
        return SANDBOX_MEM_LIMIT
    b = max(_SANDBOX_MEM_MIN_BYTES, min(b, _SANDBOX_MEM_MAX_BYTES))
    return f"{b // (1024 ** 2)}m"

#: The one directory in-sandbox files may live in. A path outside it is refused (never
#: written to the host) — the moat: the sandbox is scratch, not a host-write channel.
_SANDBOX_ROOT = "/work"
#: Cap on a single uploaded file (bytes) — a runaway write must not OOM the tar buffer.
_MAX_FILE_BYTES = 8 * 1024 * 1024


def _confined_rel(path: str) -> str | None:
    """Return the path relative to /work if it is safely inside it, else None.

    Accepts `/work/x`, `x`, `./sub/x`; refuses `/etc/x`, `../x`, or anything resolving
    outside /work. Purely lexical (PurePosixPath) — no filesystem access, so it is the
    same check for the fake and docker backends."""
    p = PurePosixPath(path)
    if p.is_absolute():
        try:
            rel = p.relative_to(_SANDBOX_ROOT)
        except ValueError:
            return None
    else:
        rel = p
    parts = rel.parts
    if any(part == ".." for part in parts) or not parts:
        return None
    result = str(PurePosixPath(*parts))
    # Reject shell-unsafe characters: the docker backend interpolates this into a
    # `sh -c` command, so a path like `a; rm -rf /` must never pass. Allow only a plain
    # filename charset (letters/digits/`._-/`) — deep-agent scratch files don't need more.
    if not _SAFE_PATH_RE.match(result):
        return None
    return result


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
        # v41: optional per-agent lease override; v44: optional mem_limit override (both clamped
        # to [min, max] in the backend; absent ⇒ the safe default).
        return DockerSandboxBackend(
            image=cfg.get("image", SANDBOX_DEFAULT_IMAGE), network=network,
            lease_s=cfg.get("lease_seconds"), mem_limit=cfg.get("mem_limit"),
        )
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
            from deepagents.backends.protocol import FileDownloadResponse

            out = []
            for path in paths:
                rel = _confined_rel(path)
                if rel is None:
                    out.append(FileDownloadResponse(path=path, content=None,
                                                    error="path_outside_work"))
                    continue
                target = os.path.join(self._dir, rel)
                try:
                    with open(target, "rb") as f:
                        out.append(FileDownloadResponse(path=path, content=f.read(), error=None))
                except OSError:
                    out.append(FileDownloadResponse(path=path, content=None,
                                                    error="file_not_found"))
            return out

        def upload_files(self, files: list[tuple[str, bytes]]) -> list:
            from deepagents.backends.protocol import FileUploadResponse

            out = []
            for path, data in files:
                rel = _confined_rel(path)
                if rel is None:
                    out.append(FileUploadResponse(path=path, error="path_outside_work"))
                    continue
                if len(data) > _MAX_FILE_BYTES:
                    out.append(FileUploadResponse(path=path, error="file_too_large"))
                    continue
                target = os.path.join(self._dir, rel)
                os.makedirs(os.path.dirname(target) or self._dir, exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
                out.append(FileUploadResponse(path=path, error=None))
            return out

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

        def __init__(self, image: str, network: bool = False, lease_s: int | None = None,
                     mem_limit: str | None = None):
            import docker  # optional dep

            self._image = image
            self._lease_s = _clamp_lease(lease_s)
            self._mem_limit = _clamp_mem(mem_limit)
            self._client = docker.from_env()  # raises if Docker daemon unavailable
            # HOME is set on the container's OWN env only (not the shared scrubbed-env helper,
            # which the fake backend runs as a host subprocess): a non-root read-only container
            # needs a writable HOME (=/work, a tmpfs) for pip/tools; the host must not get it.
            container_env = {**_scrubbed_sandbox_env(), "HOME": "/work"}
            # HARD group — present in every run attempt, never dropped. No host mount (C3).
            # `sleep {lease}` + auto_remove: the container self-terminates within the lease window
            # and Docker removes it, so a self-exited/normally-exited container needs no reaper. The
            # label lets the reaper find a STILL-RUNNING orphan (SIGKILL'd worker) by our own tag.
            from my_crew.runtime_backends.sandbox_reaper import SANDBOX_LABEL, SANDBOX_LABEL_VALUE
            base_kwargs = {
                "command": f"sleep {self._lease_s}", "detach": True,
                "network_disabled": not network,
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
                "mem_limit": self._mem_limit, "pids_limit": 256, "read_only": True,
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
            # Guard the exec: a transient Docker API error (e.g. a 404 if the container was
            # concurrently removed while parallel subagent `task` calls race execs against it)
            # must degrade to a non-zero ExecuteResponse the agent can react to, NOT raise and
            # abort the whole run. This mirrors upload_files/download_files' per-call guards and
            # keeps a flaky container-exec resilient (v43: deep_team subagents run parallel execs).
            try:
                res = self._container.exec_run(
                    ["sh", "-c", command], workdir="/work", demux=False)
            except Exception as exc:  # noqa: BLE001 — Docker API/transport error → degrade, not crash
                logger.warning("sandbox execute failed (degraded to error result): %s", exc)
                return ExecuteResponse(output=f"[sandbox exec error] {exc}"[:500], exit_code=1)
            out = res.output.decode("utf-8", errors="replace") if res.output else ""
            return ExecuteResponse(output=out, exit_code=res.exit_code)

        def download_files(self, paths: list[str]) -> list:
            from deepagents.backends.protocol import FileDownloadResponse

            out = []
            for path in paths:
                rel = _confined_rel(path)
                if rel is None:
                    out.append(FileDownloadResponse(path=path, content=None,
                                                    error="path_outside_work"))
                    continue
                # Read via exec+base64 (get_archive can't read the /work tmpfs mount over a
                # read-only rootfs). base64-encode in-container so binary content survives.
                import base64

                res = self._container.exec_run(
                    ["sh", "-c", f"base64 {_SANDBOX_ROOT}/{rel}"], workdir="/work")
                if res.exit_code != 0:
                    out.append(FileDownloadResponse(path=path, content=None,
                                                    error="file_not_found"))
                    continue
                try:
                    data = base64.b64decode((res.output or b"").strip())
                    out.append(FileDownloadResponse(path=path, content=data, error=None))
                except Exception:  # noqa: BLE001 — decode error → per-file error, never crash
                    out.append(FileDownloadResponse(path=path, content=None,
                                                    error="decode_failed"))
            return out

        def upload_files(self, files: list[tuple[str, bytes]]) -> list:
            from deepagents.backends.protocol import FileUploadResponse

            out = []
            for path, data in files:
                rel = _confined_rel(path)
                if rel is None:
                    out.append(FileUploadResponse(path=path, error="path_outside_work"))
                    continue
                if len(data) > _MAX_FILE_BYTES:
                    out.append(FileUploadResponse(path=path, error="file_too_large"))
                    continue
                try:
                    # /work is a tmpfs mount over a READ-ONLY rootfs (moat hardening), so
                    # docker put_archive (which targets the container FS layer) is refused.
                    # Write via exec instead: base64-pipe the bytes into the file so they
                    # land in the writable tmpfs. mkdir -p handles nested paths.
                    import base64

                    b64 = base64.b64encode(data).decode("ascii")
                    parent = str(PurePosixPath(rel).parent)
                    mk = f"mkdir -p {_SANDBOX_ROOT}/{parent} && " if parent not in (".", "") else ""
                    cmd = f"{mk}printf %s '{b64}' | base64 -d > {_SANDBOX_ROOT}/{rel}"
                    res = self._container.exec_run(["sh", "-c", cmd], workdir="/work")
                    if res.exit_code != 0:
                        raise RuntimeError((res.output or b"").decode("utf-8", "replace")[:120])
                    out.append(FileUploadResponse(path=path, error=None))
                except Exception as exc:  # noqa: BLE001 — per-file error, never crash the run
                    logger.warning("sandbox upload %r failed: %s", path, exc)
                    out.append(FileUploadResponse(path=path, error="upload_failed"))
            return out

        def teardown(self) -> None:
            try:
                self._container.remove(force=True)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass

    return _Docker


def FakeSandboxBackend():  # noqa: N802 — factory reads as a class to callers
    """Construct the fake (test) sandbox backend."""
    return _make_fake()()


def DockerSandboxBackend(  # noqa: N802
    image: str = SANDBOX_DEFAULT_IMAGE, network: bool = False, lease_s: int | None = None,
    mem_limit: str | None = None,
):
    """Construct the Docker (self-hosted) sandbox backend. Raises if Docker is unavailable.

    `network` is off by default; the caller passes True only when the agent opted in via the
    sandbox config (and, in the deep_agent path, only when input sanitization succeeded).
    `lease_s` sets the container's self-terminate window (clamped; None ⇒ SANDBOX_LEASE_S).
    `mem_limit` sets the container memory ceiling (clamped; None ⇒ SANDBOX_MEM_LIMIT).
    """
    try:
        return _make_docker()(image, network, lease_s, mem_limit)
    except SandboxDenied:
        raise  # a rejected HARD guardrail already fails closed with a precise message
    except Exception as exc:  # noqa: BLE001 — Docker daemon missing / unreachable
        raise SandboxDenied(
            f"Docker sandbox không khả dụng ({exc}). Cài + chạy Docker (Desktop/colima) hoặc "
            f"dùng agent_runtime khác."
        ) from exc


_PREPULL_TIMEOUT_S = 10  # bounded client so a wedged daemon can't hang the warm step


def prepull_sandbox_image(
    image: str | None = None, *, client: Any = None
) -> dict[str, Any]:
    """Opt-in warm of the sandbox image so the FIRST deep_agent step doesn't pay the pull.

    Idempotent + best-effort: image already present ⇒ no-op; absent + daemon up + online ⇒
    pulls; daemon down / offline ⇒ a clear result dict, never an exception. Returns
    ``{"ok", "pulled", "image", "message"}`` for a CLI/health surface to print. Not run on
    startup — a Docker-free deployment must never be forced to pull.
    """
    img = image or SANDBOX_DEFAULT_IMAGE
    try:
        if client is None:
            import docker  # optional dep

            client = docker.from_env(timeout=_PREPULL_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — Docker absent/unreachable is a clean skip
        return {
            "ok": False, "pulled": False, "image": img,
            "message": f"Docker không khả dụng ({exc}). Cài + chạy Docker (Desktop/colima) "
            f"nếu cần agent deep_agent.",
        }
    try:
        client.images.get(img)  # present locally → fast no-op
        return {"ok": True, "pulled": False, "image": img,
                "message": f"Image {img} đã có sẵn."}
    except Exception:  # noqa: BLE001 — not-found (or a transient) → try to pull
        pass
    try:
        client.images.pull(img)
        return {"ok": True, "pulled": True, "image": img,
                "message": f"Đã pull image {img}."}
    except Exception as exc:  # noqa: BLE001 — offline / pull error → best-effort, clear message
        return {"ok": False, "pulled": False, "image": img,
                "message": f"Pull {img} thất bại ({exc}). Kiểm tra mạng / Docker."}


def assert_not_host_shell(backend: Any) -> None:
    """Guard: the backend must not be a host-shell backend (red-team C3).

    deepagents' LocalShellBackend/FilesystemBackend-with-host-exec read the host filesystem;
    our allowlist never builds them, but assert defensively so a future path cannot slip one in.
    """
    name = type(backend).__name__
    if "LocalShell" in name or name == "FilesystemBackend":
        raise SandboxDenied(f"backend {name!r} chạy shell trên host — không được cho deep_agent.")
