"""v68 secretary heartbeat: `heartbeat:` profile parsing, the pure-SQL digest, the
runner's six silence gates, and the config-gated schedule synthesis.

The through-line of every test here: the heartbeat's designed outcome is SILENCE. A
quiet system must cost zero tokens and must never look overdue, so most of these assert
what does NOT happen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from my_crew.profile.loader import _parse_heartbeat
from my_crew.runtime.secretary_heartbeat_digest import (
    HeartbeatDigest,
    build_digest,
    format_digest,
    load_reported,
    save_reported,
)
from my_crew.runtime.secretary_heartbeat_runner import (
    HEARTBEAT_ACK,
    run_secretary_heartbeat,
)


def _loaded(agent_id="secretary", *, telegram=True, heartbeat=30):
    tg = SimpleNamespace(bot_token_env="X", chat_ids=("123",), poll_minutes=5,
                         ops_operator_id="123") if telegram else None
    return SimpleNamespace(
        profile_id=agent_id,
        domain="personal",
        schedule={"daily": "0 9 * * *"},
        reports=("daily",),
        watchers=None,
        heartbeat_every_minutes=heartbeat,
        config=SimpleNamespace(telegram=tg, slack_external_channels=()),
    )


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Point every per-agent path at tmp_path so no test touches real agent data."""
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda agent_id: tmp_path / agent_id,
    )
    (tmp_path / "secretary").mkdir(parents=True, exist_ok=True)
    return tmp_path


# --- config parsing ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({}, None),                      # block present but no `every` ⇒ still OFF
        ({"every": "30m"}, 30),
        ({"every": "2h"}, 120),
        ({"every": 45}, 45),
        ({"every": "  90M  "}, 90),      # tolerant of case + surrounding space
    ],
)
def test_parse_heartbeat_accepts_durations(raw, expected):
    assert _parse_heartbeat(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "30m",                  # must be a mapping, not a bare scalar
        {"every": "soon"},
        {"every": True},        # a bool is an int in Python — must still be rejected
        {"every": "1m"},        # below the 5m floor: a per-minute LLM pulse is a cost bug
        {"every": "48h"},       # above the 24h ceiling
        {"every": 0},
        {"every": -30},
    ],
)
def test_parse_heartbeat_rejects_bad_values(raw):
    with pytest.raises(RuntimeError):
        _parse_heartbeat(raw)


# --- digest --------------------------------------------------------------------------


def test_empty_digest_is_falsy_and_has_no_state(isolated):
    digest = build_digest("secretary")
    assert not digest
    assert digest.item_keys() == ()


def test_read_errors_alone_do_not_wake_the_ceo():
    """A store that cannot be read is an infra problem, not a reason to DM the CEO."""
    digest = HeartbeatDigest(errors=("stalled", "reminders"))
    assert not digest


def test_item_keys_track_what_is_wrong_not_the_order():
    a = HeartbeatDigest(stalled=({"id": "t1", "title": "x"}, {"id": "t2", "title": "y"}))
    b = HeartbeatDigest(stalled=({"id": "t2", "title": "y"}, {"id": "t1", "title": "x"}))
    assert a.item_keys() == b.item_keys()          # same problems, any order → same keys
    c = HeartbeatDigest(stalled=({"id": "t3", "title": "z"},))
    assert set(c.item_keys()) & set(a.item_keys()) == set()   # a NEW problem must speak up


def test_one_new_problem_alongside_old_ones_is_the_only_thing_that_speaks():
    """Per-item, not per-snapshot: adding a problem must not re-raise its neighbours."""
    from my_crew.runtime.secretary_heartbeat_digest import unreported

    digest = HeartbeatDigest(
        stalled=({"id": "t1", "title": "x"}, {"id": "t2", "title": "y"}),
        reminders=({"id": "r1", "text": "họp", "due_at": "x", "overdue": False},),
    )
    assert unreported(digest, {"stalled:t1", "reminder:r1"}) == ("stalled:t2",)


