"""Per-agent path + thread-id helpers (v2 M1-P3).

The single value that makes an agent isolated is its `data_dir`: every store
(audit / dedup / approvals / budget / checkpoints) keys off `settings.data_dir`
(set in P1). Point each agent at `.data/agents/<id>/` and isolation falls out for
free — `ActionGateway`/`BudgetTracker`/the checkpointer need no change.

`thread_id` is prefixed with the agent id so two agents' checkpoint threads never
collide (v1 used a flat `report-<kind>-<audience>`).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config.settings import DATA_DIR

# An agent id is the LAST path segment of its data dir + a thread-id prefix, so it
# must be a single safe segment: no "/", no "..", no absolute path. Anything else
# could escape the `.data/agents/` jail and break the isolation boundary.
_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_agent_id(agent_id: str) -> str:
    """Reject an agent id that could escape the per-agent data-dir jail."""
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(
            f"Invalid agent id {agent_id!r}: must match {_AGENT_ID_RE.pattern} "
            "(lowercase alnum, '-'/'_', no '/' or '..')."
        )
    return agent_id


def agent_data_dir(agent_id: str) -> Path:
    """The isolated data dir for an agent: `.data/agents/<id>/`.

    All of the agent's stores live under here, so two agents pointed at two
    different ids can never read or write each other's audit/budget/dedup/approvals.
    The id is validated so a malformed id cannot escape the `.data/agents/` jail.
    """
    return DATA_DIR / "agents" / _validate_agent_id(agent_id)


def agent_thread_id(agent_id: str, kind: str, audience: str) -> str:
    """Checkpoint thread id for one (agent, report-kind, audience).

    Agent-prefixed so A's and B's threads never collide. Date is intentionally
    omitted: one stable thread per (agent, kind, audience) keeps checkpoint rows
    bounded while still allowing resume. The id is validated (same rule as the
    data dir) so a thread id can't carry a path-like agent id.
    """
    return f"{_validate_agent_id(agent_id)}:{kind}:{audience}"
