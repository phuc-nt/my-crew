"""v6 M14: CEO chat-ops engine (manage fleet by dialogue). Offline (LLM stubbed).

Load-bearing properties:
- Multi-turn slot-filling: missing required slots are asked one at a time; a write
  command ALWAYS shows a preview and waits for an explicit "xác nhận" before running.
- Structural safety: the LLM only classifies + extracts a slot value; CODE runs the
  catalog. No destructive command exists, so "xoá hết agent" is unsupported. A parse
  failure defaults to question; an infra error re-raises (retry, not silent degrade).
- Confirm discipline: "xác nhận" runs exactly once (draft consumed before run, so a
  re-poll can't double-run); anything else cancels; a stale draft (TTL) is ignored.
- Operator gate: only the admin agent's configured telegram operator reaches ops.
"""

from __future__ import annotations

import pytest

from my_crew.agent.ops_catalog import OPS_COMMANDS
from my_crew.agent.ops_chat import classify_ops_intent, handle_ops_message
from my_crew.agent.ops_conversation_store import DRAFT_TTL_S, OpsConversationStore, OpsDraft


class _FakeLlm:
    """Returns queued JSON strings in order; each call pops the next."""

    def __init__(self, *contents):
        self._q = list(contents)

    def complete(self, messages):
        content = self._q.pop(0)
        return type("R", (), {"content": content, "cost_usd": 0.0001})()


def _store(tmp_path):
    return OpsConversationStore(tmp_path / "ops.sqlite3")


# --- catalog integrity ---


def test_no_destructive_command_in_catalog():
    ids = set(OPS_COMMANDS)
    assert "create_agent" in ids and "set_enabled" in ids
    assert not any("delete" in c or "remove" in c or "xoa" in c for c in ids)


def test_readonly_commands_have_no_write_hook_confusion():
    for cid, spec in OPS_COMMANDS.items():
        assert callable(spec["run"])
        if not spec.get("readonly"):
            assert callable(spec["preview"]), f"{cid} write command needs a preview"


def test_create_agent_domain_choices_cover_every_installed_pack():
    """Guard against the choices map drifting behind the packs: a new domain-pack that
    isn't added to create_agent's `domain` choices would be un-creatable by chat with a
    Vietnamese role name. If this fails, add the new domain (+ its VN aliases) to the map."""
    from my_crew.packs.registry import discover_domains

    domain_choices = set(OPS_COMMANDS["create_agent"]["slots"]["domain"]["choices"])
    assert set(discover_domains()) <= domain_choices, (
        f"packs {set(discover_domains()) - domain_choices} missing from create_agent "
        "domain choices in ops_catalog.py"
    )


def test_confirm_accepts_natural_affirmation_and_cancel_wins(tmp_path, monkeypatch):
    """A confirm reply is word-membership, not exact-match: 'ok tạo đi' confirms; a cancel
    word anywhere ('không, thôi') cancels (fail-safe)."""
    from my_crew.agent.ops_chat import _confirm_decision

    assert _confirm_decision("ok tạo đi luôn") == "confirm"
    assert _confirm_decision("được, chốt nhé") == "confirm"
    assert _confirm_decision("xác nhận") == "confirm"
    assert _confirm_decision("thôi không cần nữa") == "cancel"
    assert _confirm_decision("không, tạo đi") == "cancel"  # cancel wins — CEO can re-issue
    assert _confirm_decision("ừm để xem đã") == "unclear"


# --- intent classification safe default ---


@pytest.mark.parametrize("garbage", ["not json", "[1,2]", '{"intent":', ""])
def test_classify_garbage_falls_back_to_question(garbage):
    out = classify_ops_intent(_FakeLlm(garbage), "msg")
    assert out["intent"] == "question"


def test_classify_reraises_infra_error():
    from my_crew.llm.fallback_policy import ProviderCallError

    class _Down:
        def complete(self, m):
            raise ProviderCallError("down")

    with pytest.raises(ProviderCallError):
        classify_ops_intent(_Down(), "tạo agent")


# --- readonly command: run immediately, no draft ---


