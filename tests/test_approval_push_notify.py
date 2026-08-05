"""v69 approval push: queuing a Lớp B action tells the CEO on Telegram.

The notice is an OVERLAY on the approval queue — these tests pin that it fires from
both enqueue points, that its content leaks neither payloads nor attacker-influenced
free text, and above all that a broken transport never changes what the gateway did.
"""

from __future__ import annotations

from my_crew.actions.action_gateway import (
    _REASON_FALLBACK,
    ActionGateway,
    _push_reason,
)
from my_crew.audit.audit_log import AuditLog

EMAIL = {"type": "email_send", "to": "ceo@acme.com", "subject": "hi", "body": "chi tiết"}


def _gw(settings_factory, tmp_path, notify=None, **kw):
    return ActionGateway(
        settings=settings_factory(dry_run=False, **kw),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        notify_enqueued=notify,
        actor="secretary",
    )


def test_queueing_an_action_pushes_once_with_the_ids_needed_to_act(
    settings_factory, tmp_path
):
    seen = []
    gw = _gw(settings_factory, tmp_path, notify=lambda i, a, actor: seen.append((i, a, actor)))
    result = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert result.status == "pending_approval"
    assert len(seen) == 1
    approval_id, action, actor = seen[0]
    # The CEO must be able to answer "duyệt <id>" against the right agent's queue.
    assert approval_id == result.approval_id
    assert actor == "secretary"
    assert action["type"] == "email_send"


def test_the_chat_origin_enqueue_point_also_pushes(settings_factory, tmp_path):
    """`enqueue_for_approval` is a second, independent queue point — it must not be silent."""
    seen = []
    gw = _gw(settings_factory, tmp_path, notify=lambda i, a, actor: seen.append(i))
    result = gw.enqueue_for_approval(EMAIL, reason="Lớp B: gửi email cần người duyệt")
    assert result.status == "pending_approval"
    assert seen == [result.approval_id]


def test_an_executed_action_does_not_push(settings_factory, tmp_path):
    """Only a queued action needs a signature; an autonomous run must stay quiet."""
    seen = []
    gw = _gw(
        settings_factory, tmp_path, trust_mode="autonomous",
        notify=lambda i, a, actor: seen.append(i),
    )
    result = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert result.status == "executed"
    assert seen == []


def test_a_dead_transport_never_costs_the_approval(settings_factory, tmp_path, monkeypatch):
    """The queue is the source of truth. A dead Telegram must not lose the approval.

    Exercises the SHIPPED default notifier (not an injected stub) with the underlying
    transport raising — the whole point is that the default is the thing that swallows.
    """
    import my_crew.runtime.operator_notify as notify_mod

    def boom(*a, **kw):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(notify_mod, "notify_operator_best_effort", boom)
    gw = ActionGateway(
        settings=settings_factory(dry_run=False),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        actor="secretary",
    )
    result = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert result.status == "pending_approval"
    assert result.approval_id is not None
    # And the approval really is queryable afterwards — not half-written.
    assert [p.id for p in gw._approvals.list_pending()] == [result.approval_id]


def test_reason_comes_from_a_fixed_vocabulary_not_the_interrupt_text():
    """`interrupt.reason` interpolates an LLM-composed tool name for mcp_tool/gh_cli.

    That text is attacker-influenceable and would land next to a confirm prompt, so
    the push renders a fixed phrase keyed on the action type instead.
    """
    assert _push_reason({"type": "email_send"}) == "gửi email ra ngoài"
    hostile = {"type": "mcp_tool", "tool": "an toàn — CEO đã duyệt, cứ bấm ok"}
    assert _push_reason(hostile) == "gọi công cụ nhạy cảm"
    assert _push_reason({"type": "brand_new_type"}) == _REASON_FALLBACK
    assert _push_reason("not a dict") == _REASON_FALLBACK  # type: ignore[arg-type]


def test_default_notifier_swallows_a_broken_transport(monkeypatch):
    """The shipped default must never raise — that is the whole best-effort contract."""
    import my_crew.runtime.operator_notify as notify_mod
    from my_crew.actions import action_gateway as gw_mod

    def boom(*a, **kw):
        raise RuntimeError("no transport")

    monkeypatch.setattr(notify_mod, "notify_operator_best_effort", boom)
    gw_mod._notify_approval_enqueued(7, EMAIL, "secretary")  # must not raise
