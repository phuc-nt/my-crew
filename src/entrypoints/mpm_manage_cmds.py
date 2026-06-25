"""Per-agent Lớp B management — `mpm agent approvals/approve/reject/audit <id>`.

The gap-closer: `cli.py`'s approval/audit commands read the GLOBAL `.data/`, which goes
stale once the P3 worker migrates stores into `.data/agents/<id>/`. These build the
gateway / audit-log at the agent's OWN data dir (`load_profile(id,
data_dir=agent_data_dir(id))` ⇒ `settings.data_dir` ⇒ every store keys off it), so Lớp B
management + audit finally point at the migrated per-agent store. Approve/reject of agent
A never touch agent B's store.
"""

from __future__ import annotations

import sys

from src.actions.approved_dispatch import dispatch_approved_action as _dispatch_approved_action
from src.entrypoints.mpm import _flag_value
from src.runtime.agent_paths import agent_data_dir


def _load_agent(agent_id: str):
    """Load the agent's profile at its OWN data dir. Returns None on a clean error."""
    from src.profile.loader import load_profile

    try:
        return load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _gateway(loaded):
    """Build the Action Gateway at the agent's data dir (per-agent stores)."""
    from src.actions.action_gateway import ActionGateway

    return ActionGateway(loaded.settings, external_channels=loaded.config.slack_external_channels)


def run_manage(sub: str, args: list[str]) -> int:
    """Dispatch one per-agent management subcommand. `args[0]` is the agent id."""
    if not args:
        print(f"usage: mpm agent {sub} <id> ...", file=sys.stderr)
        return 2
    agent_id = args[0]
    loaded = _load_agent(agent_id)
    if loaded is None:
        return 1
    rest = args[1:]
    if sub == "approvals":
        return _approvals(loaded)
    if sub == "approve":
        return _approve(loaded, rest)
    if sub == "reject":
        return _reject(loaded, rest)
    return _audit(agent_id, rest)  # sub == "audit"


def _approvals(loaded) -> int:
    pending = _gateway(loaded).pending_approvals()
    if not pending:
        print("(no pending approvals)")
        return 0
    for p in pending:
        print(f"#{p.id}  {p.created_at[:19]}  {p.reason}")
        print(f"      action: {p.action}")
    return 0


def _approve(loaded, rest: list[str]) -> int:
    if not rest or not rest[0].isdigit():
        print("usage: mpm agent approve <id> <approval-id>", file=sys.stderr)
        return 2
    gw = _gateway(loaded)
    try:
        result = gw.approve(
            int(rest[0]), handler=lambda action: _dispatch_approved_action(action, loaded.config)
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"approved #{rest[0]}: {result.summary}")
    return 0


def _reject(loaded, rest: list[str]) -> int:
    if not rest or not rest[0].isdigit():
        print("usage: mpm agent reject <id> <approval-id>", file=sys.stderr)
        return 2
    _gateway(loaded).reject(int(rest[0]))
    print(f"rejected #{rest[0]}")
    return 0


def _audit(agent_id: str, rest: list[str]) -> int:
    from src.audit.audit_log import AuditLog

    limit_raw = _flag_value(rest, "--limit")
    path = agent_data_dir(agent_id) / "audit" / "audit.jsonl"
    entries = AuditLog(path).query(
        tool=_flag_value(rest, "--tool"),
        verdict=_flag_value(rest, "--verdict"),
        since=_flag_value(rest, "--since"),
        limit=int(limit_raw) if limit_raw else 20,
    )
    if not entries:
        print("(no audit entries match)")
        return 0
    for e in entries:
        print(
            f"{e.get('timestamp', '?')[:19]}  {e.get('verdict', '?'):10}  "
            f"{e.get('tool', '?'):28}  {e.get('reason', '')[:50]}"
        )
    return 0
