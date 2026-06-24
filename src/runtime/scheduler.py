"""Pure schedule due-check (v2 M1-P3, D1).

Given one agent's `schedule` (report-kind → 5-field cron string), its `reports` gate,
an injected `now`, and a `last_fire` map (per (agent, kind), seeded to "now" at daemon
startup), return the report kinds DUE this tick. Pure: no I/O, no sleep, no real
wall-clock — a test passes a fixed `now` + a seeded `last_fire` and gets an exact result.

The scheduler fires INTERNAL reports only; external (always Lớp B ⇒ pending approval)
is manual / P4. A schedule entry for a kind not in `reports` is ignored (the gate).
"""

from __future__ import annotations

from datetime import datetime

from croniter import croniter

_SCHEDULED_AUDIENCE = "internal"


def due_reports(
    schedule: dict[str, str],
    reports: tuple[str, ...],
    now: datetime,
    last_fire: dict[str, datetime],
) -> list[tuple[str, str]]:
    """Return the `(kind, "internal")` reports due at `now`.

    For each `(kind, cron)` in `schedule` where `kind` is also in `reports`, the next
    cron fire after `last_fire[kind]` is computed; if it is `<= now` the kind is due.
    `last_fire` is keyed by kind (the caller namespaces by agent). A kind with no
    `last_fire` entry is treated as never-fired (base = now would never be due, so the
    caller seeds it; an unseeded kind is conservatively skipped).
    """
    due: list[tuple[str, str]] = []
    for kind, cron in schedule.items():
        if reports and kind not in reports:
            continue  # the reports gate: only run kinds the agent is allowed to run
        base = last_fire.get(kind)
        if base is None:
            continue  # not seeded (caller seeds every scheduled pair at startup)
        if not croniter.is_valid(cron):
            continue  # a malformed cron string is skipped, not a crash
        next_fire = croniter(cron, base).get_next(datetime)
        if next_fire <= now:
            due.append((kind, _SCHEDULED_AUDIENCE))
    return due