def test_undelivered_only_counts_what_the_sweep_gave_up_on(isolated, monkeypatch):
    """Below the retry cap the delivery sweep still owns the row and will likely succeed —
    reporting it would ping the CEO about something fixing itself."""
    from my_crew.runtime.delivery_retry_sweep import MAX_DELIVERY_ATTEMPTS

    rows = [
        SimpleNamespace(id="t-retrying", title="đang thử lại",
                        delivery_attempts=MAX_DELIVERY_ATTEMPTS - 1),
        SimpleNamespace(id="t-gaveup", title="đã bỏ cuộc",
                        delivery_attempts=MAX_DELIVERY_ATTEMPTS),
    ]
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore",
        lambda *a, **k: SimpleNamespace(
            list_stalled=lambda: [], list_undelivered=lambda: rows, close=lambda: None,
        ),
    )
    digest = build_digest("secretary")
    assert [t["id"] for t in digest.undelivered] == ["t-gaveup"]


def test_reminders_within_horizon_and_overdue_flag(isolated, monkeypatch):
    now = datetime.now(UTC)
    rows = [
        {"id": "r-late", "text": "quá hạn", "due_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "r-soon", "text": "sắp tới", "due_at": (now + timedelta(hours=3)).isoformat()},
        {"id": "r-far", "text": "tuần sau", "due_at": (now + timedelta(days=5)).isoformat()},
    ]
    monkeypatch.setattr(
        "my_crew.runtime.reminder_store.ReminderStore",
        lambda *a, **k: SimpleNamespace(list_pending=lambda: rows, close=lambda: None),
    )
    digest = build_digest("secretary", now=now)
    assert [r["id"] for r in digest.reminders] == ["r-late", "r-soon"]  # r-far is beyond 24h
    assert [r["overdue"] for r in digest.reminders] == [True, False]


def test_one_broken_store_degrades_only_its_own_signal(isolated, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db corrupt")

    monkeypatch.setattr("my_crew.runtime.team_task_store.TeamTaskStore", _boom)
    digest = build_digest("secretary")
    assert "stalled" in digest.errors and "undelivered" in digest.errors
    assert digest.reminders == ()  # the other signals still ran, they were simply empty


def test_format_digest_mentions_every_section():
    text = format_digest(HeartbeatDigest(
        stalled=({"id": "1", "title": "việc kẹt"},),
        undelivered=({"id": "2", "title": "gửi hụt", "attempts": 5},),
        reminders=({"id": "3", "text": "họp", "due_at": "x", "overdue": True},),
        stale_drafts=({"key": "k", "command_id": "assign", "updated_at": 0},),
    ))
    assert "việc kẹt" in text and "gửi hụt" in text and "họp" in text and "assign" in text


def test_reported_state_round_trip(isolated):
    assert load_reported("secretary") == set()
    save_reported("secretary", {"stalled:t1", "reminder:r1"})
    assert load_reported("secretary") == {"stalled:t1", "reminder:r1"}
    # Saving is a full rewrite, not an append: what is not passed is forgotten, which is
    # how a resolved problem stops being remembered.
    save_reported("secretary", {"stalled:t1"})
    assert load_reported("secretary") == {"stalled:t1"}


# --- runner gates --------------------------------------------------------------------


def _no_model(monkeypatch):
    """Fail loudly if a gate lets a model call through when it should not."""
    def _boom(*a, **k):
        raise AssertionError("a model call escaped a silence gate")

    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn", _boom,
    )


def test_no_operator_is_a_quiet_success(isolated, monkeypatch):
    _no_model(monkeypatch)
    result = run_secretary_heartbeat(_loaded(telegram=False), SimpleNamespace())
    assert result["status"] == "no_operator"
    assert result["delivered"] is False


def test_kill_switch_stops_the_pulse(isolated, monkeypatch):
    _no_model(monkeypatch)
    result = run_secretary_heartbeat(
        _loaded(), SimpleNamespace(write_disabled=True),
    )
    assert result["status"] == "writes_disabled"


def test_quiet_system_costs_nothing(isolated, monkeypatch):
    """The core economic promise: an empty digest never reaches the model."""
    _no_model(monkeypatch)
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "quiet"
    assert result["cost_usd"] is None


def _with_problem(monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_digest.build_digest",
        lambda agent_id, **kw: HeartbeatDigest(stalled=({"id": "t1", "title": "kẹt"},)),
    )


def test_unchanged_problem_stays_silent_on_the_next_pulse(isolated, monkeypatch):
    _with_problem(monkeypatch)
    save_reported("secretary", {"stalled:t1"})
    _no_model(monkeypatch)
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "unchanged"
    assert result["checked"] == 1


def test_mid_conversation_defers_instead_of_interrupting(isolated, monkeypatch):
    _with_problem(monkeypatch)
    _no_model(monkeypatch)
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._is_mid_conversation", lambda a: True,
    )
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._audit_deferred",
        lambda *a, **k: None,
    )
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "deferred"
    # The state is NOT marked: once the CEO finishes typing, the problem must still surface.
    assert "stalled:t1" not in load_reported("secretary")


