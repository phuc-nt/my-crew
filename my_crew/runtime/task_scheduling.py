"""Task-scheduling helpers (v6 M15) — decide when the service fires the `tasks` kind.

Kept separate from `service.py` so `_effective_schedule` stays small and the "does this
agent have open tasks?" check has one home. `has_open_tasks` opens the task store read-only
per tick — cheap (an indexed COUNT), same posture as the inbox check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: How often the service fires the `tasks` kind. Hourly is plenty: a watch reminder is
#: deduped per-day, and a PR merge is noticed within the hour rather than instantly.
_TASKS_CRON = "0 * * * *"


def _store_path(data_dir: Path) -> Path:
    return Path(data_dir) / "tasks.sqlite3"


def has_open_tasks(loaded: Any) -> bool:
    """True when the agent has at least one open assigned task. False (no store yet) ⇒ the
    agent behaves byte-identically to pre-M15.

    The store dir is derived from the agent's canonical `agent_data_dir(profile_id)` —
    NOT `settings.data_dir`. The service loads profiles WITHOUT a per-agent data_dir, so
    `settings.data_dir` there is the global DATA_DIR, while the worker + ops-catalog write
    the store under `.data/agents/<id>/`. Keying off `agent_data_dir` makes this check
    agree with where the store actually lives, in every caller.
    """
    profile_id = getattr(loaded, "profile_id", None)
    if not profile_id:
        return False
    from my_crew.runtime.agent_paths import agent_data_dir

    path = _store_path(agent_data_dir(profile_id))
    if not path.exists():
        return False
    from my_crew.runtime.task_store import TaskStore

    store = TaskStore(path)
    try:
        return store.open_count() > 0
    finally:
        store.close()


def tasks_cron(loaded: Any) -> str:
    """The cron string the service fires `tasks` on. Fixed hourly in M15a."""
    return _TASKS_CRON