def test_get_status_runs_without_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.agent_state_reader.read_all_agent_states",
        lambda: [{"agent_id": "pm", "enabled": True, "pending_approvals": [1, 2]},
                 {"agent_id": "hr", "enabled": False, "pending_approvals": []}],
    )
    monkeypatch.setattr("my_crew.runtime.agent_state_reader.team_alerts", lambda s: [])
    store = _store(tmp_path)
    try:
        reply, _ = handle_ops_message(
            message="đội mình sao rồi", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"get_status","slots":{}}'), now=1000.0,
        )
        assert "2 agent" in reply and "pm" in reply and "2 việc chờ duyệt" in reply
        assert store.load("ceo", now=1000.0) is None  # readonly leaves no draft
    finally:
        store.close()


def test_get_cost_sums_fleet(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.agent_state_reader.read_all_agent_states",
        lambda: [{"agent_id": "pm", "budget_spent_usd": 1.5, "budget_cap_usd": 50},
                 {"agent_id": "hr", "budget_spent_usd": 0.25, "budget_cap_usd": 50}],
    )
    store = _store(tmp_path)
    try:
        reply, _ = handle_ops_message(
            message="tốn bao nhiêu tiền", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"get_cost","slots":{}}'), now=1.0,
        )
        assert "$1.7500" in reply  # 1.5 + 0.25
    finally:
        store.close()


# --- write command: slot-filling → preview → confirm ---


def test_unsupported_lists_catalog(tmp_path):
    store = _store(tmp_path)
    try:
        reply, _ = handle_ops_message(
            message="xoá hết agent đi", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"unsupported"}'), now=1.0,
        )
        assert "create_agent" in reply and "xoá" not in reply.split("lệnh:")[0].lower()
        assert store.load("ceo", now=1.0) is None
    finally:
        store.close()


def test_question_returns_empty_for_fallthrough(tmp_path):
    store = _store(tmp_path)
    try:
        reply, _ = handle_ops_message(
            message="thời tiết hôm nay", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"question"}'), now=1.0,
        )
        assert reply == ""  # caller falls through to Q&A
    finally:
        store.close()


def test_create_agent_full_slot_filling_flow(tmp_path, monkeypatch):
    created = {}

    def fake_create(spec):
        created.update(spec)
        return {"id": spec["id"], "domain": spec["domain"], "reports": spec["reports"]}

    monkeypatch.setattr("my_crew.server.agent_create.create_agent", fake_create)
    store = _store(tmp_path)
    try:
        # Turn 1: intent + partial slots (id only). Engine asks for the next missing slot.
        r1, _ = handle_ops_message(
            message="tạo agent sales-team", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"create_agent",'
                         '"slots":{"id":"sales-team"}}'), now=1.0,
        )
        assert "vai trò" in r1.lower() or "domain" in r1.lower()
        # Turn 2: answer domain → engine asks for reports.
        r2, _ = handle_ops_message(
            message="pm", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"value":"pm"}'), now=2.0,
        )
        assert "báo cáo" in r2.lower()
        # Turn 3: answer reports → all required slots in → PREVIEW + confirm ask.
        r3, _ = handle_ops_message(
            message="daily", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"value":"daily"}'), now=3.0,
        )
        assert "xác nhận" in r3.lower() and "sales-team" in r3
        assert not created  # NOTHING created yet — only a preview
        # Turn 4: confirm → create runs for real.
        r4, _ = handle_ops_message(
            message="xác nhận", conversation_key="ceo", store=store, llm=_FakeLlm(), now=4.0,
        )
        assert "đã tạo" in r4.lower() and created["id"] == "sales-team"
        assert created["domain"] == "pm" and created["reports"] == ["daily"]
        assert store.load("ceo", now=4.0) is None  # draft consumed
    finally:
        store.close()


def test_confirm_runs_once_no_double_on_repoll(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_create(spec):
        calls["n"] += 1
        return {"id": spec["id"], "domain": spec["domain"], "reports": spec["reports"]}

    monkeypatch.setattr("my_crew.server.agent_create.create_agent", fake_create)
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent",
               {"id": "x", "domain": "pm", "reports": "daily"}, "awaiting_confirm", 1.0))
    try:
        r1, _ = handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                                   llm=_FakeLlm(), now=2.0)
        # A re-poll of the SAME confirm message must not create twice (draft consumed).
        r2, _ = handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                                   llm=_FakeLlm('{"intent":"question"}'), now=3.0)
        assert calls["n"] == 1 and "đã tạo" in r1.lower()
        assert r2 == ""  # no draft ⇒ treated as a fresh (question) message
    finally:
        store.close()


