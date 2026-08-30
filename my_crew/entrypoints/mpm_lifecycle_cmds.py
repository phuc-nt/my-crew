"""Lifecycle commands — `my-crew doctor` (diagnose) + `my-crew upgrade` (guide/check).

doctor: read-only diagnosis. Reuses the server-side integration health checks (the
same ones the dashboard's Sức khỏe panel shows) and adds CLI-environment extras
(node/npm presence, home writability). It never mutates anything — no `--fix`.

upgrade: prints the exact upgrade path for the detected install mode (checkout vs
installed package) instead of self-executing shell — the operator stays in control.
`--check` does a real PyPI version compare (bounded, degrades offline).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from importlib.metadata import PackageNotFoundError, version

from my_crew.config.settings import DATA_DIR, MY_CREW_HOME, REPO_ROOT

_PYPI_JSON_URL = "https://pypi.org/pypi/my-crew/json"

#: Check ids from `integration_health._run_checks()` that gate a first RUN (an OpenRouter
#: report needs nothing else). Everything else (Atlassian, Slack, MCP builds, gws, docker,
#: SMTP, operator push, websearch key) is an optional integration — useful once the
#: operator wants that specific feature, but its absence must not read as "broken install".
_REQUIRED_CHECK_IDS = frozenset({"openrouter"})


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


def _print_check(ok: bool, label: str, detail: str, hint: str) -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}: {detail}")
    if not ok and hint:
        print(f"      → {hint}")


def _tool_version(cmd: str) -> str | None:
    """`<cmd> --version` first line, or None when the tool is missing/broken."""
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def run_doctor(args: list[str]) -> int:
    """`my-crew doctor` — ✓/✗ per check with an actionable hint, split into Bắt buộc
    (required for a first OpenRouter-only run: the key itself, a writable home, and
    working python deps — implied by doctor running at all) vs Tùy chọn (every other
    integration). rc reflects the REQUIRED group only: a clean machine with just an
    OpenRouter key exits 0 even though every optional integration is unconfigured —
    doctor must not read "unconfigured Slack" as "broken install"."""
    # The server-side checks must see .env exactly like the dashboard does.
    from dotenv import load_dotenv

    load_dotenv(MY_CREW_HOME / ".env")
    print(f"my-crew doctor — home: {MY_CREW_HOME}")
    print("Chỉ cần OpenRouter để bắt đầu.")

    required_failures = 0
    optional_failures = 0

    def _required(ok: bool, label: str, detail: str, hint: str) -> None:
        nonlocal required_failures
        _print_check(ok, label, detail, hint)
        required_failures += not ok

    def _optional(ok: bool, label: str, detail: str, hint: str) -> None:
        nonlocal optional_failures
        _print_check(ok, label, detail, hint)
        optional_failures += not ok

    print("\nBắt buộc:")
    home_writable = os.access(MY_CREW_HOME, os.W_OK)
    _required(home_writable, "home writable", str(MY_CREW_HOME),
              "fix permissions or set MY_CREW_HOME")

    # Server-side integration checks (same source the dashboard health panel uses),
    # split by id: REQUIRED (OpenRouter) vs everything else (optional integrations).
    from my_crew.server.integration_health import _run_checks

    server_checks = _run_checks()
    for check in server_checks:
        if check["id"] in _REQUIRED_CHECK_IDS:
            _required(check["ok"], check["label"], check["detail"], check["hint"])

    print("\nTùy chọn:")
    # CLI-environment extras: node/npm (MCP servers runtime).
    node_v = _tool_version("node")
    _optional(node_v is not None, "node (MCP servers runtime)", node_v or "not found",
              "install Node.js (brew install node / nodesource)")
    npm_v = _tool_version("npm")
    _optional(npm_v is not None, "npm", npm_v or "not found", "comes with Node.js")

    for check in server_checks:
        if check["id"] not in _REQUIRED_CHECK_IDS:
            _optional(check["ok"], check["label"], check["detail"], check["hint"])

    # Informational: the pinned MCP-server versions this install targets.
    from my_crew.config.settings import SHIPPED_ROOT

    pins_file = SHIPPED_ROOT / "config" / "mcp-server-pins.sh"
    if pins_file.is_file():
        pins = dict(
            line.strip().split("=", 1)
            for line in pins_file.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        )
        print(
            "  • MCP server pins: "
            f"jira {pins.get('JIRA_PKG_VERSION', '?')} · "
            f"confluence {pins.get('CONFLUENCE_PKG_VERSION', '?')} · "
            f"slack {pins.get('SLACK_PKG_VERSION', '?')}"
        )

    _print_orphan_agent_dirs()

    print(
        f"\ndoctor: bắt buộc "
        f"{'OK' if required_failures == 0 else f'{required_failures} lỗi'} · "
        f"tùy chọn {'OK' if optional_failures == 0 else f'{optional_failures} chưa cấu hình'}"
    )
    return 0 if required_failures == 0 else 1


def _print_orphan_agent_dirs() -> None:
    """P6: list `.data/agents/<id>/` dirs whose id is no longer in registry.yaml.

    Read-only — doctor never deletes anything; `mpm agent purge-data <id>` is the
    explicit, separately-confirmed follow-up (GC is never automatic, see D8/D10)."""
    from my_crew.runtime.registry import load_registry

    agents_dir = DATA_DIR / "agents"
    if not agents_dir.is_dir():
        return
    try:
        registered = {e.id for e in load_registry()}
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"\n  (bỏ qua kiểm tra dir mồ côi: không đọc được registry — {exc})")
        return
    orphans = sorted(
        d.name for d in agents_dir.iterdir() if d.is_dir() and d.name not in registered
    )
    if not orphans:
        return
    print(f"\nDir dữ liệu mồ côi (không còn trong registry.yaml): {len(orphans)}")
    for name in orphans:
        print(f"  • {name}  →  mpm agent purge-data {name} --confirm")


def _pypi_latest(timeout_s: float = 5.0) -> str | None:
    try:
        with urllib.request.urlopen(_PYPI_JSON_URL, timeout=timeout_s) as resp:
            return json.load(resp)["info"]["version"]
    except Exception:  # noqa: BLE001 — offline/404 both degrade to "unknown"
        return None


def run_upgrade(args: list[str]) -> int:
    """`my-crew upgrade [--check]` — version compare + the exact path per install mode."""
    try:
        current = version("my-crew")
    except PackageNotFoundError:
        current = "0.0.0+uninstalled"
    latest = _pypi_latest()
    print(f"current: {current}   latest on PyPI: {latest or 'unknown (offline or unpublished)'}")

    if "--check" in args:
        if latest is None:
            return 1
        return 0 if latest == current else 3  # 3 = update available (scriptable)

    if _is_checkout():
        print(
            "install mode: git checkout — upgrade with:\n"
            f"  cd {REPO_ROOT} && git pull && ./deploy/install.sh\n"
            "  (re-run install.sh is REQUIRED after upgrades: it re-renders launchd\n"
            "   plists and swaps the web bundle; see docs/deployment-guide.md)"
        )
    else:
        print(
            "install mode: installed package — upgrade with ONE of:\n"
            "  uv tool upgrade my-crew\n"
            "  pipx upgrade my-crew\n"
            "  pip install -U my-crew\n"
            "then restart `my-crew serve` (or your supervisor)."
        )
    return 0


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover — thin manual hook
    args = argv if argv is not None else sys.argv[1:]
    return run_doctor(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
