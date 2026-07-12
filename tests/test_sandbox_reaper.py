"""Reaper for orphaned deep_agent sandbox containers.

Locks the two things that would otherwise fail silently in production: parsing Docker's real
9-digit-nanosecond `Created` timestamp (a naive parse raises and disables the reaper), and the
label+age double-gate (never removing a live worker's fresh container or an unlabelled one).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.runtime_backends.sandbox_reaper import (
    _parse_docker_created,
    reap_orphaned_sandboxes,
)


def test_parse_real_nanosecond_created():
    # Docker emits 9-digit nanoseconds + Z; datetime.fromisoformat rejects that natively. The
    # reaper must parse it — otherwise every container is skipped and nothing is ever reaped.
    dt = _parse_docker_created("2026-07-12T10:04:33.123456789Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.hour == 10 and dt.minute == 4


def test_parse_created_without_fraction():
    dt = _parse_docker_created("2026-07-12T10:04:33Z")
    assert dt.year == 2026


class _FakeContainer:
    def __init__(self, created: str, *, removed: list):
        self.attrs = {"Created": created}
        self._removed = removed

    def remove(self, force=False):
        self._removed.append(self)


class _FakeClient:
    def __init__(self, containers):
        self._containers = containers

        class _C:
            def __init__(self, outer):
                self._outer = outer

            def list(self, all=False, filters=None):  # noqa: A002 — mirror docker SDK kwarg
                return self._outer._containers

        self.containers = _C(self)


def _iso_ago(seconds: int) -> str:
    # a real nanosecond-format timestamp `seconds` in the past
    dt = datetime.now(UTC) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z"


def test_reaps_only_containers_older_than_threshold():
    removed: list = []
    stale = _FakeContainer(_iso_ago(10_000), removed=removed)  # well past ttl+grace
    fresh = _FakeContainer(_iso_ago(5), removed=removed)  # young — a live worker's box
    client = _FakeClient([stale, fresh])

    n = reap_orphaned_sandboxes(client=client)
    assert n == 1
    assert stale in removed and fresh not in removed


def test_docker_unavailable_is_noop():
    # client=None + no docker importable in this path → the reaper returns 0, never raises.
    # (Simulate by passing a client whose list raises — the sweep isolates it to a no-op.)
    class _Boom:
        class containers:  # noqa: N801
            @staticmethod
            def list(all=False, filters=None):  # noqa: A002
                raise RuntimeError("hung socket")

    assert reap_orphaned_sandboxes(client=_Boom()) == 0


def test_one_bad_container_does_not_abort_sweep():
    removed: list = []
    bad = _FakeContainer("not-a-timestamp", removed=removed)
    good = _FakeContainer(_iso_ago(10_000), removed=removed)
    client = _FakeClient([bad, good])

    n = reap_orphaned_sandboxes(client=client)
    assert n == 1  # the good one still reaped despite the bad one's parse failure
    assert good in removed
