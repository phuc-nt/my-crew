"""X1 — a hostile account id cannot escape the credential sandbox, at either layer.

The credential store turns an account id straight into a filesystem path
(`_account_dir` → `DATA_DIR / "accounts" / account_id`). That is the classic shape of a
path-traversal bug: an id like `../../../../etc/my-crew-owned` would, without a guard,
make the server write an encrypted blob wherever the caller pointed it — as the
operator's own user, on their own machine.

**Measured before it was asserted, and the result changed this file.** Probing every
hostile id against a running fleet shows TWO different defenses, not one:

| id                | status | stopped by                                    |
|-------------------|--------|-----------------------------------------------|
| `../escape`       | 405    | the ROUTER — a `/`-bearing path never matches |
| `a/../../escape`  | 405    | the router                                    |
| `sub/dir`         | 405    | the router                                    |
| `%2e%2e%2fescape` | 405    | the router (decoded before routing)           |
| `""`              | 405    | the router                                    |
| `UPPER`           | 400    | `_validate_account_id`                        |
| `-leading-hyphen` | 400    | `_validate_account_id`                        |

So a genuinely traversing id never reaches `_validate_account_id` over HTTP at all. That
is defense in depth working as intended — but it means a test that sends `../escape` and
sees it refused has NOT tested the store's guard, and a docstring claiming otherwise
would be describing a mechanism that never ran.

This file therefore asserts the two layers separately:

- **`test_x1`** — over real HTTP, no hostile id is accepted and nothing is written. This
  pins the OUTER layer (routing) and the observable outcome an attacker actually gets.
- **`test_x1c`** — calls `_validate_account_id` directly on the same traversing ids, the
  only way to reach the INNER guard. Without this, someone could delete the regex
  entirely and every HTTP-level assertion here would still pass, because routing would
  keep covering for it. That is precisely the silent single-point-of-failure that
  layered defenses are supposed to prevent, so it gets its own case.

Nothing here is a model decision, so nothing here can flake: the guards are a router and
a regex, and the assertions are status codes and a file that must not exist. That is the
point of an adversarial case — pin a blocking layer, never a model's willingness to
refuse.
"""

from __future__ import annotations

import json

import pytest

from tests.fullflow_live.topology import boot

#: Ids that genuinely try to leave the accounts directory. Every one of these is stopped
#: by ROUTING (405) rather than by the store's regex — see the table above.
TRAVERSING_IDS = (
    "../escape",
    "../../escape",
    "a/../../escape",
    "sub/dir",            # a separator alone is enough to make the id a path
    "%2e%2e%2fescape",    # percent-encoded, to prove decoding does not reopen the hole
)

#: Ids that DO reach `_validate_account_id` over HTTP and are refused with a 400. Not
#: traversals, but the only way an HTTP-level case can observe the inner guard running.
MALFORMED_IDS = (
    "UPPER",              # the regex is lowercase-only; case is part of the contract
    "-leading-hyphen",    # must start alnum, so a flag-looking id cannot be minted
)

#: A sentinel written INTO the payload. If a traversal ever did land, this is what would
#: be sitting in the escaped file, which makes a stray hit unambiguous when hunting.
SENTINEL = "x1-traversal-must-never-be-written"


@pytest.fixture
def fleet(tmp_path, live_api_key):
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        yield server
    finally:
        server.stop()