def test_cancel_at_confirm_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.server.agent_create.create_agent",
                        lambda s: pytest.fail("must not create on cancel"))
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent",
               {"id": "x", "domain": "pm", "reports": "daily"}, "awaiting_confirm", 1.0))
    try:
        reply, _ = handle_ops_message(message="thôi huỷ", conversation_key="ceo", store=store,
                                      llm=_FakeLlm(), now=2.0)
        assert "huỷ" in reply.lower()
        assert store.load("ceo", now=2.0) is None
    finally:
        store.close()


def test_preview_value_error_becomes_friendly_reply_and_clears_draft(tmp_path, monkeypatch):
    """A `preview` hook's `ValueError` (e.g. `assign_team_task` when no Telegram
    escalation route is configured, or a brief the decomposer rejects) is a user-facing
    validation message, not a server crash: `_advance_or_confirm` must catch it, reply
    with the message, and drop the draft — never let it propagate out of
    `handle_ops_message` (which would 500 the poller) and never leave a half-formed
    draft the CEO's next message would be confused by."""
    import my_crew.agent.ops_chat as ops_chat_module

    def _boom_preview(slots):
        raise ValueError("chưa có đường báo cáo sự cố")

    monkeypatch.setitem(ops_chat_module.OPS_COMMANDS["assign_team_task"], "preview", _boom_preview)
    store = _store(tmp_path)
    try:
        reply, _ = handle_ops_message(
            message="giao việc viết báo cáo tháng", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"assign_team_task",'
                         '"slots":{"brief":"viết báo cáo tháng"}}'), now=1.0,
        )
        assert reply == "Chưa giao được việc: chưa có đường báo cáo sự cố"
        assert store.load("ceo", now=1.0) is None  # no half-formed draft left behind
    finally:
        store.close()


def test_cancel_during_collecting(tmp_path):
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent", {"id": "x"}, "collecting", 1.0))
    try:
        reply, _ = handle_ops_message(message="huỷ", conversation_key="ceo", store=store,
                                      llm=_FakeLlm(), now=2.0)
        assert "huỷ" in reply.lower() and store.load("ceo", now=2.0) is None
    finally:
        store.close()


def test_invalid_slot_value_asks_again(tmp_path):
    store = _store(tmp_path)
    # id slot pattern rejects uppercase/spaces → engine re-asks, no draft advance.
    store.save("ceo", OpsDraft("create_agent", {}, "collecting", 1.0))
    try:
        reply, _ = handle_ops_message(
            message="Sales Team!!!", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"value":"Sales Team!!!"}'), now=2.0,
        )
        assert "sai định dạng" in reply.lower() or "nhập lại" in reply.lower()
        draft = store.load("ceo", now=2.0)
        assert draft is not None and "id" not in draft.slots
    finally:
        store.close()


def test_set_enabled_flow(tmp_path, monkeypatch):
    flipped = {}
    monkeypatch.setattr(
        "my_crew.runtime.registry_edit.set_registry_enabled",
        lambda path, aid, on: flipped.update(aid=aid, on=on),
    )
    store = _store(tmp_path)
    try:
        # "tắt" is normalized to state="off" by the choices map before preview/run.
        r1, _ = handle_ops_message(
            message="tắt agent hr", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"set_enabled",'
                         '"slots":{"agent_id":"hr","state":"tắt"}}'), now=1.0,
        )
        assert "xác nhận" in r1.lower() and "TẮT" in r1
        assert not flipped  # preview only
        r2, _ = handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                                   llm=_FakeLlm(), now=2.0)
        assert flipped == {"aid": "hr", "on": False} and "TẮT" in r2
    finally:
        store.close()