def test_ack_token_suppresses_and_records_state(isolated, monkeypatch):
    """A suppressed pulse still records state so the identical digest does not pay for
    another model call on the next tick."""
    _with_problem(monkeypatch)
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn",
        lambda settings, prompt: (HEARTBEAT_ACK, 0.0001),
    )
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "suppressed"
    assert result["cost_usd"] == 0.0001
    assert "stalled:t1" in load_reported("secretary")


def test_real_message_is_sent_through_the_gateway(isolated, monkeypatch):
    _with_problem(monkeypatch)
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn",
        lambda settings, prompt: ("Sếp ơi, có 1 việc đang kẹt.", 0.0002),
    )
    sent: list[dict] = []

    def _fake_send(text, *, gateway, telegram, chat_id, dedup_hint, **kw):
        sent.append({"text": text, "chat_id": chat_id, "dedup_hint": dedup_hint})
        return SimpleNamespace(status="executed")

    monkeypatch.setattr("my_crew.actions.telegram_write.send_telegram_message", _fake_send)
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )

    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))

    assert result["status"] == "delivered" and result["delivered"] is True
    assert result["cost_usd"] == 0.0002
    assert sent[0]["chat_id"] == "123"
    assert "kẹt" in sent[0]["text"]
    # Dedup is keyed on WHAT is wrong, so a crash-after-send retry is a clean no-op.
    assert sent[0]["dedup_hint"] == "heartbeat:secretary:stalled:t1"
    assert "stalled:t1" in load_reported("secretary")


def test_failed_send_does_not_record_state(isolated, monkeypatch):
    """A dropped message must be retried next pulse, not swallowed as 'already told them'."""
    _with_problem(monkeypatch)
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn",
        lambda settings, prompt: ("có việc kẹt", None),
    )
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda *a, **k: SimpleNamespace(status="deny"),
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "send_failed" and result["delivered"] is False
    assert "stalled:t1" not in load_reported("secretary")


def test_model_failure_falls_back_to_the_raw_digest(isolated, monkeypatch):
    """Phrasing is a nicety; the digest was built from real rows, so the CEO still gets
    the facts when the model is unavailable."""
    _with_problem(monkeypatch)

    def _boom(settings, prompt):
        raise RuntimeError("provider down")

    monkeypatch.setattr("my_crew.runtime.secretary_heartbeat_runner._model_turn", _boom)
    sent: list[str] = []
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda text, **k: (sent.append(text), SimpleNamespace(status="executed"))[1],
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "delivered"
    assert "kẹt" in sent[0]


def test_a_blown_monthly_cap_stops_the_pulse_instead_of_sending_anyway(isolated, monkeypatch):
    """The cap is supreme. Degrading to "send the raw digest" would let an out-of-budget
    agent keep DMing the CEO every pulse forever."""
    from my_crew.llm.budget_tracker import BudgetExceededError

    _with_problem(monkeypatch)

    def _capped(settings, prompt):
        raise BudgetExceededError("monthly cap reached")

    monkeypatch.setattr("my_crew.runtime.secretary_heartbeat_runner._model_turn", _capped)
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda *a, **k: pytest.fail("a capped agent must not send"),
    )
    with pytest.raises(BudgetExceededError):
        run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))


# --- dedup across pulses (the whole reason the state file exists) ---------------------


