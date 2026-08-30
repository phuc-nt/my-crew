"""Zalo business fleet P4: credential values must never egress via redact()/audit.

Load-bearing: a real CredentialStore ciphertext blob, and the MY_CREW_CRED_KEY master
key itself, both match the new Fernet-token secret pattern in `actions/secret_patterns
.py` — so if either ever ends up in a free-text audit field or office-room feed, the
existing redaction machinery (which every audit write already goes through, per
`test_audit_log.py::test_secret_in_freetext_field_redacted`) masks it.
"""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from my_crew.actions.secret_patterns import REDACTED, find_secret, redact
from my_crew.audit.audit_log import AuditEntry, AuditLog
from my_crew.config.credential_store import MASTER_KEY_ENV, CredentialStore


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.delenv(MASTER_KEY_ENV, raising=False)
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    monkeypatch.setattr("my_crew.config.credential_store.DATA_DIR", data_dir)
    return env


def test_fernet_ciphertext_blob_matches_secret_pattern(env_file):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "hunter2-real-token-value"})
    ciphertext = (env_file.parent / ".data" / "accounts" / "acc1" / "credentials.enc").read_bytes()
    assert find_secret(ciphertext.decode("ascii")) is not None


def test_master_key_matches_secret_pattern_when_named(env_file):
    """The master key as it actually appears at rest (`.env` line `KEY=value`, or a
    free-text field naming it) still matches — anchored on the name, not the bare
    43-char+'=' shape (see `test_credential_secret_pattern_egress` narrowing note in
    `secret_patterns.py`, which fixed a false-positive against any base64 sha256)."""
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "x"})  # triggers master-key generation
    import os

    master_key = os.environ[MASTER_KEY_ENV]
    assert find_secret(f"{MASTER_KEY_ENV}={master_key}") is not None


def test_redact_masks_fernet_ciphertext_in_free_text(env_file):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "hunter2-real-token-value"})
    ciphertext_text = (
        (env_file.parent / ".data" / "accounts" / "acc1" / "credentials.enc")
        .read_bytes()
        .decode("ascii")
    )
    free_text = f"debug dump: {ciphertext_text} end"
    masked = redact(free_text)
    assert REDACTED in masked
    assert ciphertext_text not in masked


def test_audit_log_never_leaks_credential_value(tmp_path, env_file):
    store = CredentialStore(env_path=env_file)
    store.put("acc1", {"token": "hunter2-real-token-value"})
    ciphertext_text = (
        (env_file.parent / ".data" / "accounts" / "acc1" / "credentials.enc")
        .read_bytes()
        .decode("ascii")
    )

    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(
        AuditEntry(
            action_type="account_store",
            tool="credential_store.put",
            verdict="allow",
            reason=f"stored blob {ciphertext_text}",  # simulates an accidental free-text leak
        )
    )
    raw = (tmp_path / "audit.jsonl").read_text()
    assert ciphertext_text not in raw
    assert "hunter2-real-token-value" not in raw


def test_generated_fernet_token_matches_gAAAAA_pattern():
    """A freshly encrypted Fernet TOKEN always starts "gAAAAA" (version+timestamp
    header) -> caught by the dedicated token pattern."""
    key = Fernet.generate_key()
    fernet = Fernet(key)
    token = fernet.encrypt(json.dumps({"token": "x"}).encode())
    assert find_secret(token.decode("ascii")) is not None


def test_generated_fernet_key_alone_does_not_match_bare_shape():
    """A bare Fernet key (44 chars, urlsafe-b64, trailing '=') has the EXACT same
    shape as any base64url-encoded 32-byte digest (sha256 hash, ETag, S3 signature) —
    matching on shape alone made `find_secret` (which feeds the Lớp A hard-block, not
    just redaction) refuse legitimate actions carrying an unrelated content-hash. The
    pattern is anchored to the key/env-var NAME instead (see the next test), so a
    bare key with no naming context around it is no longer flagged here."""
    key = Fernet.generate_key()
    assert find_secret(key.decode("ascii")) is None


def test_base64_sha256_digest_is_not_flagged_as_a_secret():
    """The false-positive this fix removes: an ordinary base64url sha256 digest (a
    content-hash, ETag, or signed-URL `sig=` param) has the identical 43-char+'='
    shape as a Fernet key but is not a credential — it must never hard-block."""
    import base64
    import hashlib

    digest = base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).decode("ascii")
    assert find_secret(digest) is None
    assert find_secret(f"https://cdn.example.com/a?sig={digest}") is None


def test_master_key_named_in_context_still_matches():
    """The real risk this pattern guards against: `MY_CREW_CRED_KEY` (or a
    `cred_key`-labeled field) echoed next to its own name in a log line or free-text
    field — anchored on the name, not the bare shape, so it still catches this."""
    key = Fernet.generate_key().decode("ascii")
    assert find_secret(f"MY_CREW_CRED_KEY={key}") is not None
    assert find_secret(f'{{"cred_key": "{key}"}}') is not None
