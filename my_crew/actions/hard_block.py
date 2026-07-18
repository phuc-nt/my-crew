"""Action policy — allowlist + Lớp A hard-deny (PDR §5.2, §7.9).

Two layers with different scopes (v30 trust modes):

  1. **Lớp A hard-deny (checked FIRST, applies in EVERY trust mode)** — permanent
     data loss, credential exfiltration, security incidents. NEVER allowed, even if
     a tool is otherwise allowlisted or the agent runs autonomous. This is the red
     line; `classify()` runs unconditionally in the gateway.
  2. **Allowlist (default-DENY — enforced as a block in GUARDED mode)** — only
     explicitly-listed safe (server, tool) pairs and gh subcommands are permitted;
     everything else classifies NOT_ALLOWLISTED. In guarded mode that is a deny; in
     autonomous mode the gateway lets a NOT_ALLOWLISTED action with a real handler
     run (audited), exactly as it would after a human approval.

Action shapes:
  - MCP tool call:  {"type": "mcp_tool", "server": "confluence", "tool": "deletePage", "args": {}}
  - gh CLI command: {"type": "gh_cli", "argv": ["pr", "list"]}

A false deny is recoverable (operator widens the allowlist). A false allow on the
red line is the worst possible bug, so the design defaults to denial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from my_crew.actions.secret_patterns import contains_secret


class BlockCategory(StrEnum):
    DATA_LOSS = "data_loss"
    CREDENTIAL = "credential"
    SECURITY = "security"
    NOT_ALLOWLISTED = "not_allowlisted"


@dataclass(frozen=True)
class BlockVerdict:
    """Policy result. `blocked=True` means the action is refused."""

    blocked: bool
    category: BlockCategory | None = None
    reason: str = ""


_ALLOW = BlockVerdict(blocked=False)


# --- Lớp B (PDR §7.9): reversible-but-sensitive actions that require a human OK ---
# These are NOT auto-executed even when autonomous; the gateway queues them for
# approval instead. Distinct from Lớp A (never allowed) — these are "ask first".
# Matched by MCP tool name (substring) or gh argv prefix.
_LOP_B_MCP_TOOL_MARKERS = (
    "closeissue",
    "close_issue",
    "transitionissue",  # moving an issue's status is a real workflow change
    "assignissue",
    "reassign",
    # M3-P11 (C3): creating a comment on an external tracker (Linear) is a real,
    # outward-visible write → human approval. Substring-matches linear_createComment;
    # verified NOT to catch jira addComment or confluence createPage.
    "createcomment",
)
_LOP_B_GH_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pr", "merge"),
    ("pr", "close"),
    ("pr", "ready"),
)


@dataclass(frozen=True)
class InterruptVerdict:
    """Result of the Lớp B check. `interrupt=True` => queue for human approval."""

    interrupt: bool
    reason: str = ""


_NO_INTERRUPT = InterruptVerdict(interrupt=False)


def needs_interrupt(
    action: dict[str, Any], *, external_channels: frozenset[str] = frozenset()
) -> InterruptVerdict:
    """Lớp B: does this action need human approval before executing?

    Run by the gateway AFTER Lớp A (hard-deny) passes. Reversible-but-sensitive
    actions (close/merge PR, close/transition/reassign issue) return
    interrupt=True so the gateway queues them.

    Slack posts to an INTERNAL channel are auto-OK (the report flow); a post to a
    channel in `external_channels` (PDR §7.9 "message tới stakeholder external")
    is Lớp B. The gateway passes the configured external set.
    """
    if not isinstance(action, dict):
        return _NO_INTERRUPT
    atype = str(action.get("type", "")).lower()
    if atype == "email_send":
        # Locked policy: EVERY outbound email needs human approval (no domain allowlist,
        # no internal/external split). Reached only after Lớp A passes in classify().
        return InterruptVerdict(True, "Lớp B: gửi email cần người duyệt")
    if atype == "schedule_update":
        # v31 P2: rescheduling changes when the agent acts on its own — sensitive but
        # reversible ⇒ Lớp B. Guarded queues it; autonomous runs it audited (v30 path).
        return InterruptVerdict(True, "Lớp B: đổi lịch chạy cần người duyệt")
    if atype in ("team_task_create", "team_task_move"):
        # v31 P3: creating/moving a team-task card changes shared team state —
        # sensitive but reversible ⇒ Lớp B (guarded queues; autonomous runs audited).
        return InterruptVerdict(True, "Lớp B: thao tác thẻ việc đội cần người duyệt")
    if atype == "gws_write":
        # v31 P4: company Sheets/Docs are INTERNAL assets (not external-channel
        # semantics) — ordinary Lớp B: guarded queues, autonomous runs audited.
        return InterruptVerdict(True, "Lớp B: ghi Google Sheets/Docs cần người duyệt")
    if atype == "mcp_tool":
        tool = str(action.get("tool", "")).lower()
        if any(m in tool for m in _LOP_B_MCP_TOOL_MARKERS):
            return InterruptVerdict(True, f"Lớp B: {tool!r} cần người duyệt")
        # Slack message to an external/stakeholder channel needs approval.
        if "post_message" in tool or "post_message_blocks" in tool:
            channel = str((action.get("args") or {}).get("channel", ""))
            if channel and channel in external_channels:
                return InterruptVerdict(
                    True, f"Lớp B: post tới channel external {channel!r} cần người duyệt"
                )
    elif atype == "gh_cli":
        argv = [str(a).lower() for a in action.get("argv", [])]
        for prefix in _LOP_B_GH_PREFIXES:
            if argv[: len(prefix)] == list(prefix):
                return InterruptVerdict(True, f"Lớp B: gh {' '.join(prefix)} cần người duyệt")
    return _NO_INTERRUPT


# ---------------------------------------------------------------------------
# Allowlist (the safe, reversible writes an agent may perform). Anything not here
# is denied by default (default-DENY). Tool names match case-insensitively.
#
# v3 M5 S4: this is the DEFAULT (PM) allowlist. A domain pack contributes its own
# allowlist (via `pack.allowlist`); the gateway threads it into `classify(...,
# allowlist=...)`. A pack can only ADD permitted tools — it can NEVER widen the
# Lớp A red line (the destructive/security markers below are checked first, in core,
# and are not pack-overridable). When no pack allowlist is passed, this default is
# used, so direct `classify(action)` calls stay byte-identical to pre-v3.
# ---------------------------------------------------------------------------
_DEFAULT_MCP_ALLOWLIST: dict[str, frozenset[str]] = {
    "slack": frozenset({"post_message", "post_message_blocks", "update_message"}),
    # updatepage is allowed but additionally requires a version (checked in hard-deny).
    "confluence": frozenset({"createpage", "updatepage"}),
    "jira": frozenset({"addcomment", "createissue"}),
    # Linear (@tacticlaunch/mcp-linear). The allowlist is the enforced WRITE surface, so
    # only the one write tool is listed — reads bypass the gateway and need no entry.
    # createComment is additionally a Lớp B marker → queued for human approval. Name
    # lowercased because _allowlisted_mcp matches case-insensitively. Destructive Linear
    # tools (delete*/archive*) are NOT listed and hit the Lớp A red line regardless.
    "linear": frozenset({"linear_createcomment"}),
}

#: Back-compat alias — pre-v3 code/tests referenced `_MCP_ALLOWLIST`. Same object.
_MCP_ALLOWLIST = _DEFAULT_MCP_ALLOWLIST


def _normalize_allowlist(
    allowlist: dict[str, frozenset[str]] | dict[str, tuple[str, ...]] | None,
) -> dict[str, frozenset[str]]:
    """Coerce a pack-supplied allowlist (server→names) to lowercased frozensets.

    A pack may declare its allowlist with tuples; normalize so lookups are
    case-insensitive exactly like the default. None ⇒ the default PM allowlist.
    """
    if allowlist is None:
        return _DEFAULT_MCP_ALLOWLIST
    return {
        str(server).lower(): frozenset(str(t).lower() for t in tools)
        for server, tools in allowlist.items()
    }

# gh subcommands allowed, as argv prefixes (read-only + safe creates).
_GH_ALLOWLIST_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pr", "list"),
    ("pr", "view"),
    ("pr", "create"),
    ("issue", "list"),
    ("issue", "view"),
    ("issue", "create"),
    ("issue", "comment"),
    ("repo", "view"),
    ("run", "list"),
    ("run", "view"),
    ("api",),  # read-only GET; mutating verbs are hard-denied below
)


# ---------------------------------------------------------------------------
# Lớp A hard-deny — destructive / security tool-name markers (substring match).
# These deny regardless of allowlist.
# ---------------------------------------------------------------------------
_DATA_LOSS_TOOL_MARKERS = ("delete", "remove", "purge", "destroy", "trash", "archive")
_SECURITY_TOOL_MARKERS = (
    "setpermission",
    "updatepermission",
    "grant",
    "setpublic",
    "makepublic",
    "setvisibility",
    "setrestriction",
    "addrestriction",
    "invite",
    "addmember",
    "updateprojectrole",
    "updaterole",
)

# gh argv prefixes that are categorically destructive (irreversible).
_GH_DATA_LOSS_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("repo", "delete"),
    ("release", "delete"),
    ("cache", "delete"),
    ("issue", "delete"),
    ("gist", "delete"),
    ("secret", "delete"),
    ("ssh-key", "delete"),
)
# gh flags that signal a forced/irreversible operation (exact-token match).
_GH_DANGEROUS_FLAGS = frozenset({"--force", "--delete-branch", "--confirm", "--yes"})
# Mutating HTTP verbs for `gh api`.
_HTTP_MUTATING_VERBS = frozenset({"post", "put", "patch", "delete"})
# `gh api` field flags: their presence makes the request an implicit POST (a write)
# unless an explicit GET method is given. Source: gh-api manual.
_GH_API_FIELD_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})
_HTTP_READ_VERBS = frozenset({"get", "head"})


def _flatten_strings(value: Any) -> list[str]:
    """Collect all string leaves from a nested structure."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten_strings(v))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_flatten_strings(v))
        return out
    return []


