"""J3 — a credential survives a real round-trip without ever leaking in plaintext.

`routes_account_store` makes a strong, load-bearing claim in its own docstring: a
credential VALUE is accepted on POST but "never echoed back or logged". That claim is
only checkable against a REAL process — the log is a file a live server writes, and the
response bodies are what a real HTTP client actually receives. An in-process test that
calls the handler directly sees neither, which is why this case did not exist before.

So the shape here is: post a token that could not occur by chance, then hunt for it.
Everywhere. Every byte of the home directory, every line of the serve log, every
response body the server hands back. The credential must be readable through the store
(otherwise the round-trip is broken) and unreadable everywhere else (otherwise the
encryption is decorative).

The sentinel is deliberately a long random hex string: a substring search for something
like "secret" would collide with ordinary config text, and a search that can collide is
a search whose silence proves nothing.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys

import pytest

from tests.fullflow_live.topology import boot

ACCOUNT_ID = "j3-roundtrip-account"


@pytest.fixture
def fleet(tmp_path, live_api_key):
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        yield server
    finally:
        server.stop()


#: Note the `load_dotenv` FIRST. The Fernet master key lives in the home's `.env`, and
#: `_load_or_create_master_key` treats "not in os.environ" as "first use ever" — so a
#: reader that skips loading `.env` silently generates a SECOND key and then cannot
#: decrypt anything written under the first. Measured the hard way: this script without
#: the load produced `InvalidToken` against a file the server had just written
#: correctly. Every real entrypoint (`mpm_lifecycle_cmds`, `mpm_onboarding_cmds`) loads
#: `MY_CREW_HOME/.env` before touching the store, so this mirrors the product's own
#: boot order rather than inventing one.
_READ_SCRIPT = """
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(os.environ["MY_CREW_HOME"]) / ".env")
from my_crew.config.credential_store import CredentialStore

print(json.dumps({"value": CredentialStore().get(sys.argv[1])}))
"""


def _read_credential(home, account_id: str) -> dict:
    """Decrypt through the real store, in a subprocess bound to the fleet's home.

    Same reason as the escalation journey: `MY_CREW_HOME` is read at import time, so
    only a fresh interpreter can be pointed at the tmp home safely.
    """
    env = dict(os.environ)
    env["MY_CREW_HOME"] = str(home)
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-c", _READ_SCRIPT, account_id],
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"reading the credential back failed rc={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])["value"]


def _files_containing(home, needle: str) -> list[str]:
    """Every file under the home whose bytes contain `needle`.

    Bytes, not text: a leak into a binary-ish file (a sqlite page, a cache) is still a
    leak, and decoding-as-text would skip exactly the files most likely to hide one.
    """
    probe = needle.encode()
    hits = []
    for path in home.rglob("*"):
        if not path.is_file():
            continue
        try:
            if probe in path.read_bytes():
                hits.append(str(path.relative_to(home)))
        except OSError:  # a file the server is mid-write on is not a leak
            continue
    return hits


def test_j3_a_credential_round_trips_without_leaking_in_plaintext(fleet):
    # A value no amount of ordinary config text could contain by accident.
    token = "j3tok" + secrets.token_hex(24)
    refresh = "j3ref" + secrets.token_hex(24)
    bodies: list[str] = []

    def record(code, body):
        bodies.append(json.dumps(body, ensure_ascii=False))
        return code, body

    code, body = record(*fleet.request(
        "PUT", f"/api/connections/accounts/{ACCOUNT_ID}",
        {"value": {"token": token, "refresh": refresh, "meta": {"kind": "j3"}}},
        timeout=30,
    ))
    assert code == 200, f"storing the credential failed {code}: {body!r}"

    # -- it really went in: the store can decrypt exactly what was posted -------------
    stored = _read_credential(fleet.home, ACCOUNT_ID)
    assert stored.get("token") == token, (
        f"round-trip corrupted the credential: stored {stored!r} — an encrypted store "
        "that cannot return the value is worse than no store at all"
    )
    assert stored.get("refresh") == refresh

    # -- and the listing names the account without ever naming the secret -------------
    code, listing = record(*fleet.get("/api/connections/accounts", timeout=30))
    assert code == 200, f"listing failed {code}: {listing!r}"
    assert ACCOUNT_ID in json.dumps(listing), f"stored account missing from listing: {listing!r}"

    # -- the hunt --------------------------------------------------------------------
    # 1. No response body may carry the value back. This is the claim the route's
    #    docstring makes and the one an operator's browser history depends on.
    for raw in bodies:
        assert token not in raw and refresh not in raw, (
            f"a credential value was echoed back in an HTTP response: {raw[:400]}"
        )

    # 2. Not in the log. A real server writing a real log file is the only place this
    #    is checkable, and secrets in logs are the classic way encryption gets bypassed.
    log = fleet.log()
    assert token not in log and refresh not in log, (
        "a credential value was written to the serve log — encryption at rest is "
        "irrelevant if the plaintext is sitting in a log file next to it"
    )

    # 3. Not in plaintext ANYWHERE on disk. The .enc file must exist (proving something
    #    was persisted) and must not contain the raw token (proving it was encrypted).
    leaks = _files_containing(fleet.home, token) + _files_containing(fleet.home, refresh)
    assert not leaks, f"credential found in plaintext on disk: {leaks}"

    enc = fleet.home / ".data" / "accounts" / ACCOUNT_ID / "credentials.enc"
    assert enc.exists() and enc.stat().st_size > 0, (
        f"no ciphertext at {enc} — nothing was persisted, so the clean grep above "
        "proves nothing"
    )


def test_j3b_a_deleted_credential_is_gone_from_the_store_and_the_disk(fleet):
    """Deletion has to actually delete. A store that keeps recoverable ciphertext after
    a delete is a compliance problem, not a tidiness one."""
    token = "j3del" + secrets.token_hex(24)
    code, body = fleet.request(
        "PUT", f"/api/connections/accounts/{ACCOUNT_ID}",
        {"value": {"token": token}}, timeout=30,
    )
    assert code == 200, f"setup store failed {code}: {body!r}"
    enc = fleet.home / ".data" / "accounts" / ACCOUNT_ID / "credentials.enc"
    assert enc.exists(), "setup did not persist anything to delete"

    code, body = fleet.request("DELETE", f"/api/connections/accounts/{ACCOUNT_ID}", timeout=30)
    assert code == 200, f"delete failed {code}: {body!r}"
    assert body.get("deleted") is True, (
        f"delete reported deleted={body.get('deleted')!r} for a credential that "
        f"existed at {enc} — the report disagrees with the disk"
    )

    assert not enc.exists(), f"ciphertext survived the delete at {enc}"
    code, listing = fleet.get("/api/connections/accounts", timeout=30)
    assert ACCOUNT_ID not in json.dumps(listing), (
        f"deleted account still listed: {listing!r}"
    )

    # Deleting again is explicitly not an error, but must report that nothing existed.
    code, body = fleet.request("DELETE", f"/api/connections/accounts/{ACCOUNT_ID}", timeout=30)
    assert code == 200, f"second delete errored {code}: {body!r}"
    assert body.get("deleted") is False, (
        f"a no-op delete claimed deleted={body.get('deleted')!r} — a caller cannot "
        "distinguish 'removed it' from 'there was nothing there'"
    )
