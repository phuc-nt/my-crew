"""v7 M17: atomic .env merge-writer + key whitelist. Offline.

Load-bearing:
- Whitelist: only permitted keys write; PATH/LD_PRELOAD/etc REFUSED (env-injection guard).
- Atomic merge: existing keys/comments preserved, target keys updated in place, new keys
  appended; a .env.bak is kept; write is all-or-nothing on a disallowed key.
- read_key_presence returns bool only — never the secret value.
"""

from __future__ import annotations

import pytest

from my_crew.server.env_writer import (
    FINISH_WRITABLE_KEYS,
    SETUP_WRITABLE_KEYS,
    DisallowedEnvKey,
    is_writable,
    merge_env,
    read_key_presence,
)


def test_whitelist_allows_setup_keys_rejects_injection():
    assert is_writable("OPENROUTER_API_KEY", allow=SETUP_WRITABLE_KEYS)
    # env-injection attempts must be refused
    for bad in ("PATH", "LD_PRELOAD", "PYTHONPATH", "DRY_RUN", "AGENT_WRITE_DISABLED",
                "WEB_AUTH_PASSWORD_HASH"):  # auth keys not writable on the setup path
        assert not is_writable(bad, allow=SETUP_WRITABLE_KEYS)
    assert not is_writable("lowercase", allow=SETUP_WRITABLE_KEYS)  # malformed name


def test_telegram_token_pattern_gated_by_flag():
    key = "ACME_PM_TELEGRAM_BOT_TOKEN"
    assert not is_writable(key, allow=SETUP_WRITABLE_KEYS)  # off by default
    assert is_writable(key, allow=SETUP_WRITABLE_KEYS, allow_telegram_token=True)
    assert not is_writable("EVIL_TOKEN", allow=SETUP_WRITABLE_KEYS, allow_telegram_token=True)


def test_merge_preserves_existing_and_updates_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nOPENROUTER_API_KEY=old\nDRY_RUN=true\n", encoding="utf-8")
    merge_env({"OPENROUTER_API_KEY": "new", "GITHUB_REPO": "o/r"},
              allow=SETUP_WRITABLE_KEYS, env_path=env)
    text = env.read_text(encoding="utf-8")
    assert "# comment" in text  # comment preserved
    assert "OPENROUTER_API_KEY=new" in text  # updated in place
    assert "DRY_RUN=true" in text  # unrelated key untouched
    assert "GITHUB_REPO=o/r" in text  # new key appended
    assert (tmp_path / ".env.bak").exists()  # backup kept


def test_merge_all_or_nothing_on_disallowed_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=keep\n", encoding="utf-8")
    with pytest.raises(DisallowedEnvKey, match="PATH"):
        merge_env({"OPENROUTER_API_KEY": "x", "PATH": "/evil"},
                  allow=SETUP_WRITABLE_KEYS, env_path=env)
    # nothing written — original intact
    assert env.read_text(encoding="utf-8") == "OPENROUTER_API_KEY=keep\n"


def test_merge_skips_blank_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=set\n", encoding="utf-8")
    merge_env({"OPENROUTER_API_KEY": "  "}, allow=SETUP_WRITABLE_KEYS, env_path=env)
    assert "OPENROUTER_API_KEY=set" in env.read_text(encoding="utf-8")  # not blanked


def test_read_key_presence_bool_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-secret-value\nGITHUB_REPO=\n", encoding="utf-8")
    keys = frozenset({"OPENROUTER_API_KEY", "GITHUB_REPO", "SLACK_XOXC_TOKEN"})
    presence = read_key_presence(keys, env_path=env)
    assert presence == {"OPENROUTER_API_KEY": True, "GITHUB_REPO": False,
                        "SLACK_XOXC_TOKEN": False}
    # the value never leaks — presence is bool
    assert "sk-secret-value" not in str(presence)


def test_finish_keys_separate_from_setup(tmp_path):
    assert is_writable("WEB_AUTH_PASSWORD_HASH", allow=FINISH_WRITABLE_KEYS)
    assert not is_writable("OPENROUTER_API_KEY", allow=FINISH_WRITABLE_KEYS)  # a setup key
