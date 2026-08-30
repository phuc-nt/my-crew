"""Account-store credential routes (Zalo business fleet P4).

A SEPARATE surface from `routes_connections.merge_env` writes: values here go
straight into the encrypted `CredentialStore` (`.data/accounts/<id>/credentials.enc`),
never through `.env`. Mounted under `routes_connections.router` so `/api/connections`
stays the one prefix for "the UI version of secrets config", without adding a new
top-level router to `server/app.py`.

Load-bearing: a credential VALUE is accepted on POST but never echoed back or logged
— responses and log lines name only the account-id and the action, same posture as
`env_writer.read_key_presence` (presence/list, never content).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

from my_crew.config.credential_store import CredentialStore, CredentialStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["connections"])


@router.get("")
def list_accounts() -> dict:
    """Account ids that have a stored credential. Never the credential value."""
    return {"accounts": CredentialStore().list()}


@router.put("/{account_id}")
def put_account_credential(account_id: str, value: dict = Body(..., embed=True)) -> dict:  # noqa: B008
    """Store (or rotate) the credential blob for `account_id`. The request body's
    `value` dict is encrypted whole and never appears in the response or a log line."""
    if not isinstance(value, dict) or not value:
        raise HTTPException(status_code=400, detail="value phải là object JSON không rỗng.")
    try:
        CredentialStore().put(account_id, value)
    except ValueError as exc:  # invalid account id
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CredentialStoreError as exc:  # e.g. master key unusable
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info("account_store: put account_id=%s", account_id)
    return {"ok": True, "account_id": account_id}


@router.delete("/{account_id}")
def delete_account_credential(account_id: str) -> dict:
    """Remove the stored credential for `account_id`. A missing credential is not an
    error — `deleted` reports whether a file actually existed."""
    try:
        existed = CredentialStore().delete(account_id)
    except ValueError as exc:  # invalid account id
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("account_store: delete account_id=%s existed=%s", account_id, existed)
    return {"ok": True, "account_id": account_id, "deleted": existed}
