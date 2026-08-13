"""v6 M14: the CEO chat-ops operator gate in qa_answer. Offline.

Only the admin agent's configured telegram operator, over Telegram, reaches ops. Every
other combination (non-admin domain, non-operator user, non-telegram transport, no
operator configured) skips ops entirely — proving the gate is on the immutable message
`user` id, not on text a prompt could spoof.
"""

from __future__ import annotations

from my_crew.agent.qa_answer import _is_ops_operator
from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.profile.loader import LoadedProfile


def _loaded(tmp_path, *, domain, telegram):
    config = build_reporting_config_from_dict(
        {"jira_project_key": "SCRUM", "github_repo": "o/r", "slack_report_channel": "C",
         "slack_stakeholder_channel": "", "slack_external_channels": "",
         **({"telegram": telegram} if telegram else {})}
    )
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    return LoadedProfile(
        profile_id="admin", name="Admin", enabled=True, settings=settings, config=config,
        soul="", project="", memory="", schedule={}, reports=("cost-rollup",), domain=domain,
    )


_TG = {"bot_token_env": "T", "chat_ids": ["100"], "ops_operator_id": "555"}


def _mention(user="555", transport="telegram"):
    return {"ts": "tg:100:1", "text": "tạo agent", "channel": "100", "user": user,
            "transport": transport}


def test_operator_on_admin_telegram_passes(tmp_path):
    loaded = _loaded(tmp_path, domain="admin", telegram=_TG)
    assert _is_ops_operator(loaded, _mention(user="555")) is True


def test_non_operator_user_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="admin", telegram=_TG)
    assert _is_ops_operator(loaded, _mention(user="999")) is False


def test_non_admin_domain_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="pm", telegram=_TG)
    assert _is_ops_operator(loaded, _mention(user="555")) is False


def test_non_telegram_transport_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="admin", telegram=_TG)
    m = _mention(user="555")
    m.pop("transport")  # a Slack mention carries no transport key
    assert _is_ops_operator(loaded, m) is False


def test_no_operator_configured_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="admin",
                     telegram={"bot_token_env": "T", "chat_ids": ["100"]})
    assert _is_ops_operator(loaded, _mention(user="555")) is False


def test_no_telegram_block_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="admin", telegram=None)
    assert _is_ops_operator(loaded, _mention(user="555")) is False


# --- v61: personal (secretary) is ops-enabled with the ORCHESTRATION catalog ---


def test_operator_on_personal_telegram_passes(tmp_path):
    loaded = _loaded(tmp_path, domain="personal", telegram=_TG)
    assert _is_ops_operator(loaded, _mention(user="555")) is True


def test_non_operator_on_personal_rejected(tmp_path):
    loaded = _loaded(tmp_path, domain="personal", telegram=_TG)
    assert _is_ops_operator(loaded, _mention(user="999")) is False


def test_personal_catalog_is_orchestration_only():
    """Pin an ninh: personal KHÔNG bao giờ thấy lệnh quản trị fleet; admin giữ nguyên
    catalog đầy đủ (không đổi một byte hành vi pre-v61)."""
    from my_crew.agent.ops_catalog import (
        OPS_COMMANDS,
        ORCHESTRATION_COMMAND_IDS,
        catalog_for_domain,
    )

    assert catalog_for_domain("admin") is OPS_COMMANDS
    personal = catalog_for_domain("personal")
    assert set(personal) == ORCHESTRATION_COMMAND_IDS
    assert "create_agent" not in personal and "set_enabled" not in personal
    assert "create_calendar_event" not in personal  # thư ký đã có lệnh M12 riêng
    assert "assign_team_task" in personal and "cancel_task" in personal
    # subset phải là tập con thật của catalog gốc — không tự bịa lệnh mới
    assert set(personal) <= set(OPS_COMMANDS)


def test_personal_unsupported_lists_only_orchestration(tmp_path):
    """Đường engine thật với catalog personal: lệnh fleet-admin bị coi là unsupported
    và listing trả về KHÔNG chứa create_agent."""
    import time

    from my_crew.agent.ops_catalog import catalog_for_domain
    from my_crew.agent.ops_chat import handle_ops_message
    from my_crew.agent.ops_conversation_store import OpsConversationStore

    class _Llm:
        def complete(self, messages, **_kw):
            return type("R", (), {
                "content": '{"intent":"command","command_id":"create_agent","slots":{}}',
                "cost_usd": 0.0001,
            })()

    store = OpsConversationStore(tmp_path / "ops.sqlite3")
    try:
        reply, _cost = handle_ops_message(
            message="tạo agent mới tên sales", conversation_key="ceo", store=store,
            llm=_Llm(), now=time.time(), catalog=catalog_for_domain("personal"),
        )
    finally:
        store.close()
    assert "create_agent" not in reply
    assert "assign_team_task" in reply  # listing giới thiệu đúng nhóm điều phối


def test_personal_unsupported_falls_through_to_m12_catalog():
    """v65: an ops-unrecognized command from the secretary's operator must return the
    empty-reply signal (fall through to the personal M12 catalog: set_reminder,
    send_email, …) — the old ops listing shadowed every M12 command. Admin keeps the
    listing (no M12 catalog behind it)."""
    import time

    from my_crew.agent.ops_catalog import catalog_for_domain
    from my_crew.agent.ops_chat import handle_ops_message
    from my_crew.agent.ops_conversation_store import OpsConversationStore

    class _Llm:
        def complete(self, messages, **_kw):
            from types import SimpleNamespace

            return SimpleNamespace(
                content='{"intent": "unsupported"}', cost_usd=0.0,
            )

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        store = OpsConversationStore(Path(td) / "ops.sqlite3")
        try:
            reply, _cost = handle_ops_message(
                message="đặt nhắc 3h gọi anh X", conversation_key="op",
                store=store, llm=_Llm(), now=time.time(),
                catalog=catalog_for_domain("personal"),
                unsupported_fallthrough=True,
            )
            assert reply == ""  # falls through — M12 gets its shot
            reply_admin, _ = handle_ops_message(
                message="đặt nhắc 3h gọi anh X", conversation_key="op2",
                store=store, llm=_Llm(), now=time.time(),
                catalog=catalog_for_domain("admin"),
            )
            assert "Mình quản lý đội qua các lệnh" in reply_admin  # admin unchanged
        finally:
            store.close()
