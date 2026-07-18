"""Multi-agent CLI entrypoint (v2 M1-P4) — `mpm agent ...`.

    python -m my_crew.entrypoints.mpm agent list
    python -m my_crew.entrypoints.mpm agent register <id>
    python -m my_crew.entrypoints.mpm agent run <id> --report <kind> [--audience ...] [--dry-run]
    python -m my_crew.entrypoints.mpm agent approvals <id>
    python -m my_crew.entrypoints.mpm agent approve <id> <approval-id>
    python -m my_crew.entrypoints.mpm agent reject <id> <approval-id>
    python -m my_crew.entrypoints.mpm agent audit <id> [--tool X] [--verdict V] [--limit N]

The multi-agent surface over the P3 primitives (registry + per-agent worker + per-agent
stores). `cli.py` / `cron.py` stay as the legacy single-agent entrypoints. This is a thin
dispatcher: each command group lives in its own module (registry / run / management).
"""

from __future__ import annotations

import logging
import sys

_USAGE = (
    "usage: python -m my_crew.entrypoints.mpm quickstart | crew init | agent "
    "list | register <id> | run <id> --report <kind> [--audience ...] [--dry-run] | "
    "resume <id> <thread_id> --decision approve|reject | "
    "replay <id> <thread_id> [--checkpoint <id>] | "
    "automate <id> <automation.yaml> [--dry-run] | "
    "approvals <id> | approve <id> <approval-id> | reject <id> <approval-id> | audit <id> [filters]"
)


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value after `--flag` in args, or None. Shared across the mpm modules."""
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    # v6 M16: `mpm web hash-password` — generate a bcrypt hash for WEB_AUTH_PASSWORD_HASH.
    if len(args) >= 2 and args[0] == "web":
        from my_crew.entrypoints.mpm_web_cmd import run_web

        return run_web(args[1], args[2:])
    # v47: `mpm sandbox prepull [image]` — opt-in warm of the deep_agent sandbox image so the
    # first shell step doesn't pay the pull. Daemon-safe: prints a clear line, never crashes.
    if len(args) >= 2 and args[0] == "sandbox" and args[1] == "prepull":
        from my_crew.runtime_backends.sandbox_backend import prepull_sandbox_image

        result = prepull_sandbox_image(args[2] if len(args) >= 3 else None)
        print(result["message"])
        return 0 if result["ok"] else 1
    # v49: `mpm quickstart` — OpenRouter-only first report (dry-run) in one command.
    if len(args) >= 1 and args[0] == "quickstart":
        from my_crew.entrypoints.mpm_onboarding_cmds import run_quickstart

        return run_quickstart(args[1:])
    # v49: `mpm crew init` — scaffold the shipped starter crew as real keepable profiles.
    if len(args) >= 2 and args[0] == "crew":
        from my_crew.entrypoints.mpm_onboarding_cmds import run_crew

        return run_crew(args[1], args[2:])
    if len(args) < 2 or args[0] != "agent":
        print(_USAGE, file=sys.stderr)
        return 2

    sub, rest = args[1], args[2:]
    if sub == "list":
        from my_crew.entrypoints.mpm_registry_cmds import run_list

        return run_list(rest)
    if sub == "register":
        from my_crew.entrypoints.mpm_registry_cmds import run_register

        return run_register(rest)
    if sub == "run":
        from my_crew.entrypoints.mpm_run_cmd import run_agent

        return run_agent(rest)
    if sub == "resume":
        from my_crew.entrypoints.mpm_resume_cmd import run_resume

        return run_resume(rest)
    if sub == "replay":
        from my_crew.entrypoints.mpm_replay_cmd import run_replay

        return run_replay(rest)
    if sub == "automate":
        from my_crew.entrypoints.mpm_automate_cmd import run_automate

        return run_automate(rest)
    if sub in {"approvals", "approve", "reject", "audit"}:
        from my_crew.entrypoints.mpm_manage_cmds import run_manage

        return run_manage(sub, rest)

    print(f"error: unknown subcommand {sub!r}.\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