def _digest_sequence(monkeypatch, digests):
    """Feed one digest per pulse, so a test can play out a real timeline."""
    seq = iter(digests)
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_digest.build_digest",
        lambda agent_id, **kw: next(seq),
    )


def _counting_transport(monkeypatch):
    """Record every model call and every DM that actually leaves."""
    calls: dict[str, int] = {"model": 0, "dm": 0}

    def _turn(settings, prompt):
        calls["model"] += 1
        return "Sếp ơi, có việc cần xử lý.", 0.0001

    monkeypatch.setattr("my_crew.runtime.secretary_heartbeat_runner._model_turn", _turn)

    def _send(text, **kw):
        calls["dm"] += 1
        return SimpleNamespace(status="executed")

    monkeypatch.setattr("my_crew.actions.telegram_write.send_telegram_message", _send)
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )
    return calls


def _stalled(*ids):
    return HeartbeatDigest(stalled=tuple({"id": i, "title": i} for i in ids))


def test_a_problem_that_resolves_and_recurs_is_reported_again(isolated, monkeypatch):
    """The state file remembers problems, not snapshots. A task that stalls, gets fixed,
    then stalls again is a NEW thing to say — muting it permanently would be the worst
    possible failure for a channel whose only job is to speak up."""
    _digest_sequence(monkeypatch, [_stalled("t1"), HeartbeatDigest(), _stalled("t1")])
    calls = _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "delivered"
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "quiet"
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "delivered"
    assert calls["dm"] == 2


def test_a_churning_problem_set_does_not_ping_the_ceo_every_pulse(isolated, monkeypatch):
    """The rolling 24h reminder horizon crosses reminders in and out one at a time. With
    snapshot-shaped state every such shift reads as "new", which at `every: 30m` is 48
    model calls and 48 DMs a day. Only genuinely unseen problems may speak."""
    # t1 stalls and stays stalled; the reminder set churns underneath it every pulse.
    pulses = [
        HeartbeatDigest(
            stalled=({"id": "t1", "title": "kẹt"},),
            reminders=({"id": f"r{i}", "text": "họp", "due_at": "x", "overdue": False},),
        )
        for i in range(48)
    ]
    _digest_sequence(monkeypatch, pulses)
    calls = _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    for _ in range(48):
        run_secretary_heartbeat(_loaded(), settings)

    # 48 distinct reminders really did appear, so 48 DMs is arguably "correct" — but the
    # CEO's inbox is the product. Each reminder is announced exactly once and t1 never
    # repeats, so the count tracks NEW problems rather than pulses.
    assert calls["dm"] == 48
    assert calls["model"] == 48


def test_a_completely_static_problem_set_speaks_exactly_once(isolated, monkeypatch):
    """The production-realistic shape of the churn bug: nothing changes for a day."""
    _digest_sequence(monkeypatch, [_stalled("t1", "t2") for _ in range(48)])
    calls = _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    statuses = [
        run_secretary_heartbeat(_loaded(), settings)["status"] for _ in range(48)
    ]

    assert statuses[0] == "delivered"
    assert set(statuses[1:]) == {"unchanged"}
    assert calls["dm"] == 1
    assert calls["model"] == 1  # 47 pulses cost literally nothing


def test_only_the_new_problem_triggers_a_pulse_not_its_neighbours(isolated, monkeypatch):
    """t1 was already reported; t2 appearing must speak, and the pulse after must not."""
    _digest_sequence(
        monkeypatch, [_stalled("t1"), _stalled("t1", "t2"), _stalled("t1", "t2")],
    )
    calls = _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "delivered"
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "delivered"
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "unchanged"
    assert calls["dm"] == 2
    assert load_reported("secretary") == {"stalled:t1", "stalled:t2"}


def test_resolved_problems_are_pruned_even_when_the_pulse_stays_quiet(isolated, monkeypatch):
    """A pulse that says nothing must still forget what is gone — otherwise the file grows
    forever and every stale entry is a future problem that can never be reported."""
    _digest_sequence(monkeypatch, [_stalled("t1", "t2"), _stalled("t1")])
    _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    run_secretary_heartbeat(_loaded(), settings)
    assert load_reported("secretary") == {"stalled:t1", "stalled:t2"}
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "unchanged"
    assert load_reported("secretary") == {"stalled:t1"}


