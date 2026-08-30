"""Zalo business fleet P4: generic service-credential resolver. Offline.

Load-bearing: priority order is account-store > token_env > None, tested against
plain dicts (no Zalo-specific type needed — the resolver is adapter-agnostic).
A PRESENT but broken reference (bad account id, unset env var) raises rather than
silently falling through to the next branch.
"""

from __future__ import annotations

import pytest

from my_crew.config.credential_resolver import resolve_service_credentials
from my_crew.config.credential_store import CredentialStore, CredentialStoreError


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    return env


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / ".data"
    d.mkdir()
    monkeypatch.setattr("my_crew.config.credential_store.DATA_DIR", d)
    return d


def test_resolves_from_account_store_when_account_present(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("zalo-main", {"token": "from-store"})
    block = {"account": "zalo-main", "token_env": "ZALO_TOKEN"}  # both present
    assert resolve_service_credentials(block, store=store) == {"token": "from-store"}


def test_resolves_from_token_env_when_no_account(env_file, data_dir, monkeypatch):
    monkeypatch.setenv("ZALO_TOKEN", "from-env")
    block = {"token_env": "ZALO_TOKEN"}
    assert resolve_service_credentials(block) == {"token": "from-env"}


def test_returns_none_when_neither_present(env_file, data_dir):
    assert resolve_service_credentials({}) is None


def test_account_present_but_missing_in_store_raises(env_file, data_dir):
    from my_crew.config.credential_store import CredentialDecryptError

    block = {"account": "never-stored"}
    with pytest.raises(CredentialDecryptError):
        resolve_service_credentials(block)


def test_token_env_present_but_unset_raises(env_file, data_dir, monkeypatch):
    monkeypatch.delenv("ZALO_TOKEN", raising=False)
    block = {"token_env": "ZALO_TOKEN"}
    with pytest.raises(CredentialStoreError, match="ZALO_TOKEN"):
        resolve_service_credentials(block)
