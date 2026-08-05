"""Learned-approval rules (Lớp B pattern memory) — per-agent, next to `approvals.db`.

The trust ladder (`auto_approve_policy`) is a CONFIG grant the operator writes ahead of
time. This store is the complementary path: the CEO approves/rejects ONE real pending row
with an "always"/"deny" flag, and the gateway remembers the (pattern_key, params_hash) so
the SAME action decides itself next time — with an audit trail and a revoke.

Invariant preserved: a rule only decides Lớp B (reversible-but-sensitive). Lớp A hard-deny,
the allowlist default-deny, the kill-switch and dry-run are re-applied downstream — a rule
can never loosen them (stricter-of-two). Deny rules apply ONLY in guarded mode (CEO decision
2026-08-04): autonomous keeps full authority, so an autonomous run never consults this store.

Storage: table `approval_rules` INSIDE the per-agent `approvals.db` (house pattern — CREATE
IF NOT EXISTS + try/except ALTER, same as `approval_store.py`). File position IS the identity
(one db per agent), so no agent_id column is needed; `created_by` records the operator.

Key derivation is ONE function shared by learn (CLI writes the rule) and enforce (gateway/
ticker match it), so the two can never drift. Every outbound-directed action binds its
destination into `params_hash`: changing the recipient / channel / repo / doc misses the
rule and re-asks the CEO — the OpenClaw argv-binding lesson against silent scope creep.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Rule scopes. `once` is the pre-existing behavior (approve/reject a single row) and is
#: NOT stored here — it needs no memory. This store holds only the standing scopes.
SCOPE_ALWAYS = "always"
SCOPE_DENY = "deny"
_STANDING_SCOPES = (SCOPE_ALWAYS, SCOPE_DENY)


@dataclass(frozen=True)
class ApprovalRule:
    id: int
    pattern_key: str
    params_hash: str | None
    scope: str  # "always" | "deny"
    created_at: str
    created_by: str
    last_used_at: str | None = None
    use_count: int = 0
    revoked_at: str | None = None


def _hash_params(parts: list[str]) -> str:
    """Stable short hash of the destination parts a rule is bound to. Sorted so order
    never changes the identity; sha256 so a long recipient list can't collide by accident."""
    canonical = json.dumps(sorted(parts), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def email_domains(action: dict[str, Any]) -> list[str]:
    """Recipient domains of an email_send (bind on domain, not full address — a rule for
    `@acme.com` shouldn't leak to a stranger, but shouldn't churn per individual either).

    Public because the chat preview must SAY what a standing rule will cover, and the only
    honest way to say it is to read the same domains this binds. A second implementation
    there could drift and describe a narrower rule than the one actually stored.
    """
    args = action.get("args") or {}
    raw = action.get("to") or args.get("to") or ""
    recipients = raw if isinstance(raw, list) else [raw]
    domains = []
    for r in recipients:
        s = str(r)
        if "@" in s:
            domains.append(s.rsplit("@", 1)[1].lower())
    return domains


# Destination-id arg keys used by the REAL mcp writers in this repo. Sourced from the
# writers themselves, not guessed: slack_write uses `channel`; linear_write sends
# `issueId` (`linear_write.py:89`); confluence_write sends `spaceId`
# (`confluence_write.py:130`). snake_case twins are accepted because MCP servers vary.
# One list, shared with the audit bridge's `_short_target`, so the two can never drift —
# a key missing here means a learned rule would bind nothing and match a DIFFERENT target.
MCP_DESTINATION_KEYS: tuple[str, ...] = (
    "channel", "channel_id", "channelId",
    "issueId", "issue_id", "issueKey", "issue_key",
    "spaceId", "space_id", "spaceKey", "space_key",
    "pageId", "page_id",
    "projectId", "project_id",
    "id",
)


def mcp_destination(args: Any) -> str:
    """The destination id an mcp_tool call targets, or "" when none is recognized."""
    if not isinstance(args, dict):
        return ""
    for key in MCP_DESTINATION_KEYS:
        value = args.get(key)
        if value:
            return str(value)
    return ""


def derive_rule_key(action: dict[str, Any]) -> tuple[str, str | None]:
    """Map an action dict to `(pattern_key, params_hash)` — the shared identity for learn +
    enforce. `params_hash` is None ONLY for internal types whose blast radius is
    param-independent (a team-task move is a team-task move); every outbound-directed type
    binds its destination so a changed recipient/channel/repo/doc misses and re-asks.

    Taxonomy is the REAL `_MUTATING_TYPES` (`action_gateway._MUTATING_TYPES`), not an invented
    one. An unknown type falls back to `(type, whole-action-hash)` — maximally specific, so it
    can never match too broadly (it just won't match a differently-shaped action).

    Two callers derive keys from two different copies of the same action: the CLI learns a rule
    from the action as stored by `ApprovalStore`, which is REDACTED, while the gateway matches
    the LIVE action. They agree because redaction only rewrites secret-shaped substrings and no
    bound field carries a secret in practice (secrets ride in bodies; bodies are never bound).
    The one way they can disagree is a destination id that is itself secret-shaped (a Slack
    channel literally named `xoxb-...`): the two hashes then differ and the rule simply does not
    fire, leaving the action queued for a human. That is the fail-closed direction and is why
    hashing must stay on the redacted-vs-live pair as-is — binding pre-redaction would put
    unredacted secrets in this store for no safety gain.
    """
    atype = str(action.get("type", "")).lower()

    if atype == "gh_cli":
        argv = [str(a) for a in (action.get("argv") or [])]
        pattern = "gh:" + " ".join(argv[:2])  # subcommand pair only (e.g. "pr merge")
        # Bind the repo target: an explicit `-R owner/repo` if present, else the argv tail
        # that names the target (issue/PR number). Absent → bind the whole argv (specific).
        repo = ""
        if "-R" in argv:
            i = argv.index("-R")
            if i + 1 < len(argv):
                repo = argv[i + 1]
        bind = [repo] if repo else argv[2:]
        return pattern, _hash_params([str(b) for b in bind]) if bind else None

    if atype == "mcp_tool":
        server = str(action.get("server", "?"))
        tool = str(action.get("tool", "?"))
        pattern = f"mcp:{server}:{tool}"
        args = action.get("args") or {}
        dest = mcp_destination(args)
        if dest:
            return pattern, _hash_params([dest])
        # No RECOGNIZED destination key: never fall back to a NULL bind — that would let a
        # rule taught on one target auto-approve a write to a different one. Bind the whole
        # args instead (maximally specific: an unknown-shaped write can only match itself).
        if isinstance(args, dict) and args:
            return pattern, _hash_params(
                [f"{k}={json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)}"
                 for k, v in args.items()]
            )
        return pattern, None

    if atype == "email_send":
        domains = email_domains(action)
        return "email", _hash_params(domains) if domains else None

    if atype == "telegram_send":
        chat_id = str(action.get("chat_id") or "")
        return "telegram", _hash_params([chat_id]) if chat_id else None

    if atype == "gws_write":
        argv = [str(a) for a in (action.get("argv") or [])]
        product = argv[0] if argv else "?"
        pattern = f"gws:{product}"
        # Bind the whole argv tail — the doc/file/calendar id lives there (positionally
        # or in --params JSON). A different target document misses and re-asks.
        return pattern, _hash_params(argv[1:]) if len(argv) > 1 else None

    if atype in ("team_task_create", "team_task_move", "schedule_update",
                 "reminder_create", "reminder_cancel"):
        # Internal store writes — blast radius is param-independent, so no bind.
        return atype, None

    # Unknown type: maximally specific fallback (whole-action hash), never over-broad.
    canonical = json.dumps(action, sort_keys=True, ensure_ascii=False, default=str)
    return atype or "?", hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class ApprovalRuleStore:
    """SQLite-backed standing rules for one agent (table inside its `approvals.db`)."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS approval_rules ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  pattern_key TEXT NOT NULL,"
            "  params_hash TEXT,"
            "  scope TEXT NOT NULL,"
            "  created_at TEXT NOT NULL,"
            "  created_by TEXT NOT NULL DEFAULT '',"
            "  last_used_at TEXT,"
            "  use_count INTEGER NOT NULL DEFAULT 0,"
            "  revoked_at TEXT"
            ")"
        )
        self._conn.commit()

    def add_rule(
        self, action: dict[str, Any], *, scope: str, created_by: str = ""
    ) -> ApprovalRule:
        """Learn a standing rule from a real action (CLI derives the key from the row being
        approved/rejected, so the operator never hand-types a pattern). Idempotent per
        (pattern_key, params_hash, scope): a non-revoked duplicate is returned as-is."""
        if scope not in _STANDING_SCOPES:
            raise ValueError(f"scope must be one of {_STANDING_SCOPES}, got {scope!r}")
        pattern_key, params_hash = derive_rule_key(action)
        existing = self._match_row(pattern_key, params_hash, scope)
        if existing is not None:
            return existing
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "INSERT INTO approval_rules "
            "(pattern_key, params_hash, scope, created_at, created_by) VALUES (?, ?, ?, ?, ?)",
            (pattern_key, params_hash, scope, now, created_by),
        )
        self._conn.commit()
        rule = self.get(int(cur.lastrowid))
        assert rule is not None  # just inserted
        return rule

    def match(self, action: dict[str, Any]) -> ApprovalRule | None:
        """The standing decision for this action, or None. Deny wins over always when both
        exist for the same key (safe direction). Revoked rules never match."""
        pattern_key, params_hash = derive_rule_key(action)
        deny = self._match_row(pattern_key, params_hash, SCOPE_DENY)
        if deny is not None:
            return deny
        return self._match_row(pattern_key, params_hash, SCOPE_ALWAYS)

    def _match_row(
        self, pattern_key: str, params_hash: str | None, scope: str
    ) -> ApprovalRule | None:
        # params_hash is compared with IS when None so a NULL-bound internal rule matches
        # a NULL-derived action, and a bound rule matches only the exact destination hash.
        if params_hash is None:
            row = self._conn.execute(
                "SELECT * FROM approval_rules WHERE pattern_key = ? AND params_hash IS NULL "
                "AND scope = ? AND revoked_at IS NULL ORDER BY id LIMIT 1",
                (pattern_key, scope),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM approval_rules WHERE pattern_key = ? AND params_hash = ? "
                "AND scope = ? AND revoked_at IS NULL ORDER BY id LIMIT 1",
                (pattern_key, params_hash, scope),
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def record_use(self, rule_id: int) -> None:
        """Stamp last_used_at + bump use_count when a rule auto-decides (audit trail)."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE approval_rules SET last_used_at = ?, use_count = use_count + 1 "
            "WHERE id = ?",
            (now, rule_id),
        )
        self._conn.commit()

    def is_active(self, rule_id: int) -> bool:
        """True when the rule exists and is not revoked. Callers that hold a rule id across
        a suspension point can re-check with this; `match` already excludes revoked rows, so
        the synchronous match→execute path needs no re-check."""
        row = self._conn.execute(
            "SELECT revoked_at FROM approval_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return row is not None and row[0] is None

    def list_rules(self, *, include_revoked: bool = False) -> list[ApprovalRule]:
        sql = "SELECT * FROM approval_rules"
        if not include_revoked:
            sql += " WHERE revoked_at IS NULL"
        sql += " ORDER BY id"
        return [self._row_to_rule(r) for r in self._conn.execute(sql).fetchall()]

    def get(self, rule_id: int) -> ApprovalRule | None:
        row = self._conn.execute(
            "SELECT * FROM approval_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return self._row_to_rule(row) if row else None

    def revoke(self, rule_id: int) -> bool:
        """Retire a rule (soft delete — keeps the audit row). Returns False if unknown or
        already revoked."""
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE approval_rules SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, rule_id),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def _row_to_rule(self, row: tuple[Any, ...]) -> ApprovalRule:
        return ApprovalRule(
            id=row[0], pattern_key=row[1], params_hash=row[2], scope=row[3],
            created_at=row[4], created_by=row[5], last_used_at=row[6],
            use_count=row[7], revoked_at=row[8],
        )

    def close(self) -> None:
        self._conn.close()
