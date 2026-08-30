"""X3 — with auth ON, an unauthenticated caller cannot reach the fleet.

`auth.py` states its threat model plainly: one CEO, a LAN or Mac-mini deployment, and
"the one thing that must not happen" is someone else on the network opening the dashboard
and clicking approve — unlocking a Lớp B action — or reading secrets. Auth here IS the
protection, not decoration.

Every other case in this suite runs with auth OFF, which is the documented localhost-dev
path and is what `boot` gives you by default. That means the entire authenticated
configuration — the middleware, the login handler, the session cookie, the public-prefix
allowlist — has never been exercised by a real request in this suite. The harness's own
comment even anticipates this file: "the one case that cares sets it explicitly."

What makes this worth running against a live process rather than a TestClient: the
middleware order is a real bug class (`SessionMiddleware` must wrap `AuthMiddleware`, or
the session is read before it is populated), and it is wired at app-build time inside the
served process. Only a real boot proves the wiring the operator actually gets.

Four things are asserted, and each one is a distinct way the gate could fail open:

1. an unauthenticated API call is refused (401), including the control-plane routes that
   spend money and the credential routes that hold secrets;
2. the public allowlist really is limited to what it claims — `/health` and `/api/me`
   answer, and `/api/me` reports NOT authenticated rather than defaulting to true;
3. a WRONG password does not get in, and a right one does;
4. after logging in, the same previously-refused call now succeeds — proving the 401s
   were the gate discriminating, not the server being broken.

No model is involved anywhere here, so none of it can flake.
"""

from __future__ import annotations

import pytest

from tests.fullflow_live.topology import boot, seed_home

PASSWORD = "x3-correct-horse-battery"
USERNAME = "ceo"

#: Routes that MUST be behind the gate. Chosen for what they can do, not for coverage:
#: delegate spends real money, the account store holds decrypted-on-read credentials, and
#: the overview leaks the fleet's shape. If any of these answers without a session, the
#: threat model in auth.py's docstring is violated.
GUARDED = (
    ("GET", "/api/control-plane/overview"),
    ("GET", "/api/connections/accounts"),
    ("POST", "/api/control-plane/delegate"),
)


@pytest.fixture
def authed_fleet(tmp_path, live_api_key):
    """A fleet booted with auth genuinely ON.

    The hash is generated through the product's own `hash_password` rather than a
    hardcoded bcrypt string, so this case cannot drift from however the product hashes;
    and the session secret is a real value, because `assert_session_secret_safe` refuses
    to build the app with auth on and the dev constant in place — a guard this fixture
    would otherwise trip on boot.
    """
    from my_crew.server.auth import hash_password

    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key)
    server = boot(home, api_key=live_api_key, seed=False, env_overrides={
        "WEB_AUTH_USERNAME": USERNAME,
        "WEB_AUTH_PASSWORD_HASH": hash_password(PASSWORD),
        "WEB_SESSION_SECRET": "x3-a-real-session-secret-not-the-dev-constant",
    })
    try:
        yield server
    finally:
        server.stop()