def _credential_verdict(payload: Any) -> BlockVerdict | None:
    """Block if any secret (keyed or free-text pattern) appears in the payload."""
    found = contains_secret(payload)
    if found:
        return BlockVerdict(blocked=True, category=BlockCategory.CREDENTIAL, reason=found)
    return None


def _security_verdict(tool: str, args: Any) -> BlockVerdict | None:
    """Block visibility/permission changes (making things public, granting access)."""
    if any(m in tool for m in _SECURITY_TOOL_MARKERS):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason=f"tool {tool!r} changes permissions/visibility",
        )
    flat = " ".join(_flatten_strings(args)).lower()
    if "public" in flat or "anonymous" in flat or "everyone" in flat:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason="action would expose content publicly",
        )
    return None


def _valid_version(value: Any) -> bool:
    """True only for a positive integer version. Rejects bool/str/None/garbage.

    `"0"`, `-1`, `"abc"`, `True`, `[]` are NOT valid — accepting them would let a
    silent/unversioned Confluence overwrite through.
    """
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        return False
    try:
        return int(value) >= 1
    except (TypeError, ValueError):
        return False


def _hard_deny_mcp(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks for an MCP tool call. None = no red-line match."""
    tool = str(action.get("tool", "")).lower()
    args = action.get("args", {})

    # Scan args AND any sibling string fields (e.g. dedup_hint) so a secret can
    # never ride along in a non-args key. The whole action is the credential surface.
    cred = _credential_verdict(args)
    if cred:
        return cred
    siblings = {k: v for k, v in action.items() if k not in ("type", "server", "tool", "args")}
    cred = _credential_verdict(siblings)
    if cred:
        return cred

    if any(m in tool for m in _DATA_LOSS_TOOL_MARKERS):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason=f"tool {tool!r} is destructive (data loss)",
        )

    # Unversioned Confluence overwrite = silent destructive write. A valid
    # version is a positive integer (Confluence optimistic lock); reject blanks,
    # zero/negative, strings like "0", bools, and non-numeric junk.
    if "updatepage" in tool or "update_page" in tool:
        version = args.get("version") if isinstance(args, dict) else None
        if not _valid_version(version):
            return BlockVerdict(
                blocked=True,
                category=BlockCategory.DATA_LOSS,
                reason="updatePage requires a positive integer version (unversioned overwrite)",
            )

    sec = _security_verdict(tool, args)
    if sec:
        return sec
    return None


def confined_xlsx_path(attachment_path: Any, artifact_root: Path | None) -> str:
    """Resolve an attachment path IFF it is a real .xlsx confined to `artifact_root`.

    The one confinement rule, shared by Lớp A (`_attachment_verdict`) and the send-time
    handler re-check, so the two can never drift. `resolve()` dereferences symlinks, so a
    symlink INSIDE the dir pointing OUT lands its real target outside the root and is
    rejected. Raises `ValueError` on any violation; returns the reason via the message so
    the caller can turn it into either a `BlockVerdict` or a send-time refusal.

    An attachment is a file the agent generated itself (an .xlsx report), never an
    LLM-supplied arbitrary path — so the only legal source is inside the artifact dir.
    """
    if artifact_root is None:
        raise ValueError("email attachment present but artifact root unknown (fail-closed)")
    if not isinstance(attachment_path, str) or not attachment_path.strip():
        raise ValueError("email attachment path is not a valid string")

    resolved = Path(attachment_path).resolve()
    if not resolved.is_relative_to(artifact_root.resolve()):
        raise ValueError("email attachment is outside the artifact dir")
    if resolved.suffix != ".xlsx":
        raise ValueError("email attachment is not an .xlsx report")
    if not resolved.is_file():
        raise ValueError("email attachment file does not exist")
    return str(resolved)


def _attachment_verdict(
    attachment_path: Any, artifact_root: Path | None
) -> BlockVerdict | None:
    """Lớp A confinement verdict for an email attachment. None = ok/absent.

    Anything outside `artifact_root` — a traversal (`../`), an absolute path elsewhere
    (`/etc/passwd`), an in-dir symlink pointing out, a non-existent file, a non-.xlsx —
    is a security red line: the email would carry a file the agent was never meant to
    send out. Fail-closed: a present attachment with no artifact root is denied.
    """
    if attachment_path is None:
        return None
    try:
        confined_xlsx_path(attachment_path, artifact_root)
    except ValueError as exc:
        return BlockVerdict(blocked=True, category=BlockCategory.SECURITY, reason=str(exc))
    return None


def _hard_deny_email(
    action: dict[str, Any], artifact_root: Path | None = None
) -> BlockVerdict | None:
    """Lớp A checks for an outbound email send. None = no red-line match.

    Scans recipient + subject + body (and any attachment path) for secrets — a
    credential must never ride out in an email — and rejects a structurally invalid
    send (no recipient, empty body). When an attachment is present it MUST be confined
    to the agent's artifact dir (see `_attachment_verdict`). A valid send returns None
    (allowed past Lớp A) and is then ALWAYS queued for human approval (`needs_interrupt`).
    """
    to = action.get("to")
    subject = action.get("subject", "")
    body = action.get("body", "")
    attachment_path = action.get("attachment_path")

    cred = _credential_verdict(
        {"to": to, "subject": subject, "body": body, "attachment_path": attachment_path}
    )
    if cred:
        return cred

    attach = _attachment_verdict(attachment_path, artifact_root)
    if attach:
        return attach

    if not (isinstance(to, str) and to.strip()) and not (
        isinstance(to, (list, tuple)) and any(str(r).strip() for r in to)
    ):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.NOT_ALLOWLISTED,
            reason="email_send has no recipient",
        )
    if not str(body).strip():
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.NOT_ALLOWLISTED,
            reason="email_send has an empty body",
        )
    return None


# --- schedule_update (v31 P2): an agent re-scheduling ITS OWN reports ---
#: Cron floor: no schedule entry may fire faster than this (an LLM must not be able to
#: turn an agent into a per-minute spam loop / burn the budget).
_SCHEDULE_MIN_INTERVAL_S = 300
#: Cap on schedule entries carried by one update payload AND on the merged profile map
#: (the handler re-enforces the merged side).
_SCHEDULE_MAX_ENTRIES = 6


def cron_floor_error(cron: Any) -> str | None:
    """Reason string when `cron` is not a valid 5-field expression or fires faster than
    the floor; None when acceptable. Shared by Lớp A (`_hard_deny_schedule_update`) and
    the write handler's re-enforcement (schedule_write) so the two can never drift.

    The interval is measured over consecutive fire times from a FIXED base so the
    verdict is deterministic (a policy answer must not depend on when it is asked).
    """
    from datetime import datetime

    from croniter import croniter

    if not isinstance(cron, str) or not cron.strip():
        return "schedule cron must be a non-empty string"
    if not croniter.is_valid(cron):
        return f"invalid cron expression {cron!r}"
    try:
        it = croniter(cron, datetime(2026, 1, 1, 0, 0))
        prev = it.get_next(datetime)
        for _ in range(5):
            nxt = it.get_next(datetime)
            if (nxt - prev).total_seconds() < _SCHEDULE_MIN_INTERVAL_S:
                return (
                    f"cron {cron!r} fires faster than every "
                    f"{_SCHEDULE_MIN_INTERVAL_S // 60} minutes (floor)"
                )
            prev = nxt
    except Exception:  # noqa: BLE001 — e.g. a never-firing date (Feb 30): a policy
        # verdict must be a reason string at every gateway door, never an exception.
        return f"cron {cron!r} never fires or cannot be evaluated"
    return None


def _hard_deny_schedule_update(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks for a self-schedule change. None = no red-line match.

    Structural/floor violations are HARD categories (SECURITY), never NOT_ALLOWLISTED:
    in autonomous mode a NOT_ALLOWLISTED block with a real handler is re-entered
    `approved=True` and would be bypassed — the chat door denies it, but the
    `execute()`/`approve()` doors would not. A hard category holds at every door.
    Identity is NOT read here (and not carried by the payload at all): the handler is
    a closure over the agent's own profile id, so there is nothing to validate.
    """
    cred = _credential_verdict(action)
    if cred:
        return cred
    schedule = action.get("schedule")
    if not isinstance(schedule, dict) or not schedule:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason="schedule_update must carry a non-empty {kind: cron} mapping",
        )
    if len(schedule) > _SCHEDULE_MAX_ENTRIES:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason=f"schedule_update carries more than {_SCHEDULE_MAX_ENTRIES} entries",
        )
    for kind, cron in schedule.items():
        if not isinstance(kind, str) or not kind.strip():
            return BlockVerdict(
                blocked=True,
                category=BlockCategory.SECURITY,
                reason="schedule kind must be a non-empty string",
            )
        err = cron_floor_error(cron)
        if err:
            return BlockVerdict(blocked=True, category=BlockCategory.SECURITY, reason=err)
    return None


