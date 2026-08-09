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

from my_crew.actions.approval_rule_store import SCOPE_ALWAYS, SCOPE_DENY, derive_rule_key
from my_crew.entrypoints.mpm import _flag_value
from my_crew.runtime.agent_paths import agent_data_dir


def _describe_rule_key(action: dict) -> str:
    """Human-readable one-liner for the rule the operator is about to teach."""
    pattern_key, params_hash = derive_rule_key(action)
    bound = " (đích cố định)" if params_hash else " (mọi tham số)"
    return f"{pattern_key}{bound}"


def _rule_ack(agent_id: str, action: dict, scope: str, rule_id: int) -> str:
    """The ack shown after a rule is learned. ALWAYS states the guarded-only limit for a
    deny rule (CEO decision 2026-08-04) so nobody mistakes it for an autonomous block."""
    verb = "chặn" if scope == SCOPE_DENY else "duyệt"
    limit = " — CHỈ hiệu lực ở chế độ guarded" if scope == SCOPE_DENY else ""
    return (
        f"Từ giờ tự {verb}: {_describe_rule_key(action)}{limit}. "
        f"Hoàn tác: mpm agent rules {agent_id} --revoke {rule_id}"
    )


def _load_agent(agent_id: str):
    """Load the agent's profile at its OWN data dir. Returns None on a clean error."""
    from my_crew.profile.loader import load_profile

    try:
        return load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _gateway(loaded):
    """Build the Action Gateway at the agent's data dir (per-agent stores)."""
    from my_crew.actions.action_gateway import ActionGateway

    return ActionGateway(loaded.settings, external_channels=loaded.config.slack_external_channels,
                         actor=getattr(loaded, "profile_id", ""))  # v46


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
    if sub == "rules":
        return _rules(loaded, rest)
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
        print("usage: mpm agent approve <id> <approval-id> [--always]", file=sys.stderr)
        return 2
    approval_id = int(rest[0])
    always = "--always" in rest
    gw = _gateway(loaded)
    # Read the row's action BEFORE the transition (approve consumes it) so a --always
    # rule is derived from the exact action the operator just OK'd — no hand-typed pattern.
    row = gw._approvals.get(approval_id) if always else None
    try:
        # Agent-bound dispatch (v31 P2): native types (schedule_update) close over THIS
        # loaded agent's identity; everything else falls through to the shared dispatch.
        from my_crew.actions.approved_dispatch import make_agent_bound_dispatch

        # getattr: production `loaded` is a LoadedProfile (always has profile_id);
        # an id-less double simply gets a dispatch that can't run agent-bound types.
        result = gw.approve(
            approval_id,
            handler=make_agent_bound_dispatch(
                getattr(loaded, "profile_id", ""), loaded.config
            ),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"approved #{approval_id}: {result.summary}")
    if always and row is not None:
        agent_id = getattr(loaded, "profile_id", "")
        rule = gw.approval_rules.add_rule(
            row.action, scope=SCOPE_ALWAYS, created_by=agent_id
        )
        print(_rule_ack(agent_id, row.action, SCOPE_ALWAYS, rule.id))
    return 0


def _reject(loaded, rest: list[str]) -> int:
    if not rest or not rest[0].isdigit():
        print("usage: mpm agent reject <id> <approval-id> [--always]", file=sys.stderr)
        return 2
    approval_id = int(rest[0])
    always = "--always" in rest
    gw = _gateway(loaded)
    row = gw._approvals.get(approval_id) if always else None
    if not gw.reject(approval_id):
        # Another surface (web, chat, or a second CLI) already decided this row.
        # Say so instead of claiming a rejection that did not happen — and do NOT
        # learn a deny rule from a decision that was not ours to make.
        print(f"error: #{approval_id} đã được xử lý trước đó", file=sys.stderr)
        return 1
    print(f"rejected #{approval_id}")
    if always and row is not None:
        agent_id = getattr(loaded, "profile_id", "")
        rule = gw.approval_rules.add_rule(
            row.action, scope=SCOPE_DENY, created_by=agent_id
        )
        print(_rule_ack(agent_id, row.action, SCOPE_DENY, rule.id))
    return 0


def _rules(loaded, rest: list[str]) -> int:
    """`mpm agent rules <id>` (list) / `... --revoke <rule-id> [--confirm]`.

    Revoking a DENY rule loosens protection, so it requires `--confirm` (explicit — never
    silent). Revoking an ALWAYS rule tightens, so it needs no extra confirmation."""
    gw = _gateway(loaded)
    store = gw.approval_rules
    revoke_id = _flag_value(rest, "--revoke")
    if revoke_id is not None:
        if not revoke_id.isdigit():
            print("usage: mpm agent rules <id> --revoke <rule-id> [--confirm]", file=sys.stderr)
            return 2
        rule = store.get(int(revoke_id))
        if rule is None:
            print(f"error: no rule #{revoke_id}", file=sys.stderr)
            return 1
        if rule.scope == SCOPE_DENY and "--confirm" not in rest:
            print(
                f"refusing to revoke deny rule #{revoke_id} without --confirm "
                "(revoking a deny loosens protection).",
                file=sys.stderr,
            )
            return 1
        if store.revoke(int(revoke_id)):
            print(f"revoked rule #{revoke_id}")
            return 0
        print(f"rule #{revoke_id} was already revoked", file=sys.stderr)
        return 1
    rules = store.list_rules()
    if not rules:
        print("(no learned rules)")
        return 0
    for r in rules:
        effect = "guarded" if r.scope == SCOPE_DENY else "mọi chế độ"
        used = f", đã dùng {r.use_count}×" if r.use_count else ""
        print(f"#{r.id}  {r.scope:6}  {r.pattern_key}  [hiệu lực: {effect}]{used}")
    return 0


def _audit(agent_id: str, rest: list[str]) -> int:
    from my_crew.audit.audit_log import AuditLog

    # v76: `mpm agent audit <id> verify` (or `--team` for the shared team-tasks trail)
    # walks the hash-chain and reports the first break — the command that turns
    # "append-only by discipline" into "tamper-evident, checkable".
    if "verify" in rest:
        from my_crew.audit.audit_chain import verify_chain

        if "--team" in rest:
            from my_crew.runtime.team_task_paths import team_tasks_root

            target = team_tasks_root() / "audit" / "audit.jsonl"
        else:
            target = agent_data_dir(agent_id) / "audit" / "audit.jsonl"
        v = verify_chain(target)
        print(f"{target}")
        print(f"  total={v['total']} hashed={v['hashed']} legacy_prefix={v['legacy_prefix']} "
              f"restarts={v['restarts']}")
        if v["ok"]:
            print("  OK — chain nguyên vẹn")
            return 0
        print(f"  BROKEN tại dòng {v['broken_line']} (lý do: {v['reason']})")
        return 1

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