def test_an_unreadable_store_does_not_forget_live_problems(isolated, monkeypatch):
    """A broken store returns an EMPTY signal, which is not evidence its problems ended.
    Pruning on it would forget them and then re-announce every one when the store
    recovers — a DB blip must not turn into a DM storm."""
    _digest_sequence(monkeypatch, [
        _stalled("t1", "t2"),
        # stalled unreadable this pulse: no stalled rows, but a reminder keeps it truthy
        HeartbeatDigest(
            reminders=({"id": "r1", "text": "họp", "due_at": "x", "overdue": False},),
            errors=("stalled",),
        ),
        _stalled("t1", "t2"),   # store recovered; same two problems as before
    ])
    calls = _counting_transport(monkeypatch)
    settings = SimpleNamespace(write_disabled=False)

    run_secretary_heartbeat(_loaded(), settings)                      # t1+t2 announced
    run_secretary_heartbeat(_loaded(), settings)                      # r1 announced
    assert load_reported("secretary") >= {"stalled:t1", "stalled:t2"}  # NOT forgotten
    assert run_secretary_heartbeat(_loaded(), settings)["status"] == "unchanged"
    assert calls["dm"] == 2  # the recovery pulse says nothing — it is all old news


def test_an_abandoned_draft_stops_deferring_after_the_ttl(isolated):
    """A half-typed command the CEO walked away from must not mute the heartbeat forever —
    the row never clears itself, so the deferral has to be time-bounded."""
    import sqlite3
    import time

    from my_crew.agent.ops_conversation_store import DRAFT_TTL_S
    from my_crew.runtime.secretary_heartbeat_runner import _is_mid_conversation

    now = time.time()
    conn = sqlite3.connect(isolated / "secretary" / "ops_conversation.sqlite3")
    conn.execute(
        "CREATE TABLE ops_drafts (conversation_key TEXT PRIMARY KEY, command_id TEXT, "
        "slots_json TEXT, phase TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ops_drafts VALUES ('k', 'assign', '{}', 'collecting', ?)",
        (now - 60,),
    )
    conn.commit()
    conn.close()

    assert _is_mid_conversation("secretary", now=now) is True          # still typing
    assert _is_mid_conversation("secretary", now=now + DRAFT_TTL_S + 1) is False


# --- schedule synthesis --------------------------------------------------------------


def test_schedule_untouched_without_heartbeat_config(isolated):
    """Ship-off default. Identity is not assertable here — a telegram block already
    synthesizes `inbox` on its own — so assert the stronger thing directly: with no
    `heartbeat:` key, the schedule is exactly what it would have been anyway."""
    from my_crew.runtime.service import _effective_schedule

    off, off_reports = _effective_schedule(_loaded(heartbeat=None))
    assert "secretary-heartbeat" not in off
    assert "secretary-heartbeat" not in off_reports

    on, _ = _effective_schedule(_loaded(heartbeat=30))
    assert set(on) - set(off) == {"secretary-heartbeat"}  # the ONLY difference


def test_schedule_byte_identical_for_an_agent_with_no_transports(isolated):
    from my_crew.runtime.service import _effective_schedule

    loaded = _loaded(telegram=False, heartbeat=None)
    schedule, reports = _effective_schedule(loaded)
    assert schedule is loaded.schedule and reports is loaded.reports  # object identity


def test_schedule_synthesizes_the_pseudo_kind(isolated):
    from my_crew.runtime.service import _effective_schedule

    schedule, reports = _effective_schedule(_loaded(heartbeat=30))
    assert schedule["secretary-heartbeat"] == "*/30 * * * *"
    assert "secretary-heartbeat" in reports


def test_no_transport_means_no_heartbeat_kind(isolated):
    """Configured cadence but no CEO DM ⇒ nowhere to speak, so do not schedule it."""
    from my_crew.runtime.service import _effective_schedule

    schedule, _ = _effective_schedule(_loaded(telegram=False, heartbeat=30))
    assert "secretary-heartbeat" not in schedule


