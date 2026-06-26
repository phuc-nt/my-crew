"""Action policy — allowlist + Lớp A hard-deny (PDR §5.2, §7.9).

For "full autonomous write", an enumerate-the-bad denylist is unsafe: it permits
anything not yet listed, and the unlisted set is unbounded. So the gateway uses a
default-DENY allowlist, with the Lớp A red line as a second hard-deny layer on top
(defense-in-depth):

  1. **Lớp A hard-deny (checked FIRST)** — permanent data loss, credential
     exfiltration, security incidents. NEVER allowed, even if a tool is otherwise
     allowlisted. This is the red line.
  2. **Allowlist** — only explicitly-listed safe (server, tool) pairs and gh
     subcommands are permitted. Everything else is denied by default.

Action shapes:
  - MCP tool call:  {"type": "mcp_tool", "server": "confluence", "tool": "deletePage", "args": {}}
  - gh CLI command: {"type": "gh_cli", "argv": ["pr", "list"]}

A false deny is recoverable (operator widens the allowlist). A false allow on the
red line is the worst possible bug, so the design defaults to denial.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.actions.secret_patterns import contains_secret


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
# Allowlist (Phase 0 — the safe, reversible writes the agent may perform).
# Phase 1 widens this deliberately as real handlers land. Anything not here is
# denied by default. Tool names are matched case-insensitively.
# ---------------------------------------------------------------------------
_MCP_ALLOWLIST: dict[str, frozenset[str]] = {
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


def _allowlisted_mcp(action: dict[str, Any]) -> bool:
    server = str(action.get("server", "")).lower()
    tool = str(action.get("tool", "")).lower()
    return tool in _MCP_ALLOWLIST.get(server, frozenset())


def _allowlisted_gh(action: dict[str, Any]) -> bool:
    return _matches_any_prefix(_argv_lower(action), _GH_ALLOWLIST_PREFIXES)


def classify(action: dict[str, Any]) -> BlockVerdict:
    """Decide whether an action may proceed.

    Order: Lớp A hard-deny first (the red line, never overridable), then the
    default-DENY allowlist. Returns a blocked verdict with category + reason, or
    an allow verdict only for explicitly-permitted, non-red-line actions.
    """
    if not isinstance(action, dict):
        raise TypeError(f"action must be a dict, got {type(action).__name__}")

    action_type = str(action.get("type", "")).lower()

    # Layer 1: Lớp A hard-deny (defense-in-depth, checked before allowlist).
    if action_type == "mcp_tool":
        denied = _hard_deny_mcp(action)
    elif action_type == "gh_cli":
        denied = _hard_deny_gh(action)
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

    # Layer 2: default-DENY allowlist.
    allowed = _allowlisted_mcp(action) if action_type == "mcp_tool" else _allowlisted_gh(action)
    if allowed:
        return _ALLOW
    label = action.get("tool") if action_type == "mcp_tool" else " ".join(_argv_lower(action)[:3])
    return BlockVerdict(
        blocked=True,
        category=BlockCategory.NOT_ALLOWLISTED,
        reason=f"action {label!r} is not on the allowlist (default deny)",
    )
