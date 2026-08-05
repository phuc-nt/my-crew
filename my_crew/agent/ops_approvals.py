"""Approve / reject a queued Lớp B action from chat (v69).

Chat is the THIRD surface on this queue, after the CLI and the web banner. It calls
the same `gw.approve` / `gw.reject` + `make_agent_bound_dispatch` path the CLI does
(`mpm_manage_cmds._approve`) — there is no second approval road, because a second
road is a second place for Lớp A to be wrong.

Three properties this module exists to hold:

**Binding at preview, not at confirm.** The `(agent_id, approval_id)` pair the CEO is
shown is the pair that gets executed. The v64 H1 lesson was a command that re-resolved
"the newest row" at confirm time and acted on a row that arrived in between; here the
ids ride in the draft slots, so a push landing mid-conversation cannot move the target.

**A standing rule needs a scope sentence, not a hash.** `derive_rule_key` binds a
recipient domain / repo / chat id, and `params_hash` is a blind digest — showing it
would be theater. The preview renders what the rule will actually cover in words, and
refuses `always`/`deny` entirely when the action can only be summarized as a stub.

**A lost race is its own outcome.** Three surfaces means the row may already be
decided. That is reported as its own message and, critically, never learns a rule —
teaching a standing rule from a decision another surface made is teaching blind.
"""

from __future__ import annotations

import logging

from my_crew.actions.action_gateway import HardBlockedError
from my_crew.actions.approval_rule_store import (
    SCOPE_ALWAYS,
    SCOPE_DENY,
    derive_rule_key,
    email_domains,
    mcp_destination,
)
from my_crew.actions.approval_summary import is_stub_summary, summarize_action
from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.agent_state_reader import read_pending_actions

logger = logging.getLogger(__name__)

#: Scope words the CEO may type. `once` is the plain decision; `always`/`deny` also
#: teach a standing rule. Kept as a small vocabulary rather than free text so a typo
#: can never silently escalate a one-off into a permanent rule.
_SCOPE_ONCE = "once"
_ALWAYS_WORDS = frozenset({"always", "luôn", "luon", "luôn luôn", "tự duyệt", "tu duyet"})
_DENY_WORDS = frozenset({"deny", "chặn", "chan", "chặn hẳn", "chan han", "cấm", "cam"})


def _normalize_scope(raw: str) -> str:
    """`once` | `always` | `deny` from what the CEO typed. Unknown ⇒ `once`.

    Defaulting an unrecognized word to `once` is deliberate: the failure direction of
    a misread scope must be "decided this one row", never "created a standing rule".
    """
    word = (raw or "").strip().lower()
    if not word:
        return _SCOPE_ONCE
    if word in _ALWAYS_WORDS:
        return SCOPE_ALWAYS
    if word in _DENY_WORDS:
        return SCOPE_DENY
    return _SCOPE_ONCE


def _enabled_agent_ids() -> list[str]:
    """Agent ids the registry actually serves.

    The `agent_id` slot is operator-typed, so it is validated against the registry
    rather than trusted: an unregistered id must not reach `load_profile` and mint a
    data dir for an agent that does not exist.
    """
    from my_crew.runtime.registry import load_registry

    ids = []
    for entry in load_registry():
        if getattr(entry, "enabled", True):
            ids.append(entry.id)
    return ids


def _require_agent(agent_id: str) -> str:
    agent = (agent_id or "").strip()
    if not agent:
        raise ValueError("thiếu mã agent — nói rõ việc chờ duyệt của agent nào")
    known = _enabled_agent_ids()
    if agent not in known:
        raise ValueError(
            f"không có agent `{agent}` đang bật — các agent hiện có: {', '.join(known)}"
        )
    return agent


def _find_pending(agent_id: str, approval_id: int) -> dict | None:
    """The pending row, read read-only. None when it is gone or already decided.

    Returning None rather than raising lets each caller say the true thing: at PREVIEW a
    missing row means the CEO named an id that isn't waiting (bad input, ask again); at
    CONFIRM it means another surface decided it between the two steps (a lost race, which
    is nobody's mistake).
    """
    rows = read_pending_actions(agent_data_dir(agent_id))
    for row in rows:
        if int(row["id"]) == approval_id:
            return row
    return None