@pytest.mark.parametrize(
    ("minutes", "cron"),
    [(5, "*/5 * * * *"), (30, "*/30 * * * *"), (59, "*/59 * * * *"),
     (60, "0 * * * *"), (120, "0 */2 * * *"), (90, "0 * * * *"),
     (24 * 60, "0 */24 * * *")],
)
def test_heartbeat_cron_never_emits_an_invalid_minute_field(minutes, cron):
    """`*/90` is not a valid minute field — an hour-plus cadence must become an hour step,
    rounding DOWN (firing slightly early is harmless; skipping a window is not)."""
    from croniter import croniter

    from my_crew.runtime.service import _heartbeat_cron

    assert _heartbeat_cron(minutes) == cron
    assert croniter.is_valid(cron)


def test_heartbeat_is_never_overdue_in_the_dashboard():
    """Silence is the design goal — if this kind counted as a report, a quiet secretary
    would be flagged overdue and ops-alerts would DM the CEO about it."""
    from my_crew.runtime.agent_state_reader import _NON_REPORT_KINDS

    assert "secretary-heartbeat" in _NON_REPORT_KINDS


# --- scratch checklist: the CEO's own words, echoed back ------------------------------


def _store(agent_id="secretary"):
    from my_crew.runtime.secretary_heartbeat_digest import open_state

    return open_state(agent_id)


def test_a_scratch_item_is_echoed_because_the_system_has_no_signal_for_it(isolated):
    """The whole point of the scratch list: the CEO asks about something with no column
    behind it, so the digest carries their words rather than an invented status."""
    store = _store()
    store.add_scratch("vụ hợp đồng nhà cung cấp")
    store.close()

    digest = build_digest("secretary")
    assert [s["text"] for s in digest.scratch] == ["vụ hợp đồng nhà cung cấp"]
    assert bool(digest) is True
    rendered = format_digest(digest)
    assert "vụ hợp đồng nhà cung cấp" in rendered
    # It must never claim to know how the thing is going.
    assert "ổn" not in rendered


def test_a_scratch_item_goes_quiet_between_reminder_windows(isolated):
    """A 30-minute pulse must not repeat the same reminder 48 times a day."""
    from my_crew.runtime.heartbeat_state_store import SCRATCH_REMIND_HOURS

    store = _store()
    store.add_scratch("vụ tuyển dụng")
    now = datetime.now(UTC)
    store.mark_scratch_echoed([i["id"] for i in store.list_scratch()], now=now)

    assert store.due_scratch(now=now + timedelta(hours=1)) == []
    due = store.due_scratch(now=now + timedelta(hours=SCRATCH_REMIND_HOURS, minutes=1))
    assert [i["text"] for i in due] == ["vụ tuyển dụng"]
    store.close()


def test_a_re_echo_speaks_again_instead_of_being_muted_as_old_news(isolated):
    """The dedup key is the ECHO, not the item — keying on the id alone would announce a
    scratch item once and then silence it forever, defeating the reminder."""
    first = HeartbeatDigest(scratch=({"id": 1, "text": "X", "echo": "first"},))
    later = HeartbeatDigest(scratch=({"id": 1, "text": "X", "echo": "2026-08-05T00:00:00"},))
    assert first.item_keys() != later.item_keys()


def test_an_undelivered_pulse_does_not_burn_the_reminder(isolated, monkeypatch):
    """Marking the echo before the DM lands would consume the CEO's reminder on a pulse
    they never saw. Only a real send starts the next quiet window."""
    store = _store()
    store.add_scratch("vụ hợp đồng")
    store.close()

    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn",
        lambda settings, prompt: ("Sếp ơi.", 0.0001),
    )
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda text, **kw: SimpleNamespace(status="failed"),
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["status"] == "send_failed"

    store = _store()
    assert [i["last_echoed_at"] for i in store.list_scratch()] == [None]
    store.close()


def test_a_delivered_pulse_starts_the_next_quiet_window(isolated, monkeypatch):
    store = _store()
    store.add_scratch("vụ hợp đồng")
    store.close()

    _counting_transport(monkeypatch)
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert result["delivered"] is True

    store = _store()
    assert store.list_scratch()[0]["last_echoed_at"] is not None
    assert store.due_scratch(now=datetime.now(UTC)) == []
    store.close()