# --- gws_write (v31 P4): Google Sheets/Docs writes via the `gws` CLI ---
#: The ONLY gws invocations an agent may make, as argv prefixes (mirrors the gh model).
#: Real gws 0.13.2 syntax (pre-flight verified): helper subcommands carry a `+`.
#: Gmail is deliberately ABSENT — outbound mail goes through the `email_send` type
#: (its own Lớp A/B policy + SMTP handler), never through a second door.
_GWS_ALLOWLIST_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("sheets", "+append"),
    ("docs", "documents", "create"),
    ("docs", "+write"),
    # v39 #3: create a Google Calendar event. Reversible-but-sensitive ⇒ ordinary Lớp B
    # (guarded queues, autonomous runs audited). Calendar delete/acl-share are caught by
    # the destructive/permission marker scan above, so they never reach this allowlist.
    ("calendar", "events", "insert"),
)
#: Destructive/permission verbs anywhere in a gws argv = Lớp A, both trust modes.
_GWS_DATA_LOSS_MARKERS = ("delete", "clear", "trash", "batchclear")
_GWS_SECURITY_MARKERS = ("share", "permission", "permissions", "publish", "acl")


def _hard_deny_gws(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks for a gws CLI write. None = allowed past the red line.

    EVERYTHING here is a hard category (F1): unlike `gh_cli` (whose allowlist miss is
    NOT_ALLOWLISTED and may be human-approved), the gws surface is a fixed 3-prefix
    table — an argv outside it is a policy violation, not a queue candidate, because in
    autonomous mode a NOT_ALLOWLISTED deny with a real handler would be re-entered
    `approved=True` and executed.

    The destructive/permission markers scan EVERY argv token, including content values
    ("--values 'delete old records'" is denied). That is a deliberate fail-closed false
    positive: content wording can be rephrased; a missed destructive verb cannot be
    undone.
    """
    argv_raw = action.get("argv", [])
    argv_raw = [str(a) for a in argv_raw] if isinstance(argv_raw, (list, tuple)) else []
    argv = [a.lower() for a in argv_raw]

    cred = _credential_verdict(action)
    if cred:
        return cred
    if not argv:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason="gws_write must carry a non-empty argv",
        )
    for marker_set, category, label in (
        (_GWS_DATA_LOSS_MARKERS, BlockCategory.DATA_LOSS, "destructive"),
        (_GWS_SECURITY_MARKERS, BlockCategory.SECURITY, "permission/visibility"),
    ):
        for tok in argv:
            if any(m in tok for m in marker_set):
                return BlockVerdict(
                    blocked=True,
                    category=category,
                    reason=f"gws argv contains a {label} verb ({tok!r})",
                )
    if not _matches_any_prefix(argv, _GWS_ALLOWLIST_PREFIXES):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason=f"gws subcommand {' '.join(argv[:3])!r} is outside the fixed prefix table",
        )
    return None


# --- team_task_create / team_task_move (v31 P3): kanban card actions ---
_TEAM_TASK_TITLE_MAX = 200
#: Task ids are coordinator-minted hex (uuid4[:12]) — bound the shape so a payload
#: cannot smuggle structured junk through the id field.
_TEAM_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_AGENT_ID_SHAPE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _hard_deny_team_task(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks shared by the two kanban card types. None = no red-line match.

    Structural denies are HARD (SECURITY), never NOT_ALLOWLISTED — same F1 posture as
    `schedule_update`: they must hold at the `execute()`/approve doors too, not only at
    the chat door. Store-verified PERMISSIONS (assignee ∈ roster, actor may move this
    task) live in the write handler — they need the store and the actor closure, which
    policy code deliberately does not have.
    """
    cred = _credential_verdict(action)
    if cred:
        return cred
    atype = str(action.get("type", "")).lower()

    def _deny(reason: str) -> BlockVerdict:
        return BlockVerdict(blocked=True, category=BlockCategory.SECURITY, reason=reason)

    if atype == "team_task_create":
        title = action.get("title")
        if not isinstance(title, str) or not title.strip():
            return _deny("team_task_create must carry a non-empty title")
        if len(title) > _TEAM_TASK_TITLE_MAX:
            return _deny(f"team_task_create title exceeds {_TEAM_TASK_TITLE_MAX} chars")
        assignee = action.get("assignee")
        if not isinstance(assignee, str) or not _AGENT_ID_SHAPE_RE.match(assignee):
            return _deny("team_task_create assignee must be a valid agent id")
        return None

    task_id = action.get("task_id")
    if not isinstance(task_id, str) or not _TEAM_TASK_ID_RE.match(task_id):
        return _deny("team_task_move task_id has an invalid shape")
    status = action.get("status")
    from my_crew.runtime.team_task_store import _TASK_STATUSES

    if status not in _TASK_STATUSES:
        return _deny(f"team_task_move status must be one of {_TASK_STATUSES}")
    return None


def _hard_deny_telegram(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks for a telegram send (v6 M13). None = no red-line match.

    Scans chat_id + text for secrets (a credential must never ride out in a message) and
    rejects a structurally invalid send (no chat_id, empty text). A valid send is allowed
    past Lớp A and executes DIRECTLY (no Lớp B): the destination set is the agent's
    operator-declared `chat_ids` — the same trust level as an internal Slack channel —
    and the send handler refuses any chat outside that set at execution time.
    """
    chat_id = action.get("chat_id")
    text = action.get("text", "")

    cred = _credential_verdict({"chat_id": chat_id, "text": text})
    if cred:
        return cred

    if not str(chat_id or "").strip():
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.NOT_ALLOWLISTED,
            reason="telegram_send has no chat_id",
        )
    if not str(text).strip():
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.NOT_ALLOWLISTED,
            reason="telegram_send has an empty text",
        )
    return None


def _argv_lower(action: dict[str, Any]) -> list[str]:
    argv = action.get("argv", [])
    if not isinstance(argv, (list, tuple)):
        return []
    return [str(a).lower() for a in argv]


def _has_prefix(argv: list[str], prefix: tuple[str, ...]) -> bool:
    return argv[: len(prefix)] == list(prefix)


def _matches_any_prefix(argv: list[str], prefixes: tuple[tuple[str, ...], ...]) -> bool:
    return any(_has_prefix(argv, p) for p in prefixes)


def _explicit_http_method(argv_lower: list[str]) -> str | None:
    """Return the explicit HTTP verb from -X/--method (any spelling), else None."""
    for i, tok in enumerate(argv_lower):
        if tok in ("-x", "--method") and i + 1 < len(argv_lower):
            return argv_lower[i + 1]
        if tok.startswith("--method="):
            return tok.split("=", 1)[1]
        if tok.startswith("-x") and len(tok) > 2:  # glued: -XPOST / -xdelete
            return tok[2:]
    return None


def _gh_api_verdict(argv_raw: list[str]) -> BlockVerdict | None:
    """Block writes via `gh api`: explicit mutating verb OR implicit POST.

    `gh api` defaults to GET, but becomes POST whenever a field flag
    (-f/-F/--field/--raw-field/--input) is present unless an explicit read
    method is given. Field flags are case-sensitive (-f vs -F), so the RAW
    (original-case) argv is required here.
    """
    argv_lower = [a.lower() for a in argv_raw]
    method = _explicit_http_method(argv_lower)
    if method in _HTTP_MUTATING_VERBS:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason=f"gh api with mutating verb {method.upper()}",
        )
    # Implicit POST: a field flag with no explicit read method = a write.
    has_field = any(tok in _GH_API_FIELD_FLAGS for tok in argv_raw)
    if has_field and method not in _HTTP_READ_VERBS:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason="gh api with field params is an implicit POST (write)",
        )
    return None


def _hard_deny_gh(action: dict[str, Any]) -> BlockVerdict | None:
    """Lớp A checks for a gh command. None = no red-line match."""
    argv_raw = action.get("argv", [])
    argv_raw = [str(a) for a in argv_raw] if isinstance(argv_raw, (list, tuple)) else []
    argv = _argv_lower(action)

    cred = _credential_verdict(argv)
    if cred:
        return cred

    if _matches_any_prefix(argv, _GH_DATA_LOSS_PREFIXES):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason="gh subcommand is an irreversible delete",
        )

    if any(flag in _GH_DANGEROUS_FLAGS for flag in argv):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason="gh command carries a forced/irreversible flag",
        )

    # `gh api` writes: explicit verb (separated/glued/equals) OR implicit POST.
    if _has_prefix(argv, ("api",)):
        api_verdict = _gh_api_verdict(argv_raw)
        if api_verdict:
            return api_verdict

    # Visibility/permission changes via repo edit or explicit public flag.
    joined = " ".join(argv)
    if ("--visibility" in joined and "public" in joined) or "public" in argv:
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.SECURITY,
            reason="gh command changes repository visibility to public",
        )

    # Force-push in any form (flag, short flag, or +refspec).
    if "push" in argv and (
        "--force" in joined
        or "-f" in argv
        or any(tok.startswith("+") for tok in argv)
        or "--force-with-lease" in argv
    ):
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.DATA_LOSS,
            reason="force-push detected",
        )
    return None


def _allowlisted_mcp(
    action: dict[str, Any], allowlist: dict[str, frozenset[str]] | None = None
) -> bool:
    server = str(action.get("server", "")).lower()
    tool = str(action.get("tool", "")).lower()
    table = allowlist if allowlist is not None else _DEFAULT_MCP_ALLOWLIST
    return tool in table.get(server, frozenset())


def _allowlisted_gh(action: dict[str, Any]) -> bool:
    return _matches_any_prefix(_argv_lower(action), _GH_ALLOWLIST_PREFIXES)


def classify(
    action: dict[str, Any],
    *,
    allowlist: dict[str, frozenset[str]] | dict[str, tuple[str, ...]] | None = None,
    artifact_root: Path | None = None,
) -> BlockVerdict:
    """Decide whether an action may proceed.

    Order: Lớp A hard-deny first (the red line, never overridable), then the
    default-DENY allowlist. Returns a blocked verdict with category + reason, or
    an allow verdict only for explicitly-permitted, non-red-line actions.

    `allowlist` (v3 M5 S4) is the active domain pack's permitted MCP server→tool
    map. None ⇒ the default PM allowlist (byte-identical pre-v3). It governs ONLY
    the default-DENY layer; the Lớp A hard-deny above is core and not pack-overridable,
    so a pack can never permit a destructive/security action by listing it.
    """
    if not isinstance(action, dict):
        raise TypeError(f"action must be a dict, got {type(action).__name__}")

    mcp_allowlist = _normalize_allowlist(allowlist)
    action_type = str(action.get("type", "")).lower()

    # Layer 1: Lớp A hard-deny (defense-in-depth, checked before allowlist).
    if action_type == "mcp_tool":
        denied = _hard_deny_mcp(action)
    elif action_type == "gh_cli":
        denied = _hard_deny_gh(action)
    elif action_type == "email_send":
        # Email is a native gateway action type (no email MCP server). Lớp A scans the
        # recipient/subject/body for secrets and rejects an empty recipient/body; a
        # well-formed send is allowed past Lớp A, then ALWAYS queued Lớp B (needs_interrupt).
        denied = _hard_deny_email(action, artifact_root)
        if denied:
            return denied
        return _ALLOW
    elif action_type == "telegram_send":
        # Telegram (v6 M13) is likewise a native gateway action type. Lớp A scans for
        # secrets + structural validity; a valid send executes directly (internal-only
        # by construction — see _hard_deny_telegram + the handler's chat allowlist).
        denied = _hard_deny_telegram(action)
        if denied:
            return denied
        return _ALLOW
    elif action_type == "schedule_update":
        # v31 P2: native self-reschedule. Lớp A scans secrets + structure + cron floor
        # (all HARD categories); a valid update is allowed past Lớp A, then Lớp B-queued
        # in guarded mode (needs_interrupt) / run audited in autonomous. The write
        # handler re-enforces everything again before touching profile.yaml.
        denied = _hard_deny_schedule_update(action)
        if denied:
            return denied
        return _ALLOW
    elif action_type in ("team_task_create", "team_task_move"):
        # v31 P3: kanban card actions. Lớp A scans secrets + structure (hard
        # categories); permissions (assignee ∈ roster, actor may move THIS task) are
        # store-verified in the write handler with the actor's closure identity.
        denied = _hard_deny_team_task(action)
        if denied:
            return denied
        return _ALLOW
    elif action_type == "gws_write":
        # v31 P4: Sheets/Docs write via the gws CLI. The 3-prefix table + destructive
        # verb scan are ALL hard categories (see _hard_deny_gws); a clean argv is
        # allowed past Lớp A then Lớp B-gated (internal company asset).
        denied = _hard_deny_gws(action)
        if denied:
            return denied
        return _ALLOW
    else:
        # Unknown type: still scan for secrets, then deny (not allowlisted).
        denied = _credential_verdict(action.get("args", action.get("argv", action)))
        if denied:
            return denied
        return BlockVerdict(
            blocked=True,
            category=BlockCategory.NOT_ALLOWLISTED,
            reason=f"unknown action type {action_type!r} is denied by default",
        )
    if denied:
        return denied

    # Layer 2: default-DENY allowlist (pack-contributed for MCP; gh stays core).
    allowed = (
        _allowlisted_mcp(action, mcp_allowlist)
        if action_type == "mcp_tool"
        else _allowlisted_gh(action)
    )
    if allowed:
        return _ALLOW
    label = action.get("tool") if action_type == "mcp_tool" else " ".join(_argv_lower(action)[:3])
    return BlockVerdict(
        blocked=True,
        category=BlockCategory.NOT_ALLOWLISTED,
        reason=f"action {label!r} is not on the allowlist (default deny)",
    )
