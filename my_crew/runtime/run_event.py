"""B1 run-event log — one JSONL line per worker run (v2 M1-P3).

Each worker run appends a single line to `<agent data dir>/runs.jsonl` recording what
ran and how it ended (status / cost / delivered). The coordinating service (Slice 3)
reads the last line to get the run detail alongside the worker's exit code. Lives next
to the per-agent audit log, so it is isolated per agent like every other store.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_run_event(data_dir: Path, event: dict[str, Any]) -> None:
    """Append one run-event as a JSON line to `data_dir/runs.jsonl`.

    Adds a UTC ISO `ts` if the caller did not provide one. Creates the data dir if
    missing. Append-only: never rewrites prior lines.
    """
    event = {"ts": datetime.now(UTC).isoformat(), **event}
    data_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with (data_dir / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_last_run_event(agent_id: str) -> dict[str, Any] | None:
    """Return the last run-event dict for an agent (or None if no runs yet).

    Reads the final non-empty line of `<agent data dir>/runs.jsonl`. Shared by the
    coordinating service (outcome detail) and the M2-P6 web service (agent status),
    so neither imports a private helper. A malformed last line returns None.
    """
    from my_crew.runtime.agent_paths import agent_data_dir

    path = agent_data_dir(agent_id) / "runs.jsonl"
    if not path.exists():
        return None
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def read_run_events(agent_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return an agent's run-events newest-first (M4: timeline view source).

    Sibling of `read_last_run_event` — reads the whole `runs.jsonl`, skips malformed
    lines (never fails the whole read), reverses to newest-first, and clamps to `limit`
    (bounded so a long-running agent's history can't return an unbounded list). Returns
    `[]` when there are no runs yet.
    """
    from my_crew.runtime.agent_paths import agent_data_dir

    path = agent_data_dir(agent_id) / "runs.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue  # skip a corrupt line rather than fail the whole read
    out.reverse()  # newest first
    clamp = max(1, min(limit, 500))
    return out[:clamp]
