"""Encrypted per-account credential store (Zalo business fleet P4).

Each external-service account (Zalo OA, Meta, future Gmail-per-account) gets one
encrypted blob at `.data/accounts/<account-id>/credentials.enc`: a JSON dict
(token/secret/refresh/meta) encrypted whole with Fernet. This is the SAME
"encrypt one blob, atomic temp+replace" shape as `server/env_writer.py` uses for
`.env`, so this module follows that file's pattern rather than inventing a new one.

Master key: `MY_CREW_CRED_KEY` (a base64 Fernet key) lives in `.env`, generated once
on first use and written through `env_writer.merge_env` — same choke point every
other secret in this repo goes through, so a rogue key name still can't sneak past
the `.env` whitelist. The master key itself is plaintext in `.env`, same posture as
every other credential in this repo today (OPENROUTER_API_KEY etc.) — not worse,
documented in `docs/system-architecture.md`.

Threat model / what this does NOT do: it does not protect against an attacker who
already has read access to the host `.env` AND `.data/` (the key and the ciphertext
sit next to each other, as with any local secrets-at-rest scheme without an HSM/KMS).
What it DOES do: a stray `.data/` backup, log capture, or `grep -r` over the repo
never turns up a plaintext token — the value is only ever in memory, decrypted at
the point of use.

Never logs or returns a credential value on error — every raised exception message
names the account-id and the failure kind only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from my_crew.config.settings import DATA_DIR

logger = logging.getLogger(__name__)

#: Same shape as the agent-id jail in `runtime/agent_paths.py` — a single safe path
#: segment, no "/", no "..", so an account id can never escape `.data/accounts/`.
_ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: Env var name for the Fernet master key. Whitelisted in `server/env_writer
#: .CREDENTIAL_STORE_WRITABLE_KEYS` — that frozenset (not a client-facing route) is the
#: only allow-list this module's own write ever uses.
MASTER_KEY_ENV = "MY_CREW_CRED_KEY"

_ACCOUNTS_DIR_NAME = "accounts"
_CRED_FILENAME = "credentials.enc"
_BACKUP_SUFFIX = ".bak.enc"


class CredentialStoreError(RuntimeError):
    """Base class for credential-store failures. Message never contains a secret value."""


class CredentialDecryptError(CredentialStoreError):
    """Raised when a stored blob cannot be decrypted: wrong/missing master key, or the
    ciphertext file is corrupted. Deliberately loud — a silent empty-dict return here
    would look like "no credential configured" and send a service call out with no
    auth, which is a worse failure than a crash."""


def _validate_account_id(account_id: str) -> str:
    if not _ACCOUNT_ID_RE.match(account_id):
        raise ValueError(
            f"Invalid account id {account_id!r}: must match {_ACCOUNT_ID_RE.pattern} "
            "(lowercase alnum, '-'/'_', no '/' or '..')."
        )
    return account_id


def _account_dir(account_id: str) -> Path:
    return DATA_DIR / _ACCOUNTS_DIR_NAME / _validate_account_id(account_id)


def _cred_path(account_id: str) -> Path:
    return _account_dir(account_id) / _CRED_FILENAME


def _load_or_create_master_key(env_path: Path | None = None) -> bytes:
    """Return the Fernet master key, generating + persisting one on first use.

    Reads `MY_CREW_CRED_KEY` from the live process environment first (the normal
    path once `.env` has been loaded at process start). If unset, generates a fresh
    Fernet key, writes it to `.env` through the SAME whitelisted `env_writer.merge_env`
    choke point every other secret in this repo uses, and also sets it on
    `os.environ` for the rest of THIS process's lifetime (mirrors `routes_connections
    .put_operator_keys`, which does the same immediate-visibility trick after a write).
    """
    existing = os.environ.get(MASTER_KEY_ENV, "").strip()
    if existing:
        return existing.encode("ascii")

    new_key = Fernet.generate_key()
    from my_crew.server import env_writer

    env_writer.merge_env(
        {MASTER_KEY_ENV: new_key.decode("ascii")},
        allow=env_writer.CREDENTIAL_STORE_WRITABLE_KEYS,
        env_path=env_path,
    )
    os.environ[MASTER_KEY_ENV] = new_key.decode("ascii")
    logger.info("credential_store: generated new %s (first use)", MASTER_KEY_ENV)
    return new_key


def _fernet(env_path: Path | None = None) -> Fernet:
    key = _load_or_create_master_key(env_path=env_path)
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise CredentialStoreError(
            f"{MASTER_KEY_ENV} in .env is not a valid Fernet key — "
            "cannot encrypt/decrypt any credential until it is fixed or regenerated."
        ) from exc


class CredentialStore:
    """Encrypted at-rest storage for one account's service credential blob.

    `env_path` is test-only indirection (mirrors `env_writer.merge_env`'s own
    `env_path` parameter) so tests never touch the real `.env`.
    """

    def __init__(self, env_path: Path | None = None) -> None:
        self._env_path = env_path

    def put(self, account_id: str, value: dict) -> None:
        """Encrypt `value` (JSON-serializable dict) and write it for `account_id`.

        Rotation: if a credential already exists, it is copied to `.bak.enc` (ONE
        backup kept, overwriting any prior backup) before the new value replaces it.
        Write is atomic (temp file + os.replace), matching `env_writer.merge_env`.
        """
        _validate_account_id(account_id)
        if not isinstance(value, dict):
            raise TypeError(
                f"credential value for {account_id!r} must be a dict, got {type(value)}"
            )

        fernet = _fernet(self._env_path)
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        ciphertext = fernet.encrypt(payload)

        account_dir = _account_dir(account_id)
        account_dir.mkdir(parents=True, exist_ok=True)
        cred_path = _cred_path(account_id)
        backup_path = account_dir / f"{_CRED_FILENAME}{_BACKUP_SUFFIX}"

        if cred_path.exists():
            shutil.copy2(cred_path, backup_path)  # rotation: keep exactly one prior version
            os.chmod(backup_path, 0o600)

        tmp = account_dir / f"{_CRED_FILENAME}.{os.getpid()}.tmp"
        tmp.write_bytes(ciphertext)
        os.chmod(tmp, 0o600)
        os.replace(tmp, cred_path)  # atomic swap, same as env_writer.merge_env
        os.chmod(cred_path, 0o600)
        logger.info("credential_store: put account_id=%s", account_id)

    def get(self, account_id: str) -> dict:
        """Decrypt and return the stored dict for `account_id`.

        Raises CredentialDecryptError with a clear message (never the ciphertext or
        any decrypted value) if: no credential is stored, the master key cannot
        decrypt it (wrong/rotated key), or the file is corrupted/truncated.
        """
        _validate_account_id(account_id)
        cred_path = _cred_path(account_id)
        if not cred_path.exists():
            raise CredentialDecryptError(
                f"no credential stored for account {account_id!r} (expected {cred_path})."
            )

        ciphertext = cred_path.read_bytes()
        fernet = _fernet(self._env_path)
        try:
            payload = fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise CredentialDecryptError(
                f"cannot decrypt credential for account {account_id!r}: "
                f"{MASTER_KEY_ENV} does not match, or the file is corrupted."
            ) from exc

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CredentialDecryptError(
                f"credential for account {account_id!r} decrypted but is not valid JSON "
                "— the store is corrupted."
            ) from exc
        if not isinstance(parsed, dict):
            raise CredentialDecryptError(
                f"credential for account {account_id!r} decrypted to a non-dict payload "
                "— the store is corrupted."
            )
        return parsed

    def delete(self, account_id: str) -> bool:
        """Remove the stored credential (and its backup, if any) for `account_id`.
        Returns True if a credential file existed and was removed, False if there was
        nothing to delete (not an error — deleting an absent credential is a no-op)."""
        _validate_account_id(account_id)
        cred_path = _cred_path(account_id)
        backup_path = _account_dir(account_id) / f"{_CRED_FILENAME}{_BACKUP_SUFFIX}"
        existed = cred_path.exists()
        cred_path.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        logger.info("credential_store: delete account_id=%s existed=%s", account_id, existed)
        return existed

    def list(self) -> list[str]:
        """Account ids that currently have a stored credential, sorted. Never reads or
        decrypts any blob — this only lists directory names."""
        accounts_root = DATA_DIR / _ACCOUNTS_DIR_NAME
        if not accounts_root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in accounts_root.iterdir()
            if entry.is_dir() and (entry / _CRED_FILENAME).exists()
        )
