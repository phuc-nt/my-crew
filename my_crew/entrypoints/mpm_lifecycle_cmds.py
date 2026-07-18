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

from my_crew.config.settings import MY_CREW_HOME, REPO_ROOT

_PYPI_JSON_URL = "https://pypi.org/pypi/my-crew/json"


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
    """`my-crew doctor` — ✓/✗ per check with an actionable hint; rc 1 if anything failed."""
    # The server-side checks must see .env exactly like the dashboard does.
    from dotenv import load_dotenv

    load_dotenv(MY_CREW_HOME / ".env")
    print(f"my-crew doctor — home: {MY_CREW_HOME}")

    failures = 0

    # CLI-environment extras first: the integration checks assume a runnable host.
    node_v = _tool_version("node")
    _print_check(node_v is not None, "node (MCP servers runtime)", node_v or "not found",
                 "install Node.js (brew install node / nodesource)")
    failures += node_v is None
    npm_v = _tool_version("npm")
    _print_check(npm_v is not None, "npm", npm_v or "not found", "comes with Node.js")
    failures += npm_v is None

    home_writable = os.access(MY_CREW_HOME, os.W_OK)
    _print_check(home_writable, "home writable", str(MY_CREW_HOME),
                 "fix permissions or set MY_CREW_HOME")
    failures += not home_writable

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

    # Server-side integration checks (same source the dashboard health panel uses).
    from my_crew.server.integration_health import _run_checks

    for check in _run_checks():
        _print_check(check["ok"], check["label"], check["detail"], check["hint"])
        failures += not check["ok"]

    print(f"doctor: {'all checks passed' if failures == 0 else f'{failures} check(s) failed'}")
    return 0 if failures == 0 else 1


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
