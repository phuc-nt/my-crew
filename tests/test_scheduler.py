"""Slice 3: pure schedule due-check (croniter, injected now + last_fire)."""

from __future__ import annotations

from datetime import datetime

from src.runtime.scheduler import due_reports

# A Wednesday 2026-06-24 at various clock times (no tz — croniter uses naive local).
_8AM = datetime(2026, 6, 24, 8, 0, 0)
_BEFORE_8 = datetime(2026, 6, 24, 7, 59, 0)
_YESTERDAY_9 = datetime(2026, 6, 23, 9, 0, 0)


def test_due_when_cron_fired_since_last():
    # last_fire was yesterday; the daily 08:00 cron's next fire (today 08:00) is <= now.
    due = due_reports({"daily": "0 8 * * *"}, ("daily",), _8AM, {"daily": _YESTERDAY_9})
    assert due == [("daily", "internal")]


def test_not_due_just_before_cron_time():
    # now is 07:59 — the next 08:00 fire is in the future ⇒ not due.
    due = due_reports({"daily": "0 8 * * *"}, ("daily",), _BEFORE_8, {"daily": _YESTERDAY_9})
    assert due == []


def test_no_double_fire_within_period():
    # last_fire is already today 08:00 (just fired) ⇒ next fire is tomorrow 08:00 > now.
    due = due_reports({"daily": "0 8 * * *"}, ("daily",), _8AM, {"daily": _8AM})
    assert due == []


def test_reports_gate_excludes_unlisted_kind():
    # weekly is scheduled but the agent's reports gate only allows daily ⇒ weekly excluded.
    schedule = {"daily": "0 8 * * *", "weekly": "0 8 * * 3"}  # both would fire today 08:00
    due = due_reports(schedule, ("daily",), _8AM, {"daily": _YESTERDAY_9, "weekly": _YESTERDAY_9})
    assert due == [("daily", "internal")]


def test_empty_reports_gate_allows_all_scheduled():
    # an empty reports tuple is treated as "no gate" → every scheduled+due kind fires.
    schedule = {"daily": "0 8 * * *", "okr": "0 8 * * 3"}  # Wed = weekday 3
    due = due_reports(schedule, (), _8AM, {"daily": _YESTERDAY_9, "okr": _YESTERDAY_9})
    assert set(due) == {("daily", "internal"), ("okr", "internal")}


def test_weekday_cron_not_due_on_wrong_day():
    # weekly fires Fridays (weekday 5); today is Wednesday ⇒ next fire is a future Friday.
    last = datetime(2026, 6, 19, 17, 0)  # last Friday 17:00
    due = due_reports({"weekly": "0 17 * * 5"}, ("weekly",), _8AM, {"weekly": last})
    assert due == []


def test_unseeded_kind_is_skipped():
    # a kind with no last_fire entry (not seeded) is conservatively skipped, not fired.
    due = due_reports({"daily": "0 8 * * *"}, ("daily",), _8AM, {})
    assert due == []


def test_malformed_cron_skipped_not_crash():
    due = due_reports({"daily": "not a cron"}, ("daily",), _8AM, {"daily": _YESTERDAY_9})
    assert due == []


def test_audience_always_internal():
    due = due_reports({"daily": "0 8 * * *"}, ("daily",), _8AM, {"daily": _YESTERDAY_9})
    assert all(audience == "internal" for _kind, audience in due)
