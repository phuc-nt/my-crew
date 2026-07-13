"""Cross-agent path helpers for the team-task store + handoff artifacts.

Both the store DB and the handoff artifacts live at the repo-root `DATA_DIR`
(`.data/`), NOT under any single agent's `.data/agents/<id>/` — a team task spans
multiple agents by design, so its shared state cannot live inside one agent's
isolated dir. This is the single source of truth for that root path so the
coordinator, the worker's `team-step` branch, `team_task_store`, and
`team_task_artifact` never disagree on where the shared state lives.
"""

from __future__ import annotations

from pathlib import Path

from src.config.settings import DATA_DIR


def team_tasks_root() -> Path:
    """The shared cross-agent data dir: repo-root `.data/`."""
    return DATA_DIR


def team_tasks_db_path() -> Path:
    """`<team_tasks_root()>/team_tasks.sqlite3` — the one shared team-task store file."""
    return team_tasks_root() / "team_tasks.sqlite3"


def capture_db_path() -> Path:
    """`<team_tasks_root()>/captures.sqlite3` — the per-attempt telemetry store file.

    A sibling of the team-task store (same cross-agent root, same multi-writer access from
    concurrent workers) but a SEPARATE DB so telemetry stays decoupled from task/step state.
    """
    return team_tasks_root() / "captures.sqlite3"


def team_checkpoints_db_path() -> Path:
    """`<team_tasks_root()>/team_checkpoints.sqlite3` — LangGraph checkpoints for
    team-task step graphs (v34 P1). Its OWN file (not any agent's `checkpoints.db`,
    not the store DB) so multi-process lock behavior stays decoupled."""
    return team_tasks_root() / "team_checkpoints.sqlite3"


def clarify_db_path() -> Path:
    """`<team_tasks_root()>/clarify.sqlite3` — CEO clarification questions (v33 P4).

    Cross-agent by nature (any agent may ask; the CEO answers from web or Telegram),
    so it lives at the shared root like the team-task store, in its own file so the
    Q&A queue stays decoupled from task/step state."""
    return team_tasks_root() / "clarify.sqlite3"
