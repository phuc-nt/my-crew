"""v49 onboarding commands — `mpm quickstart` + `mpm crew init`.

Both compose EXISTING machinery to lower first-run friction (see the v49 plan), adding no new
report/graph or crew-building logic:

- `quickstart`: the already-possible "OpenRouter-key-only → one dry-run report" path, surfaced as
  one command. Forces `--dry-run` so it can never write externally.
- `crew init`: scaffold the shipped starter crew as REAL keepable profiles (reusing v32
  `create_crew`), distinct from the throwaway `demo-mode.sh` swap.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from my_crew.config.settings import MY_CREW_HOME


def run_quickstart(args: list[str]) -> int:
    """`mpm quickstart` — run the `default` agent's daily report in dry-run, OpenRouter-only.

    The one hard requirement for any LLM run is OPENROUTER_API_KEY; every other integration is
    optional for a dry-run report. Dry-run is FORCED here so quickstart never triggers an external
    write — the fastest safe first output.
    """
    # The guard must see .env values (the printed hint tells users to put the key
    # there) — the run path loads .env only later, inside the config builders.
    load_dotenv(MY_CREW_HOME / ".env")
    if not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "Chưa có OPENROUTER_API_KEY. Đặt nó trong .env (hoặc export) rồi chạy lại:\n"
            "  echo 'OPENROUTER_API_KEY=sk-or-...' >> .env",
            file=sys.stderr,
        )
        return 2

    from my_crew.entrypoints.mpm_run_cmd import run_agent

    print("→ Quickstart: chạy report 'daily' của agent 'default' (dry-run, không ghi ra ngoài)…")
    # Force --dry-run: quickstart is a safe first taste, never an external write.
    return run_agent(["default", "--report", "daily", "--dry-run"])


def run_crew(sub: str, args: list[str]) -> int:
    """`mpm crew init` — scaffold the shipped starter crew as REAL keepable profiles.

    Reuses the v32 `create_crew()` (idempotent, skip-existing, wires the coordinator only when
    unset) — the same single door the web one-click crew uses. Unlike `demo-mode.sh`, this writes
    real user-data the user keeps and customizes; there is no backup/restore swap.
    """
    if sub != "init":
        print(f"error: unknown crew subcommand {sub!r}. Dùng: mpm crew init", file=sys.stderr)
        return 2

    from my_crew.server.template_create import create_crew

    result = create_crew()
    created = result.get("created", [])
    skipped = result.get("skipped", [])
    failed = result.get("failed", [])
    coordinator_id = result.get("coordinator_id") or "(chưa đặt)"

    print(f"Đội mẫu: tạo mới {len(created)} · bỏ qua (đã có) {len(skipped)} · lỗi {len(failed)}")
    if created:
        print(f"  + tạo: {', '.join(created)}")
    if skipped:
        print(f"  = đã có: {', '.join(skipped)}")
    if failed:
        # `failed` items are {role_id, error} dicts — format as a clean sentence, not dict-repr.
        detail = ", ".join(f"{f.get('role_id', '?')}: {f.get('error', '')}" for f in failed)
        print(f"  ! lỗi: {detail}", file=sys.stderr)
    print(f"  điều phối (coordinator): {coordinator_id}")
    print(
        "\nTiếp theo:\n"
        "  • khởi động điều phối: uv run python -m my_crew.runtime.service\n"
        "  • thử 1 report: python -m my_crew.entrypoints.mpm quickstart"
    )
    return 1 if failed else 0
