"""v47 Phase 2: opt-in sandbox image pre-pull — warm the deep_agent image ahead of time so the
first shell step doesn't pay the pull. Daemon-safe: a missing daemon / offline pull returns a
clear result dict, never an exception. No deepagents / Docker dependency (a fake client drives it).
"""

from __future__ import annotations

from my_crew.runtime_backends.sandbox_backend import (
    SANDBOX_DEFAULT_IMAGE,
    prepull_sandbox_image,
)


class _Images:
    def __init__(self, *, present: bool, pull_error: Exception | None = None):
        self._present = present
        self._pull_error = pull_error
        self.pulled: list[str] = []

    def get(self, image):
        if self._present:
            return object()
        raise Exception("not found locally")  # noqa: TRY002 — mimics docker ImageNotFound

    def pull(self, image):
        if self._pull_error is not None:
            raise self._pull_error
        self.pulled.append(image)
        return object()


class _Client:
    def __init__(self, images):
        self.images = images


def test_present_image_is_a_noop():
    imgs = _Images(present=True)
    r = prepull_sandbox_image(client=_Client(imgs))
    assert r["ok"] is True and r["pulled"] is False
    assert r["image"] == SANDBOX_DEFAULT_IMAGE
    assert imgs.pulled == []  # never pulled — already present


def test_absent_image_is_pulled_once():
    imgs = _Images(present=False)
    r = prepull_sandbox_image("custom:tag", client=_Client(imgs))
    assert r["ok"] is True and r["pulled"] is True
    assert imgs.pulled == ["custom:tag"]


def test_daemon_absent_returns_clear_result_no_crash(monkeypatch):
    # No client passed → from_env is attempted; force it to raise like a down daemon.
    import sys
    import types

    fake = types.ModuleType("docker")

    def _boom(*a, **k):
        raise RuntimeError("Cannot connect to the Docker daemon")

    fake.from_env = _boom
    monkeypatch.setitem(sys.modules, "docker", fake)

    r = prepull_sandbox_image()
    assert r["ok"] is False and r["pulled"] is False
    assert "Docker" in r["message"]  # clear, actionable — not a traceback


def test_offline_pull_error_is_best_effort():
    imgs = _Images(present=False, pull_error=RuntimeError("network is unreachable"))
    r = prepull_sandbox_image(client=_Client(imgs))
    assert r["ok"] is False and r["pulled"] is False
    assert "thất bại" in r["message"]