def _require_pending(agent_id: str, approval_id: int) -> dict:
    """The pending row for the PREVIEW step; refuses when the id names nothing waiting."""
    row = _find_pending(agent_id, approval_id)
    if row is None:
        raise ValueError(
            f"việc chờ duyệt #{approval_id} của `{agent_id}` không còn ở trạng thái chờ "
            "— có thể đã được xử lý ở web/CLI trước đó"
        )
    return row


def _scope_sentence(action: dict, scope: str) -> str:
    """What a standing rule would ACTUALLY cover, in words the CEO can judge.

    Mirrors the binding `derive_rule_key` computes. Never renders `params_hash`: a
    hash tells the operator nothing, so consenting to it is consenting blind. Where
    the key binds nothing (`params_hash is None`), the sentence says so explicitly —
    that is the broad case and it is exactly the one the CEO must see clearly.
    """
    verb = "TỰ DUYỆT" if scope == SCOPE_ALWAYS else "TỰ TỪ CHỐI"
    atype = str(action.get("type", "")).lower()
    _, params_hash = derive_rule_key(action)
    # `params_hash is None` is the ONLY signal that a rule binds nothing. It is read from
    # derive_rule_key rather than re-derived here, so this sentence cannot claim a narrower
    # scope than the rule actually has.
    broad = params_hash is None

    if atype == "email_send":
        if broad:
            return f"Từ nay {verb}: MỌI email của agent này, gửi tới BẤT KỲ ai"
        names = ", ".join(f"@{d}" for d in email_domains(action))
        return f"Từ nay {verb}: MỌI email gửi tới {names}"
    if atype == "gh_cli":
        argv = [str(a) for a in (action.get("argv") or [])]
        sub = " ".join(argv[:2]) or "?"
        if broad:
            return f"Từ nay {verb}: MỌI lệnh `gh {sub}`, trên BẤT KỲ repo nào"
        target = ""
        if "-R" in argv and argv.index("-R") + 1 < len(argv):
            target = argv[argv.index("-R") + 1]
        target = target or " ".join(argv[2:])
        return f"Từ nay {verb}: MỌI lệnh `gh {sub}` trên {target}"
    if atype == "mcp_tool":
        tool = f"{action.get('server', '?')}:{action.get('tool', '?')}"
        if broad:
            return f"Từ nay {verb}: MỌI lần gọi công cụ `{tool}`"
        dest = mcp_destination(action.get("args") or {})
        where = f"đích `{dest}`" if dest else "ĐÚNG tham số đã dùng lần này"
        return f"Từ nay {verb}: công cụ `{tool}` trên {where}"
    if atype == "telegram_send":
        if broad:
            return f"Từ nay {verb}: MỌI tin Telegram của agent này"
        return f"Từ nay {verb}: MỌI tin Telegram gửi tới chat {action.get('chat_id')}"
    if atype == "gws_write":
        argv = [str(a) for a in (action.get("argv") or [])]
        product = argv[0] if argv else "?"
        if broad:
            return f"Từ nay {verb}: MỌI thao tác ghi `{product}`"
        return f"Từ nay {verb}: ghi `{product}` trên ĐÚNG tài liệu đã dùng lần này"
    # Internal store writes bind nothing — the broad case, said plainly. Same wording for
    # an unknown type, which is unreachable here (a stub is refused before this point).
    return f"Từ nay {verb}: MỌI thao tác `{atype}` của agent này"


