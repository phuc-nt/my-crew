"""my-crew CLI front door — `my-crew <group> ...` (also `python -m my_crew.entrypoints.mpm`).

    my-crew quickstart
    my-crew crew init
    my-crew agent list | register <id> | run <id> --report <kind> [--audience ...] [--dry-run]
    my-crew agent resume <id> <thread_id> --decision approve|reject
    my-crew agent replay <id> <thread_id> [--checkpoint <id>]
    my-crew agent automate <id> <automation.yaml> [--dry-run]
    my-crew agent approvals <id> | approve <id> <approval-id> | reject <id> <approval-id>
    my-crew agent audit <id> [--tool X] [--verdict V] [--limit N]
    my-crew web hash-password
    my-crew sandbox prepull [image]

The multi-agent surface over the P3 primitives (registry + per-agent worker + per-agent
stores). `cli.py` / `cron.py` stay as the legacy single-agent entrypoints. This is a thin
argparse dispatcher: each command group lives in its own module (registry / run /
management), imported lazily so `--help` costs nothing and tests can monkeypatch the
command modules before dispatch binds them.
"""

from __future__ import annotations

import argparse
import logging
import sys
from importlib.metadata import PackageNotFoundError, version


def _dist_version() -> str:
    """Installed distribution version; a checkout without an install has no metadata."""
    try:
        return version("my-crew")
    except PackageNotFoundError:
        return "0.0.0+uninstalled"


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value after `--flag` in args, or None. Shared across the mpm modules."""
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


_AGENT_ACTIONS = (
    "list", "register", "run", "resume", "replay", "automate",
    "approvals", "approve", "reject", "audit",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="my-crew",
        description=(
            "my-crew — autonomous AI crew for a one-person company. Every write "
            "flows through the Action Gateway (autonomy-first, locked guardrails, full audit)."
        ),
        epilog=(
            "examples:\n"
            "  my-crew quickstart          # first dry-run report, only needs an OpenRouter key\n"
            "  my-crew crew init                  # scaffold the starter crew as real profiles\n"
            "  my-crew agent run pm --report daily --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"my-crew {_dist_version()}")
    sub = parser.add_subparsers(dest="group", required=True, metavar="<group>")

    p = sub.add_parser("quickstart", help="run a first dry-run report with only an OpenRouter key")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser(
        "serve",
        help="run web dashboard + coordinator in the foreground (compose/systemd/terminal)",
    )
    p.add_argument("--web-only", action="store_true", help="only the web dashboard")
    p.add_argument("--scheduler-only", action="store_true", help="only the coordinator")

    p = sub.add_parser("crew", help="crew-level onboarding (init: scaffold the starter crew)")
    p.add_argument("action", metavar="init")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("agent", help="operate one agent (list/register/run/approvals/audit/...)")
    p.add_argument("action", metavar="|".join(_AGENT_ACTIONS))
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("doctor", help="diagnose the install (env keys, MCP builds, node, home)")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("upgrade", help="show the upgrade path; --check compares against PyPI")
    p.add_argument("--check", action="store_true", help="exit 3 when an update is available")

    p = sub.add_parser("web", help="web helpers (hash-password: bcrypt for WEB_AUTH_PASSWORD_HASH)")
    p.add_argument("action", metavar="hash-password")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("sandbox", help="deep-agent sandbox helpers (prepull: warm the image)")
    p.add_argument("action", metavar="prepull")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    return parser


def _dispatch_agent(action: str, rest: list[str]) -> int:
    if action == "list":
        from my_crew.entrypoints.mpm_registry_cmds import run_list

        return run_list(rest)
    if action == "register":
        from my_crew.entrypoints.mpm_registry_cmds import run_register

        return run_register(rest)
    if action == "run":
        from my_crew.entrypoints.mpm_run_cmd import run_agent

        return run_agent(rest)
    if action == "resume":
        from my_crew.entrypoints.mpm_resume_cmd import run_resume

        return run_resume(rest)
    if action == "replay":
        from my_crew.entrypoints.mpm_replay_cmd import run_replay

        return run_replay(rest)
    if action == "automate":
        from my_crew.entrypoints.mpm_automate_cmd import run_automate

        return run_automate(rest)
    if action in {"approvals", "approve", "reject", "audit"}:
        from my_crew.entrypoints.mpm_manage_cmds import run_manage

        return run_manage(action, rest)
    print(f"error: unknown subcommand {action!r}.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    # argparse signals usage errors (and --help/--version) via SystemExit; the mpm
    # contract is return-int (tests and cron drivers call main() directly), so fold
    # the exit code back into a return value.
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2

    # Installed/container mode: make the shipped starter profiles loadable before any
    # command touches the registry/profiles (no-op on a checkout).
    from my_crew.config.home_seed import ensure_home_seeded

    ensure_home_seeded()

    if ns.group == "quickstart":
        from my_crew.entrypoints.mpm_onboarding_cmds import run_quickstart

        return run_quickstart(ns.rest)
    if ns.group == "serve":
        from my_crew.entrypoints.serve_cmd import run_serve

        flags = (["--web-only"] if ns.web_only else []) + (
            ["--scheduler-only"] if ns.scheduler_only else []
        )
        return run_serve(flags)
    if ns.group == "crew":
        from my_crew.entrypoints.mpm_onboarding_cmds import run_crew

        return run_crew(ns.action, ns.rest)
    if ns.group == "doctor":
        from my_crew.entrypoints.mpm_lifecycle_cmds import run_doctor

        return run_doctor(ns.rest)
    if ns.group == "upgrade":
        from my_crew.entrypoints.mpm_lifecycle_cmds import run_upgrade

        return run_upgrade(["--check"] if ns.check else [])
    if ns.group == "web":
        from my_crew.entrypoints.mpm_web_cmd import run_web

        return run_web(ns.action, ns.rest)
    if ns.group == "sandbox":
        if ns.action != "prepull":
            print(f"error: unknown subcommand {ns.action!r}.", file=sys.stderr)
            return 2
        from my_crew.runtime_backends.sandbox_backend import prepull_sandbox_image

        result = prepull_sandbox_image(ns.rest[0] if ns.rest else None)
        print(result["message"])
        return 0 if result["ok"] else 1
    return _dispatch_agent(ns.action, ns.rest)


if __name__ == "__main__":
    raise SystemExit(main())