def test_x3_an_unauthenticated_caller_is_refused_then_admitted_after_login(authed_fleet):
    # -- 1. locked out ----------------------------------------------------------------
    for method, path in GUARDED:
        payload = {"brief": "x3 must never run"} if method == "POST" else None
        code, body = authed_fleet.request(method, path, payload, timeout=30)
        assert code == 401, (
            f"{method} {path} answered {code} WITHOUT a session — with auth on, this "
            f"route is reachable by anyone on the network: {body!r}"
        )

    # -- 2. the public allowlist is exactly as narrow as it claims ---------------------
    code, _ = authed_fleet.get("/health", timeout=30)
    assert code == 200, "/health must stay public — it is the liveness probe"

    code, me = authed_fleet.get("/api/me", timeout=30)
    assert code == 200, f"/api/me must stay public so the SPA can ask: got {code}"
    assert me.get("authenticated") is False, (
        f"/api/me reports {me!r} before any login — a client asking 'am I logged in' is "
        "being told yes, which is the answer that decides whether the SPA shows the "
        "dashboard or the login screen"
    )

    # -- 3. a wrong password does not get in ------------------------------------------
    code, body = authed_fleet.post(
        "/api/login", {"username": USERNAME, "password": "wrong-password"}, timeout=30
    )
    assert code == 401, f"a WRONG password was accepted ({code}): {body!r}"

    # Still locked out afterwards: a failed login must not leave a usable session behind.
    code, _ = authed_fleet.get("/api/control-plane/overview", timeout=30)
    assert code == 401, "a FAILED login still produced a working session"

    # -- 4. the right password does, and the gate opens --------------------------------
    code, body = authed_fleet.post(
        "/api/login", {"username": USERNAME, "password": PASSWORD}, timeout=30
    )
    assert code == 200, (
        f"the CORRECT password was refused ({code}: {body!r}) — every 401 above is then "
        "just a server that refuses everything, and proves nothing about the gate"
    )

    code, me = authed_fleet.get("/api/me", timeout=30)
    assert me.get("authenticated") is True and me.get("user") == USERNAME, (
        f"after a successful login /api/me still reports {me!r}"
    )

    # The discrimination proof: the SAME call that was refused now works. This is what
    # makes the 401s above evidence of a gate rather than of a broken server.
    code, body = authed_fleet.get("/api/control-plane/overview", timeout=30)
    assert code == 200, (
        f"still refused ({code}) AFTER a successful login — the session cookie is not "
        f"being honoured, which usually means SessionMiddleware and AuthMiddleware are "
        f"wired in the wrong order: {body!r}"
    )


def test_x3b_the_startup_guards_refuse_an_unsafe_configuration(tmp_path, live_api_key):
    """The fail-loud guards, asserted by really trying to boot an unsafe fleet.

    Two configurations must be refused AT STARTUP rather than served insecurely:

    - auth ON with the publicly-known dev session secret — anyone could forge a logged-in
      cookie, so the gate in the case above would be bypassable without a password;
    - a non-loopback bind with auth OFF — the dashboard exposed to the whole network.

    These are asserted by observing that `serve` DIES, because a warning that the operator
    scrolls past is exactly what `assert_bind_safe`'s docstring says this must not be
    ("fail loud, not warn"). A booted server here would mean the product shipped the
    insecure configuration.
    """
    from my_crew.server.auth import _DEV_SESSION_SECRET, hash_password

    # Each config carries the marker its OWN guard must put in the log. Asserting the
    # marker, not merely that boot raised: `boot` raises a RuntimeError for any startup
    # failure — a port clash, a syntax error, a missing dependency — so a bare
    # `except RuntimeError: pass` would call this green on a fleet that fails to start
    # for reasons having nothing to do with security. Measured: both configs really do
    # die on their own guard, and these are the strings they emit.
    unsafe_configs = (
        (
            "auth on with the public dev session secret",
            {
                "WEB_AUTH_PASSWORD_HASH": hash_password(PASSWORD),
                "WEB_SESSION_SECRET": _DEV_SESSION_SECRET,
            },
            "forge",  # "...an attacker could forge a session cookie"
        ),
        (
            "non-loopback bind with auth off",
            {"BIND_HOST": "0.0.0.0", "WEB_AUTH_PASSWORD_HASH": ""},  # noqa: S104 — the point
            "refusing to bind",
        ),
    )

    for label, overrides, marker in unsafe_configs:
        home = tmp_path / f"home-{abs(hash(label))}"
        seed_home(home, api_key=live_api_key)
        server = None
        try:
            server = boot(home, api_key=live_api_key, seed=False, env_overrides=overrides)
        except RuntimeError as exc:
            # Expected: the child exits during startup, which is the fail-loud behaviour
            # these guards promise. The marker proves WHICH failure it was.
            assert marker in str(exc), (
                f"[{label}] the fleet failed to boot, but not because of its security "
                f"guard — expected {marker!r} in the startup output. Something else is "
                f"broken and this case is no longer testing the guard:\n{exc}"
            )
            continue
        finally:
            if server is not None:
                server.stop()
        raise AssertionError(
            f"a fleet booted successfully with an UNSAFE configuration ({label}) — the "
            "startup guard did not fire, so this configuration would be served to the "
            "network as-is"
        )