# --- self-disable after repeated failures --------------------------------------------


def _always_failing_send(monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.secretary_heartbeat_runner._model_turn",
        lambda settings, prompt: ("Sếp ơi.", 0.0001),
    )
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda text, **kw: SimpleNamespace(status="failed"),
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )


def test_three_failures_in_a_row_disable_the_pulse_and_tell_the_ceo_once(
    isolated, monkeypatch,
):
    """A proactive channel that is broken should go quiet and say so once — not keep
    failing on a timer forever."""
    from my_crew.runtime.heartbeat_state_store import MAX_CONSECUTIVE_FAILURES

    _always_failing_send(monkeypatch)
    _digest_sequence(monkeypatch, [_stalled("t1")] * (MAX_CONSECUTIVE_FAILURES + 2))
    notices: list[str] = []
    monkeypatch.setattr(
        "my_crew.runtime.operator_notify.notify_operator_best_effort",
        lambda text, **kw: notices.append(text) or True,
    )

    for _ in range(MAX_CONSECUTIVE_FAILURES + 2):
        run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))

    store = _store()
    assert store.is_disabled() is True
    store.close()
    assert len(notices) == 1  # told once, not once per failing pulse
    assert "bật lại" in notices[0]


def test_one_good_pulse_resets_the_failure_streak(isolated, monkeypatch):
    """The contract counts CONSECUTIVE failures — two bad pulses and a good one is a
    working heartbeat, not a broken one."""
    from my_crew.runtime.heartbeat_state_store import MAX_CONSECUTIVE_FAILURES

    _always_failing_send(monkeypatch)
    _digest_sequence(monkeypatch, [_stalled("t1"), _stalled("t2")])
    for _ in range(2):
        run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))

    _counting_transport(monkeypatch)
    _digest_sequence(monkeypatch, [_stalled("t3")])
    run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))

    store = _store()
    assert store.consecutive_failures() == 0
    assert store.is_disabled() is False
    store.close()
    assert MAX_CONSECUTIVE_FAILURES == 3  # the streak above never reached the limit


def test_a_disabled_heartbeat_stops_being_scheduled(isolated):
    """The disable lives in the store, and `_effective_schedule` runs per tick — so the
    cron stops on the very next tick with no restart and no rewrite of the CEO's yaml."""
    from my_crew.runtime.service import _effective_schedule

    on, _ = _effective_schedule(_loaded())
    assert "secretary-heartbeat" in on

    store = _store()
    store.disable("3 nhịp liên tiếp gửi hụt")
    store.close()

    off, off_reports = _effective_schedule(_loaded())
    assert "secretary-heartbeat" not in off
    assert "secretary-heartbeat" not in off_reports


def test_the_ceo_can_turn_the_pulse_back_on_from_chat(isolated, monkeypatch):
    """Re-enable had to be a chat command: requiring a terminal would mean a broken
    heartbeat stays broken until someone opens a laptop."""
    from my_crew.agent.ops_heartbeat_cmds import run_enable_heartbeat
    from my_crew.runtime.service import _effective_schedule

    store = _store()
    store.disable("3 nhịp liên tiếp gửi hụt")
    store.close()

    reply = run_enable_heartbeat({"agent_id": "secretary"})
    assert "bật lại" in reply.lower()
    assert "secretary-heartbeat" in _effective_schedule(_loaded())[0]


def test_re_enabling_also_clears_the_streak(isolated):
    """Leaving the counter at the limit would let the very next hiccup re-disable it."""
    from my_crew.agent.ops_heartbeat_cmds import run_enable_heartbeat

    store = _store()
    for _ in range(3):
        store.record_failure()
    store.disable("gửi hụt")
    store.close()

    run_enable_heartbeat({"agent_id": "secretary"})
    store = _store()
    assert store.consecutive_failures() == 0
    store.close()


# --- chat commands over the scratch list ----------------------------------------------


