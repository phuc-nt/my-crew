"""Zalo business fleet P4: encrypted per-account credential store. Offline.

Load-bearing:
- put/get round-trips a dict, encrypted with Fernet, never plaintext on disk.
- Master key auto-generates on first use, written through env_writer (whitelisted).
- Wrong key / corrupted file -> CredentialDecryptError with a clear message, never
  a silent empty return.
- File mode 0600; rotation keeps exactly one `.bak.enc`; write is atomic.
- Invalid account id is rejected (same jail shape as agent ids).
"""

from __future__ import annotations

import json
import os
import stat

import pytest
from cryptography.fernet import Fernet

from my_crew.config.credential_store import (
    MASTER_KEY_ENV,
    CredentialDecryptError,
    CredentialStore,
    CredentialStoreError,
)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.delenv(MASTER_KEY_ENV, raising=False)
    yield env


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / ".data"
    d.mkdir()
    monkeypatch.setattr("my_crew.config.credential_store.DATA_DIR", d)
    return d


def test_put_get_roundtrip(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("zalo-oa-main", {"token": "abc123", "refresh": "def456"})
    assert store.get("zalo-oa-main") == {"token": "abc123", "refresh": "def456"}


def test_master_key_generated_on_first_use_and_written_to_env(env_file, data_dir):
    assert os.environ.get(MASTER_KEY_ENV) is None
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})
    assert f"{MASTER_KEY_ENV}=" in env_file.read_text(encoding="utf-8")
    assert os.environ.get(MASTER_KEY_ENV)  # visible to this process immediately
    # second call reuses the SAME key (round-trips using the persisted key)
    assert store.get("acc1") == {"token": "x"}


def test_no_plaintext_token_on_disk(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    secret = "super-secret-token-value-zzz"
    store.put("acc1", {"token": secret})
    raw = (data_dir / "accounts" / "acc1" / "credentials.enc").read_bytes()
    assert secret.encode() not in raw


def test_get_missing_account_raises_clear_error(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    with pytest.raises(CredentialDecryptError, match="acc-missing"):
        store.get("acc-missing")


def test_get_wrong_key_raises_clear_error_not_empty(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})
    # simulate key rotation/loss: overwrite MY_CREW_CRED_KEY with a different valid key
    os.environ[MASTER_KEY_ENV] = Fernet.generate_key().decode("ascii")
    with pytest.raises(CredentialDecryptError, match="cannot decrypt"):
        store.get("acc1")


def test_get_corrupted_file_raises_clear_error(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})
    cred_path = data_dir / "accounts" / "acc1" / "credentials.enc"
    cred_path.write_bytes(b"not-a-valid-fernet-token-at-all")
    with pytest.raises(CredentialDecryptError, match="cannot decrypt"):
        store.get("acc1")


def test_invalid_master_key_format_raises_store_error(env_file, data_dir):
    os.environ[MASTER_KEY_ENV] = "not-a-valid-fernet-key"
    store = CredentialStore(env_path=env_file)
    with pytest.raises(CredentialStoreError, match=MASTER_KEY_ENV):
        store.put("acc1", {"token": "x"})


def test_file_mode_0600(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})
    cred_path = data_dir / "accounts" / "acc1" / "credentials.enc"
    mode = stat.S_IMODE(cred_path.stat().st_mode)
    assert mode == 0o600


def test_rotation_keeps_one_backup(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "v1"})
    store.put("acc1", {"token": "v2"})
    backup_path = data_dir / "accounts" / "acc1" / "credentials.enc.bak.enc"
    assert backup_path.exists()
    # current value is v2, backup decrypts to v1
    assert store.get("acc1") == {"token": "v2"}
    from cryptography.fernet import Fernet as _F

    fernet = _F(os.environ[MASTER_KEY_ENV].encode("ascii"))
    backup_value = json.loads(fernet.decrypt(backup_path.read_bytes()))
    assert backup_value == {"token": "v1"}
    store.put("acc1", {"token": "v3"})  # rotate again: backup becomes v2, not v1+v2
    backup_value = json.loads(fernet.decrypt(backup_path.read_bytes()))
    assert backup_value == {"token": "v2"}


def test_atomic_write_no_tmp_file_left_behind(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})
    leftovers = list((data_dir / "accounts" / "acc1").glob("*.tmp"))
    assert leftovers == []


def test_delete_removes_credential_and_backup(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "v1"})
    store.put("acc1", {"token": "v2"})  # creates a backup
    assert store.delete("acc1") is True
    account_dir = data_dir / "accounts" / "acc1"
    assert not (account_dir / "credentials.enc").exists()
    assert not (account_dir / "credentials.enc.bak.enc").exists()


def test_delete_nonexistent_is_noop_returns_false(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    assert store.delete("never-existed") is False


def test_list_returns_only_accounts_with_credentials(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    store.put("acc-a", {"token": "a"})
    store.put("acc-b", {"token": "b"})
    (data_dir / "accounts" / "acc-empty-dir").mkdir(parents=True)  # no cred file inside
    assert store.list() == ["acc-a", "acc-b"]


def test_list_empty_when_no_accounts_dir(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    assert store.list() == []


@pytest.mark.parametrize(
    "bad_id", ["../escape", "Has/Slash", "UPPER", "", "has space", "a/../../b"]
)
def test_invalid_account_id_rejected(env_file, data_dir, bad_id):
    store = CredentialStore(env_path=env_file)
    with pytest.raises(ValueError, match="Invalid account id"):
        store.put(bad_id, {"token": "x"})


def test_put_rejects_non_dict_value(env_file, data_dir):
    store = CredentialStore(env_path=env_file)
    with pytest.raises(TypeError):
        store.put("acc1", "not-a-dict")  # type: ignore[arg-type]
