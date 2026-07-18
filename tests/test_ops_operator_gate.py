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
