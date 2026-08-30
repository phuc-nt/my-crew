"""Generic service-credential resolver (Zalo business fleet P4, architecture D5).

Adapters that need an external-service credential (Zalo OA send, future ads-pack,
future per-account Gmail) call `resolve_service_credentials` instead of reading
`.env` or `credential_store.CredentialStore` directly, so the priority order lives
in exactly one place — the same reasoning `config/telegram_token.py` documents for
the read/write split on the Telegram bot token.
"""

from __future__ import annotations

import os

from my_crew.config.credential_store import CredentialStore, CredentialStoreError


def resolve_service_credentials(
    block: dict, *, store: CredentialStore | None = None
) -> dict | None:
    """Resolve a service credential dict from a profile-style config block.

    Priority (P4 architecture, D5): `block["account"]` (an account-store id) wins over
    `block["token_env"]` (a plain env-var NAME whose value is a bare token string, the
    pre-existing indirection pattern from `config/telegram_token.py`) wins over `None`.

    This is intentionally GENERIC — it takes any dict shape, not a Zalo-specific type,
    so adapters (Zalo P1, ads-pack P6, future per-account Gmail) share one resolution
    order without each reading `.env`/the store directly. Returns `None` only when
    neither `account` nor `token_env` is present in `block` at all — a PRESENT but
    broken reference (bad account id, unset env var) raises instead of silently
    falling through to the next branch, so a typo'd account id doesn't quietly send
    an unauthenticated request using a stale env token.
    """
    account_id = block.get("account")
    if account_id:
        return (store or CredentialStore()).get(account_id)

    token_env = block.get("token_env")
    if token_env:
        token = os.environ.get(token_env, "").strip()
        if not token:
            raise CredentialStoreError(
                f"token_env {token_env!r} is set in config but the env var is empty/unset."
            )
        return {"token": token}

    return None