def test_x1_no_hostile_account_id_is_accepted_or_written_over_http(fleet):
    accounts_dir = fleet.home / ".data" / "accounts"
    before = {p for p in fleet.home.rglob("*") if p.is_file()}

    for account_id in TRAVERSING_IDS:
        code, body = fleet.request(
            "PUT", f"/api/connections/accounts/{account_id}",
            {"value": {"token": SENTINEL}}, timeout=30,
        )
        # 405, specifically: a traversing id does not match this route at all. Asserted
        # exactly rather than as a 4xx band because the code IS the evidence of which
        # layer stopped it — a 400 here would mean the request reached the handler, i.e.
        # routing now delivers `/`-bearing ids and only the regex stands between an
        # attacker and an arbitrary write. That is a real weakening and must be loud.
        assert code == 405, (
            f"traversing id {account_id!r} returned {code}, expected 405 — routing no "
            f"longer refuses path-shaped ids, so the store's regex is now the ONLY "
            f"defense left: {body!r}"
        )

    for account_id in MALFORMED_IDS:
        code, body = fleet.request(
            "PUT", f"/api/connections/accounts/{account_id}",
            {"value": {"token": SENTINEL}}, timeout=30,
        )
        assert code == 400, (
            f"malformed id {account_id!r} returned {code}, expected 400 from "
            f"_validate_account_id — the store's own guard did not fire: {body!r}"
        )

    # -- the disk is the real verdict --------------------------------------------------
    # A refusal that arrives after the file was already written is not a working guard.
    after = {p for p in fleet.home.rglob("*") if p.is_file()}
    new_files = after - before

    # The fleet is live, so its own tick loop legitimately writes logs, databases and
    # audit rows while this case runs. Those are not what is being hunted: the question
    # is only whether a credential blob appeared, anywhere.
    leaked = [
        p for p in new_files
        if p.name == "credentials.enc" or SENTINEL in _safe_read(p)
    ]
    assert not leaked, (
        f"a rejected account id still caused a write: {[str(p) for p in leaked]} — the "
        "refusal was returned after the damage, so the guard is decorative"
    )

    # And nothing may have appeared under the accounts directory even under a name this
    # case did not predict — the escape itself is the failure, whatever it is called.
    if accounts_dir.exists():
        assert not any(p.name == "credentials.enc" for p in accounts_dir.rglob("*")), (
            "a credential was persisted despite every id being rejected"
        )


def test_x1b_a_legitimate_account_id_still_works(fleet):
    """The positive control, and it is not optional.

    Every assertion above is satisfied by a store that rejects EVERYTHING — a typo in the
    regex, a route that refuses unconditionally, a broken store. That version of the
    product is badly broken and X1 alone would call it green. This case is what makes
    X1's refusals mean "the guards discriminate" rather than "nothing works".
    """
    code, body = fleet.request(
        "PUT", "/api/connections/accounts/x1-legit-account",
        {"value": {"token": "x1-legit-value"}}, timeout=30,
    )
    assert code == 200, (
        f"a VALID account id was refused ({code}: {body!r}) — the store rejects "
        "everything, so X1's refusals prove nothing about hostile ids specifically"
    )

    enc = fleet.home / ".data" / "accounts" / "x1-legit-account" / "credentials.enc"
    assert enc.exists() and enc.stat().st_size > 0, (
        f"valid id accepted but nothing persisted at {enc}"
    )

    code, listing = fleet.get("/api/connections/accounts", timeout=30)
    assert code == 200 and "x1-legit-account" in json.dumps(listing), (
        f"stored account missing from listing: {listing!r}"
    )


def test_x1c_the_store_guard_itself_refuses_traversal(fleet):
    """The INNER layer, reached directly — the only way to test it against traversal.

    Deliberately not an HTTP call: routing answers 405 for every one of these ids before
    a handler runs, so no request can carry them to the regex. Calling the function is
    therefore not a shortcut around the real system; it is the only path that reaches
    this particular guard with this particular input.

    Why it earns its place: delete `_validate_account_id`'s regex entirely and `test_x1`
    above still passes in full, because routing keeps covering for it. The store would
    then be one router change away from arbitrary writes, with a green suite. This case
    is what makes the second layer's absence visible.

    Runs inside the live fleet fixture so it stays in this file's live-gated package and
    shares the same boot, but it needs nothing from the server itself.
    """
    from my_crew.config.credential_store import _validate_account_id

    for account_id in (*TRAVERSING_IDS, *MALFORMED_IDS, "", "..", "a/b/../../../c"):
        with pytest.raises(ValueError):
            _validate_account_id(account_id)

    # The same discrimination check as X1b, one layer down: a guard that raises on
    # everything would satisfy every `pytest.raises` above while being useless.
    assert _validate_account_id("x1-legit-account") == "x1-legit-account", (
        "the store guard rejects even a valid id — it raises unconditionally, so the "
        "refusals above say nothing about traversal"
    )


def _safe_read(path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