def test_domain_and_id_are_normalized_from_conversational_answers(tmp_path, monkeypatch):
    """The E2E lesson: the CEO says a Vietnamese role + a mixed-case name; the engine must
    map "quản lý dự án" → "pm" and lowercase the id, not reject them."""
    created = {}
    monkeypatch.setattr(
        "my_crew.server.agent_create.create_agent",
        lambda spec: created.update(spec) or {"id": spec["id"], "domain": spec["domain"],
                                              "reports": spec["reports"]},
    )
    store = _store(tmp_path)
    try:
        # Intent seeds id="Sales-PM" (mixed case) + domain="quản lý dự án" (Vietnamese).
        r1, _ = handle_ops_message(
            message="tạo agent Sales-PM để quản lý dự án", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"command","command_id":"create_agent",'
                         '"slots":{"id":"Sales-PM","domain":"quản lý dự án"}}'), now=1.0,
        )
        # Both seeded slots were accepted (normalized), so the engine asks for `reports` next.
        assert "báo cáo" in r1.lower()
        draft = store.load("ceo", now=1.0)
        assert draft.slots["id"] == "sales-pm" and draft.slots["domain"] == "pm"
        # Provide reports → preview → confirm.
        handle_ops_message(message="daily", conversation_key="ceo", store=store,
                           llm=_FakeLlm('{"value":"daily"}'), now=2.0)
        handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                           llm=_FakeLlm(), now=3.0)
        assert created["id"] == "sales-pm" and created["domain"] == "pm"
    finally:
        store.close()


def test_reports_are_lowercased(tmp_path, monkeypatch):
    """E2E lesson: the CEO typed 'Daily' (capitalized) and create failed on the pack's
    lowercase 'daily'. The reports slot must lowercase before it reaches create_agent."""
    created = {}
    monkeypatch.setattr(
        "my_crew.server.agent_create.create_agent",
        lambda spec: created.update(spec) or {"id": spec["id"], "domain": spec["domain"],
                                              "reports": spec["reports"]},
    )
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent", {"id": "x", "domain": "pm"}, "collecting", 1.0))
    try:
        # CEO answers "Daily" → normalized to "daily" → preview.
        r1, _ = handle_ops_message(message="Daily", conversation_key="ceo", store=store,
                                   llm=_FakeLlm('{"value":"Daily"}'), now=2.0)
        assert "xác nhận" in r1.lower()
        assert store.load("ceo", now=2.0).slots["reports"] == "daily"
        handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                           llm=_FakeLlm(), now=3.0)
        assert created["reports"] == ["daily"]
    finally:
        store.close()


def test_invalid_domain_choice_rejected(tmp_path):
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent", {"id": "x"}, "collecting", 1.0))
    try:
        # An answer that maps to no known domain → validation error, re-ask.
        reply, _ = handle_ops_message(
            message="phòng marketing", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"value":"marketing"}'), now=2.0,
        )
        assert "chỉ nhận" in reply.lower() and "pm" in reply
        assert "domain" not in (store.load("ceo", now=2.0).slots)
    finally:
        store.close()


# --- TTL ---


def test_stale_draft_is_ignored(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save("ceo", OpsDraft("create_agent",
               {"id": "x", "domain": "pm", "reports": "daily"}, "awaiting_confirm", 100.0))
    try:
        # "xác nhận" arrives DRAFT_TTL_S+1 later → draft expired → treated as fresh message.
        reply, _ = handle_ops_message(
            message="xác nhận", conversation_key="ceo", store=store,
            llm=_FakeLlm('{"intent":"question"}'), now=100.0 + DRAFT_TTL_S + 1,
        )
        assert reply == ""  # no live draft → question fallthrough, nothing created
    finally:
        store.close()


def test_advance_or_confirm_skips_draft_after_auto_confirm(tmp_path, monkeypatch):
    """v15 F3 pin: a preview that ALREADY auto-ran its own confirm (assign under
    `team_task_auto_confirm`) must clear the conversation instead of parking an
    awaiting_confirm draft — otherwise the CEO's next message hits a ghost
    "Đã huỷ"/"kế hoạch đã thay đổi" turn for a task that is already running."""
    import time

    from my_crew.agent.ops_catalog import OPS_COMMANDS
    from my_crew.agent.ops_chat import _advance_or_confirm

    def _auto_preview(slots):
        slots["auto_confirmed"] = "1"
        return "ĐÃ TỰ XÁC NHẬN"

    monkeypatch.setitem(
        OPS_COMMANDS, "fake_auto_cmd",
        {"slots": {}, "preview": _auto_preview, "run": lambda s: "done", "readonly": False},
    )
    store = OpsConversationStore(tmp_path / "ops.sqlite3")
    reply, _cost = _advance_or_confirm(
        command_id="fake_auto_cmd", slots={"brief": "x"}, conversation_key="ceo",
        store=store, now=time.time(), cost=None,
    )
    assert reply == "ĐÃ TỰ XÁC NHẬN"
    assert store.load("ceo", now=time.time()) is None  # no awaiting_confirm draft parked