def _guard_rule_scope(action: dict, scope: str) -> None:
    """A standing rule may only be taught over an action the CEO was really shown.

    A stub summary (`<type> (chi tiết xem web)`) means chat could not describe what
    the action does. Consent to a permanent rule over a description like that is not
    consent, so `always`/`deny` are refused and the one-off decision is offered.
    """
    if scope == _SCOPE_ONCE:
        return
    if is_stub_summary(action):
        raise ValueError(
            "loại việc này chat chưa tóm tắt được nên không tạo luật lâu dài được — "
            "duyệt/từ chối một lần thì được, còn muốn đặt luật thì mở web"
        )


def _rule_ack(scope: str, rule_id: int) -> str:
    """Deny rules only bite on the guarded path — say so, every time.

    A CEO who believes a deny rule is a global kill switch would be wrong in the most
    dangerous direction: an agent in autonomous mode never consults this store at all.
    """
    if scope == SCOPE_DENY:
        return (f"Đã ghi luật CHẶN (#{rule_id}) — lưu ý: luật chặn chỉ có hiệu lực ở "
                "chế độ guarded; agent đang chạy tự chủ (autonomous) không hỏi luật này.")
    return f"Đã ghi luật TỰ DUYỆT (#{rule_id}) cho các lần sau."


# --- list ------------------------------------------------------------------


def run_list_approvals(slots: dict[str, str]) -> str:
    """Everything waiting for a signature, across every enabled agent."""
    lines: list[str] = []
    unreadable: list[str] = []
    for agent_id in _enabled_agent_ids():
        try:
            rows = read_pending_actions(agent_data_dir(agent_id))
        except Exception:  # noqa: BLE001 — one broken db must not blind the whole list
            logger.warning("approvals unreadable for agent %s", agent_id, exc_info=True)
            unreadable.append(agent_id)
            continue
        for row in rows:
            lines.append(
                f"#{row['id']} · {agent_id} · {summarize_action(row['action'])}"
            )
    if not lines and not unreadable:
        return "Không có việc nào đang chờ duyệt."
    out = ["Đang chờ duyệt:", *lines] if lines else ["Không có việc nào đang chờ duyệt."]
    if unreadable:
        # Never silently drop an agent: "nothing pending" and "could not read" must
        # not look identical to someone deciding whether to go check the web.
        out.append(f"(chưa đọc được hàng chờ của: {', '.join(unreadable)})")
    out.append("Duyệt bằng: `duyệt <số> của <agent>` — từ chối: `từ chối <số> của <agent>`")
    return "\n".join(out)


# --- approve / reject ------------------------------------------------------


def _preview(slots: dict[str, str], *, approving: bool) -> str:
    agent_id = _require_agent(slots.get("agent_id", ""))
    raw_id = (slots.get("approval_id") or "").strip()
    if not raw_id.isdigit():
        raise ValueError("mã việc chờ duyệt phải là một con số, ví dụ `duyệt 12 của secretary`")
    approval_id = int(raw_id)
    row = _require_pending(agent_id, approval_id)
    scope = _normalize_scope(slots.get("scope", ""))
    action = row["action"]
    _guard_rule_scope(action, scope)

    verb = "DUYỆT" if approving else "TỪ CHỐI"
    parts = [
        f"Mình sẽ {verb} việc #{approval_id} của `{agent_id}`:",
        summarize_action(action),
    ]
    if scope != _SCOPE_ONCE:
        parts.append(_scope_sentence(action, scope))
        if scope == SCOPE_DENY:
            parts.append("(luật chặn chỉ có hiệu lực ở chế độ guarded)")
    # "xác nhận" only — deliberately NOT "duyệt", which is also how the CEO starts a
    # NEW approval command. A confirm word that doubles as a command word is how a
    # reply meant for the newest push lands on an older pending draft.
    parts.append("Xác nhận? (trả lời: xác nhận / huỷ)")
    return "\n".join(parts)


def preview_approve_pending_action(slots: dict[str, str]) -> str:
    return _preview(slots, approving=True)


def preview_reject_pending_action(slots: dict[str, str]) -> str:
    return _preview(slots, approving=False)


