"""An operator notice must survive an operator who does not use Telegram.

Every channel path used to end at `send_telegram_message`, so an unbound agent pushed
nothing at all and the content sat in the web app waiting to be discovered. These pin
the fallback order and, more importantly, the three-state answer (True / False / None)
the agent-walking caller depends on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from my_crew.config.smtp_config import SmtpConfig
from my_crew.runtime import operator_channels as oc


def _loaded(*, telegram_id: str = "", smtp: SmtpConfig | None = None):
    """One agent as the channel layer sees it: a config with bindings, nothing more."""
    telegram = SimpleNamespace(ops_operator_id=telegram_id) if telegram_id else None
    return SimpleNamespace(
        config=SimpleNamespace(
            telegram=telegram, smtp=smtp, slack_external_channels=(),
        ),
        settings=SimpleNamespace(),
        profile_id="agent-x",
    )


_SMTP = SmtpConfig(smtp_host="mail.example.test", smtp_user="u", from_addr="bot@example.test",
                   recipients=("ceo@example.test",))


def test_no_channel_configured_answers_none_not_false(monkeypatch):
    # None and False mean different things to the caller: None ("this agent cannot
    # speak") keeps it walking the registry, False ("tried and failed") stops it.
    monkeypatch.delenv(oc.OPERATOR_WEBHOOK_URL_ENV, raising=False)
    monkeypatch.delenv(oc.OPERATOR_EMAIL_ENV, raising=False)
    assert oc.send_via_channels("hi", loaded=_loaded()) is None


def _no_ssrf_check(monkeypatch):
    """Skip the real DNS-resolving SSRF guard in tests: `*.example.test` hostnames do
    not resolve, and the guard itself is covered exhaustively by
    tests/test_webhook_url_guard.py — these tests are about the channel-selection and
    redirect-handling behavior, not the guard."""
    monkeypatch.setattr(
        "my_crew.runtime.webhook_url_guard.assert_safe_webhook_url", lambda url: None
    )


def test_webhook_alone_delivers_when_telegram_is_absent(monkeypatch):
    # The whole point of the arc: no Telegram binding anywhere, operator still pushed.
    _no_ssrf_check(monkeypatch)
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://hook.example.test/notice")
    seen: dict = {}

    class _Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = req.data
        return _Resp()

    monkeypatch.setattr(oc._NO_REDIRECT_OPENER, "open", _open)
    assert oc.send_via_channels("kẹt rồi", loaded=_loaded()) is True
    assert seen["url"] == "https://hook.example.test/notice"
    # Discord reads `content`, most others read `text` — one payload serves both, which
    # is why there is no per-vendor adapter.
    assert b'"content"' in seen["body"] and b'"text"' in seen["body"]


def test_webhook_redirect_to_internal_host_is_not_followed(monkeypatch):
    # A host that was public when saved (or at an earlier send) could 302 an attacker-
    # controlled response toward an internal target. The redirect must not be followed —
    # it must surface as a failure, never as a silent POST to the internal host.
    _no_ssrf_check(monkeypatch)
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://hook.example.test/notice")

    posted_to: list[str] = []

    def _open(req, timeout=None):
        posted_to.append(req.full_url)
        import urllib.error

        # Simulate what the real opener does once `_NoRedirectHandler.redirect_request`
        # returns None on a 302: HTTPError is raised instead of a second request firing.
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        raise urllib.error.HTTPError(req.full_url, 302, "Found", headers, None)

    monkeypatch.setattr(oc._NO_REDIRECT_OPENER, "open", _open)
    assert oc.send_via_channels("x", loaded=_loaded()) is False
    # Only the original URL was ever requested — nothing was sent to the redirect target.
    assert posted_to == ["https://hook.example.test/notice"]


def test_smtp_takes_over_when_telegram_fails(monkeypatch):
    # A configured-but-broken channel must not swallow the notice: order matters only
    # until something works.
    monkeypatch.delenv(oc.OPERATOR_WEBHOOK_URL_ENV, raising=False)
    monkeypatch.setenv(oc.OPERATOR_EMAIL_ENV, "ceo@example.test")
    monkeypatch.setattr(oc, "_try_telegram", lambda *a, **k: False)
    sent: dict = {}

    def _send(smtp, *, to, subject, body, timeout):
        sent.update(to=to, subject=subject, body=body)

    monkeypatch.setattr("my_crew.actions.email_write.send_plain_email", _send)
    assert oc.send_via_channels("kẹt", loaded=_loaded(smtp=_SMTP), subject="S") is True
    assert sent["to"] == ["ceo@example.test"] and sent["subject"] == "S"


def test_every_configured_channel_failing_answers_false(monkeypatch):
    # False, not None: the agent HAS channels, so the caller should not keep looking
    # for another agent — it should report the notice undelivered.
    _no_ssrf_check(monkeypatch)
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://hook.example.test/x")

    def _boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(oc._NO_REDIRECT_OPENER, "open", _boom)
    assert oc.send_via_channels("x", loaded=_loaded()) is False


def test_a_raising_channel_does_not_block_the_next_one(monkeypatch):
    # Contract with every caller is never-raises; a channel that explodes must be
    # logged and stepped over, not propagated into a background tick.
    _no_ssrf_check(monkeypatch)
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://hook.example.test/x")
    monkeypatch.setenv(oc.OPERATOR_EMAIL_ENV, "ceo@example.test")

    def _boom(*a, **k):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(oc, "_try_telegram", _boom)
    monkeypatch.setattr(oc._NO_REDIRECT_OPENER, "open",
                        lambda *a, **k: pytest.fail("should have stopped at smtp"))
    monkeypatch.setattr("my_crew.actions.email_write.send_plain_email",
                        lambda *a, **k: None)
    assert oc.send_via_channels("x", loaded=_loaded(smtp=_SMTP)) is True


def test_dry_run_telegram_counts_as_delivered_and_blocks_real_email(monkeypatch):
    # A rehearsing agent must not start sending real mail because its rehearsal "did
    # not deliver" — dry_run is a successful rehearsal, not a failed send.
    monkeypatch.setenv(oc.OPERATOR_EMAIL_ENV, "ceo@example.test")
    monkeypatch.setattr("my_crew.actions.email_write.send_plain_email",
                        lambda *a, **k: pytest.fail("dry-run must not send real email"))

    class _Gw:
        def close(self):
            pass

    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: _Gw())
    monkeypatch.setattr("my_crew.actions.telegram_write.send_telegram_message",
                        lambda *a, **k: SimpleNamespace(status="dry_run"))
    assert oc.send_via_channels("x", loaded=_loaded(telegram_id="42", smtp=_SMTP)) is True


def test_webhook_send_re_validates_and_blocks_rebound_dns(monkeypatch):
    # The write-time guard only proves the URL was public when saved. If DNS for that
    # host later rebinds to an internal address, the send-time re-check inside
    # `_try_webhook` must catch it before any request goes out.
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://hook.example.test/x")
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 0))]
    )
    monkeypatch.setattr(
        oc._NO_REDIRECT_OPENER, "open",
        lambda *a, **k: pytest.fail("must not reach the network once DNS rebinds internal"),
    )
    assert oc.send_via_channels("x", loaded=_loaded()) is False


def test_channels_for_lists_only_what_is_usable(monkeypatch):
    # Drives the health surface: the operator should be able to SEE that nothing can
    # reach them, rather than inferring it from silence.
    monkeypatch.delenv(oc.OPERATOR_WEBHOOK_URL_ENV, raising=False)
    monkeypatch.delenv(oc.OPERATOR_EMAIL_ENV, raising=False)
    assert oc.channels_for(_loaded()) == []
    assert oc.channels_for(_loaded(telegram_id="42")) == ["telegram"]
    # smtp with recipients baked into the config needs no OPERATOR_EMAIL to count
    assert oc.channels_for(_loaded(smtp=_SMTP)) == ["smtp"]
    monkeypatch.setenv(oc.OPERATOR_WEBHOOK_URL_ENV, "https://h.example.test")
    assert oc.channels_for(_loaded(telegram_id="42", smtp=_SMTP)) == [
        "telegram", "smtp", "webhook"]