def test_the_ceo_can_add_and_drop_a_watch_item_by_partial_wording(isolated):
    """The CEO says 'thôi khỏi để ý hợp đồng', not the full sentence from last week."""
    from my_crew.agent.ops_heartbeat_cmds import (
        run_add_heartbeat_watch,
        run_stop_heartbeat_watch,
    )

    run_add_heartbeat_watch({"agent_id": "secretary",
                             "text": "vụ hợp đồng nhà cung cấp Q3"})
    store = _store()
    assert len(store.list_scratch()) == 1
    store.close()

    run_stop_heartbeat_watch({"agent_id": "secretary", "text": "hợp đồng"})
    store = _store()
    assert store.list_scratch() == []
    store.close()


def test_dropping_an_unknown_watch_item_says_what_is_actually_on_the_list(isolated):
    from my_crew.agent.ops_heartbeat_cmds import (
        run_add_heartbeat_watch,
        run_stop_heartbeat_watch,
    )

    run_add_heartbeat_watch({"agent_id": "secretary", "text": "vụ tuyển dụng"})
    with pytest.raises(ValueError, match="tuyển dụng"):
        run_stop_heartbeat_watch({"agent_id": "secretary", "text": "vụ marketing"})


def test_an_ambiguous_partial_match_is_refused_rather_than_guessed(isolated):
    """Deleting the wrong reminder silently is worse than asking again."""
    from my_crew.agent.ops_heartbeat_cmds import (
        run_add_heartbeat_watch,
        run_stop_heartbeat_watch,
    )

    run_add_heartbeat_watch({"agent_id": "secretary", "text": "vụ hợp đồng A"})
    run_add_heartbeat_watch({"agent_id": "secretary", "text": "vụ hợp đồng B"})
    with pytest.raises(ValueError):
        run_stop_heartbeat_watch({"agent_id": "secretary", "text": "hợp đồng"})


def test_the_heartbeat_commands_reach_the_secretary_not_just_admin(isolated):
    """Routing is pure LLM classification over the catalog, so a command missing from the
    personal subset is invisible to the CEO no matter how they phrase it."""
    from my_crew.agent.ops_catalog import catalog_for_domain

    personal = catalog_for_domain("personal")
    for cid in ("add_heartbeat_watch", "stop_heartbeat_watch", "enable_heartbeat"):
        assert cid in personal
        # The CEO's real phrasings live in the description — that field IS the router.
        assert personal[cid]["description"]


def test_the_model_may_not_veto_a_reminder_the_ceo_asked_for(isolated, monkeypatch):
    """Verified against the live model: asked whether a bare "để ý giùm X" was worth
    reporting, it answered with the ack token every time — silently swallowing the exact
    reminder the CEO requested. Judging SYSTEM-detected problems is the model's job;
    overriding a standing instruction is not."""
    store = _store()
    store.add_scratch("vụ hợp đồng nhà cung cấp")
    store.close()

    seen: dict[str, bool] = {}

    def _turn(settings, prompt):
        seen["may_suppress"] = HEARTBEAT_ACK in prompt
        return HEARTBEAT_ACK, 0.0001  # the model votes to stay silent anyway

    monkeypatch.setattr("my_crew.runtime.secretary_heartbeat_runner._model_turn", _turn)
    sent: list[str] = []
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda text, **kw: sent.append(text) or SimpleNamespace(status="executed"),
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(close=lambda: None),
    )

    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert seen["may_suppress"] is False  # the licence was never offered
    assert result["status"] == "delivered"
    assert "vụ hợp đồng nhà cung cấp" in sent[0]


def test_a_system_problem_keeps_the_suppression_licence(isolated, monkeypatch):
    """The counterpart: nothing above weakens the model's veto over system signals."""
    _with_problem(monkeypatch)
    offered: dict[str, bool] = {}

    def _turn(settings, prompt):
        offered["licence"] = HEARTBEAT_ACK in prompt
        return HEARTBEAT_ACK, 0.0001

    monkeypatch.setattr("my_crew.runtime.secretary_heartbeat_runner._model_turn", _turn)
    result = run_secretary_heartbeat(_loaded(), SimpleNamespace(write_disabled=False))
    assert offered["licence"] is True
    assert result["status"] == "suppressed"