def _decide(slots: dict[str, str], *, approving: bool) -> str:
    from my_crew.actions.approved_dispatch import make_agent_bound_dispatch
    from my_crew.entrypoints.mpm_manage_cmds import _gateway

    agent_id = _require_agent(slots.get("agent_id", ""))
    approval_id = int(str(slots["approval_id"]).strip())
    scope = _normalize_scope(slots.get("scope", ""))
    # Re-read at run time: between preview and confirm another surface may have decided
    # it. The IDS never move (they are bound in the draft) — only the row's liveness is
    # re-checked, which is the opposite of the v64 H1 mistake of re-resolving the target.
    #
    # A row gone AT CONFIRM is a lost race, not bad input: the CEO typed a valid id and
    # someone else got there first. It reads as its own outcome (same wording as losing
    # the race inside the gateway), because "you typed something wrong" would be a lie.
    row = _find_pending(agent_id, approval_id)
    if row is None:
        return _race_lost(approval_id, agent_id)
    action = row["action"]
    _guard_rule_scope(action, scope)

    # Same load + same gateway construction the CLI approve path uses. Chat is a third
    # surface on one queue, not a second implementation of it: if the CLI's construction
    # changes (actor attribution, external-channel policy), chat moves with it.
    from my_crew.profile.loader import load_profile

    loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    gw = _gateway(loaded)
    try:
        if approving:
            try:
                result = gw.approve(
                    approval_id,
                    handler=make_agent_bound_dispatch(
                        getattr(loaded, "profile_id", ""), loaded.config
                    ),
                )
            except ValueError:
                # transition_if_pending lost — another surface decided it first.
                return _race_lost(approval_id, agent_id)
            except HardBlockedError as exc:
                # Lớp A denies even an approved action, and no human tap overrides it.
                # Reported as a refusal, never as a retryable error, and it teaches no
                # rule: a standing "always" over an action Lớp A blocks is a rule that
                # can only ever be wrong.
                return (f"KHÔNG duyệt được #{approval_id} của `{agent_id}`: Lớp A chặn "
                        f"({exc}). Đây là chặn cứng, duyệt tay cũng không qua được.")
            except RuntimeError as exc:
                # Ordering matters: HardBlockedError subclasses RuntimeError, so its clause
                # must stay ABOVE this one — a Lớp A block reported as "retry" would send
                # the CEO tapping at a wall.
                # The handler failed AFTER claiming the row; the gateway reverted it to
                # pending. Distinct from a race and from a hard block, because the CEO
                # can simply retry — say that instead of a generic failure.
                logger.warning("approval #%s handler failed", approval_id, exc_info=True)
                return (f"Chạy việc #{approval_id} của `{agent_id}` bị lỗi ({exc}) — "
                        "việc VẪN ĐANG CHỜ DUYỆT, anh thử lại được.")
            head = f"Đã duyệt #{approval_id} của `{agent_id}`: {result.summary}"
        else:
            if not gw.reject(approval_id):
                return _race_lost(approval_id, agent_id)
            head = f"Đã từ chối #{approval_id} của `{agent_id}`."

        if scope == _SCOPE_ONCE:
            return head
        # The rule is derived from the STORED action, never from anything hand-typed,
        # so what was approved and what becomes standing are the same shape.
        rule = gw.approval_rules.add_rule(
            action, scope=scope,
            # Surface and principal are both recorded: an audit needs to tell a rule the
            # CEO taught from chat apart from one an agent's own CLI run created.
            created_by=f"{agent_id} via ops-chat",
        )
        return f"{head}\n{_rule_ack(scope, rule.id)}"
    finally:
        gw.close()


def _race_lost(approval_id: int, agent_id: str) -> str:
    return (f"Việc #{approval_id} của `{agent_id}` đã được xử lý trước đó (ở web hoặc CLI) "
            "— mình không đụng vào nữa. Gõ `xem approval` để coi danh sách mới.")


def run_approve_pending_action(slots: dict[str, str]) -> str:
    return _decide(slots, approving=True)


def run_reject_pending_action(slots: dict[str, str]) -> str:
    return _decide(slots, approving=False)
