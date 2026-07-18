"""Trust-ladder policy: may this Lớp B action run WITHOUT waiting for a human? (v8 M23)

The first relaxation of execution authority since v1 — and it stays inside the invariant:
this decides ONLY whether a Lớp B (reversible-but-sensitive) action skips the human queue.
Lớp A hard-deny, the allowlist, the kill-switch and dry-run are re-applied downstream (the
auto path re-enters the gateway with `approved=True`), so nothing here can loosen them.

Two origins, both gated:
- SCHEDULED (a cron report / assigned task): auto-OK only for an action-type the profile
  turned on, to a destination the grant names, and only while the day's cap has a free slot.
- CHAT (a Telegram/Slack mention issuing a command): additionally requires the sender to be
  in `trusted_senders` — a TELEGRAM DM from a specific, immutable user id. A stranger, a group
  chat, or a non-Telegram transport never auto-approves (falls back to the human queue).

The daily cap is a RESERVATION (DedupStore.claim), not a read-then-act count — atomic, durable
across restart, safe across processes. A consumed slot that then fails is not refunded (the
safe direction: repeated failure exhausts the cap and falls back to a human).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.actions.dedup_store import DedupStore

#: The audit/run-event rationale prefix that marks an auto-approved action. ONE definition —
#: the UI "đã tự duyệt" list and any counting key off this exact string (red-team M3: it is a
#: DISPLAY marker, never the enforcement mechanism — the cap is the claim slot).
RATIONALE_PREFIX = "auto_approve:"


@dataclass(frozen=True)
class AutoApproveDecision:
    allowed: bool
    rationale: str = ""  # "auto_approve:scheduled:<type>" / "auto_approve:trusted_sender:<id>"
    reason: str = ""     # why NOT allowed (for logging) when allowed is False


def _action_semantic_type(action: dict[str, Any]) -> str | None:
    """Map a gateway action to the config action-type key, or None if unclassifiable.

    `slack_post` = an mcp_tool posting a Slack message; `email_send` = an email. Only the
    types the trust ladder knows are returned; anything else ⇒ never auto (None)."""
    atype = str(action.get("type", "")).lower()
    if atype == "email_send":
        return "email_send"
    if atype == "mcp_tool":
        tool = str(action.get("tool", "")).lower()
        if "post_message" in tool:
            return "slack_post"
    return None


def _action_destination(action: dict[str, Any], semantic_type: str) -> str:
    """The destination the grant is bound to (red-team M5): the Slack channel / the email
    recipient. Empty string when absent (a grant with a channel list then won't match)."""
    args = action.get("args") or {}
    if semantic_type == "slack_post":
        return str(args.get("channel") or "")
    if semantic_type == "email_send":
        return str(action.get("to") or args.get("to") or "")
    return ""


def evaluate(
    action: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    origin: str,                      # "scheduled" | "chat"
    sender_id: str = "",              # chat origin: the immutable sender user id
    transport: str = "",              # chat origin: "telegram" | "slack" | ...
    chat_id: str = "",                # chat origin: the chat the message came from
) -> AutoApproveDecision:
    """Decide whether `action` may auto-approve. Pure — no I/O, no cap reservation (the caller
    claims the slot only AFTER this says allowed, so a denied action never burns a slot)."""
    if not config:
        return AutoApproveDecision(False, reason="auto_approve tắt")
    stype = _action_semantic_type(action)
    if stype is None:
        return AutoApproveDecision(False, reason="loại hành động không hỗ trợ auto")

    grant = (config.get("actions") or {}).get(stype)
    if not grant or not grant.get("enabled"):
        return AutoApproveDecision(False, reason=f"{stype} chưa bật auto")

    # Destination-bound (red-team M5): the grant only covers the channels/recipients it names.
    allowed_dests = grant.get("channels") if stype == "slack_post" else grant.get("recipients")
    dest = _action_destination(action, stype)
    if allowed_dests is not None and dest not in set(allowed_dests):
        return AutoApproveDecision(False, reason=f"đích {dest!r} ngoài phạm vi được cấp")

    if origin == "chat":
        # Chat origin adds the trusted-sender gate: TELEGRAM DM only, sender in the allowlist
        # (red-team M4). A Telegram DM has chat_id == the sender's user id. Require BOTH ids
        # present AND equal — never skip the DM binding when either is blank (defense-in-depth).
        if transport != "telegram":
            return AutoApproveDecision(False, reason="chat auto chỉ áp dụng Telegram")
        if not sender_id or not chat_id or str(chat_id) != str(sender_id):
            return AutoApproveDecision(False, reason="chat auto chỉ áp dụng DM riêng")
        trusted = ((config.get("trusted_senders") or {}).get("telegram")) or []
        if str(sender_id) not in {str(s) for s in trusted}:
            return AutoApproveDecision(False, reason="người gửi không trong danh sách tin cậy")
        return AutoApproveDecision(True, rationale=f"{RATIONALE_PREFIX}trusted_sender:{sender_id}")

    if origin == "scheduled":
        return AutoApproveDecision(True, rationale=f"{RATIONALE_PREFIX}scheduled:{stype}")

    return AutoApproveDecision(False, reason=f"origin không hỗ trợ: {origin!r}")


def claim_daily_slot(
    dedup: DedupStore, action: dict[str, Any], config: dict[str, Any], *, now: datetime
) -> bool:
    """Reserve one of today's auto slots for this action-type (red-team M1). Atomic + durable:
    tries `auto-slot:<type>:<local-date>:<seq>` for seq 1..max_per_day and claims the first
    free one. Returns True if a slot was reserved, False if the cap is exhausted (⇒ fall back
    to the human queue). LOCAL date so the reset matches the scheduler + the CEO's clock
    (red-team M2). A consumed slot is not released on later failure — the safe direction."""
    stype = _action_semantic_type(action)
    if stype is None:
        return False
    grant = (config.get("actions") or {}).get(stype) or {}
    max_per_day = int(grant.get("max_per_day", 0))
    if max_per_day <= 0:
        return False
    local_date = now.astimezone().date().isoformat()
    for seq in range(1, max_per_day + 1):
        if dedup.claim(f"auto-slot:{stype}:{local_date}:{seq}"):
            return True
    return False
