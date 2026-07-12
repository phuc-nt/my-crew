"""v8 M21 CEO-observability: missed_schedule / failing alerts + the ops-alerts push. Offline.

Load-bearing:
- missed_schedule fires only for an ENABLED agent whose scheduled kind is past the wide
  overdue threshold; a fresh run or a disabled agent stays silent.
- failing fires on 3 consecutive error/load_error run-events of one kind.
- Old states without schedule/run_events yield NO new alerts (backward-compat).
- run_ops_alerts pushes NEW-today alerts once (per-day dedup), combined into one message.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.runtime import agent_state_reader as asr

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _state(agent_id="a1", *, enabled=True, schedule=None, reports=(), run_events=()):
    return {
        "agent_id": agent_id, "name": agent_id, "enabled": enabled,
        "budget_spent_usd": 0.0, "budget_cap_usd": 0.0, "budget_ratio": 0.0,
        "pending_approvals": [], "audit_counts": {}, "last_run": None,
        "schedule": schedule or {}, "reports": reports, "run_events": list(run_events),
    }


def _ev(kind, status, ts):
    return {"kind": kind, "status": status, "ts": ts}


# --- missed_schedule ---


def test_missed_schedule_fires_when_overdue():
    st = _state(schedule={"daily": "0 8 * * *"}, reports=("daily",),
                run_events=[_ev("daily", "delivered", "2026-07-01T08:00:00+00:00")])
    alerts = asr.team_alerts([st], now=NOW)
    assert any(a["kind"] == "missed_schedule" and a["agent_id"] == "a1" for a in alerts)


def test_fresh_run_is_not_overdue():
    st = _state(schedule={"daily": "0 8 * * *"}, reports=("daily",),
                run_events=[_ev("daily", "delivered", "2026-07-04T08:00:00+00:00")])
    assert not any(a["kind"] == "missed_schedule" for a in asr.team_alerts([st], now=NOW))


def test_disabled_agent_never_alerts():
    st = _state(enabled=False, schedule={"daily": "0 8 * * *"}, reports=("daily",),
                run_events=[_ev("daily", "error", "2026-07-01T08:00:00+00:00")])
    assert asr.team_alerts([st], now=NOW) == []


def test_synthetic_pollers_never_overdue():
    # inbox/tasks fire on a fast synthetic cron and a zero-work poll is a success — they
    # must never be treated as "missed" reports.
    st = _state(schedule={"inbox": "*/2 * * * *", "tasks": "0 * * * *"},
                reports=("inbox", "tasks"), run_events=[])
    assert not any(a["kind"] == "missed_schedule" for a in asr.team_alerts([st], now=NOW))


def test_kind_not_in_reports_gate_ignored():
    st = _state(schedule={"weekly": "0 8 * * 1"}, reports=("daily",), run_events=[])
    assert not any(a["kind"] == "missed_schedule" for a in asr.team_alerts([st], now=NOW))


# --- failing ---


def test_failing_fires_on_three_consecutive_errors():
    st = _state(schedule={"daily": "0 8 * * *"}, reports=("daily",), run_events=[
        _ev("daily", "error", "2026-07-04T08:00:00+00:00"),
        _ev("daily", "load_error", "2026-07-03T08:00:00+00:00"),
        _ev("daily", "error", "2026-07-02T08:00:00+00:00"),
    ])
    assert any(a["kind"] == "failing" and "daily" in a["message"]
               for a in asr.team_alerts([st], now=NOW))


def test_failing_streak_broken_by_a_success():
    st = _state(schedule={"daily": "0 8 * * *"}, reports=("daily",), run_events=[
        _ev("daily", "error", "2026-07-04T08:00:00+00:00"),
        _ev("daily", "delivered", "2026-07-03T08:00:00+00:00"),  # breaks the leading streak
        _ev("daily", "error", "2026-07-02T08:00:00+00:00"),
        _ev("daily", "error", "2026-07-01T08:00:00+00:00"),
    ])
    assert not any(a["kind"] == "failing" for a in asr.team_alerts([st], now=NOW))


# --- backward-compat: old states without the new fields ---


def test_old_state_without_new_fields_no_new_alerts():
    old = {"agent_id": "z", "name": "z", "enabled": True, "budget_spent_usd": 0.0,
           "budget_cap_usd": 0.0, "budget_ratio": 0.0, "pending_approvals": [],
           "audit_counts": {}, "last_run": None}
    assert asr.team_alerts([old], now=NOW) == []


# --- per-kind event window: a chatty poller must NOT evict report events (review H1) ---


def test_per_kind_window_survives_poll_flood(tmp_path, monkeypatch):
    """A polling agent floods runs.jsonl with inbox events between reports. The per-kind
    window must still surface the report kind's recent events so failing/missed still fire."""
    import json as _json

    from src.runtime import agent_state_reader as _asr

    data_dir = tmp_path / "agents" / "chatty"
    data_dir.mkdir(parents=True)
    lines = []
    # 3 old daily errors FIRST (oldest), then 300 inbox successes flooding after them.
    for i in range(3):
        lines.append(_json.dumps({"ts": f"2026-07-0{i+1}T08:00:00+00:00", "kind": "daily",
                                  "status": "error"}))
    for i in range(300):
        lines.append(_json.dumps({"ts": f"2026-07-04T10:{i % 60:02d}:00+00:00",
                                  "kind": "inbox", "status": "no_mentions"}))
    (data_dir / "runs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.agent_state_reader.agent_data_dir",
                        lambda aid: tmp_path / "agents" / aid)

    events = _asr._recent_events_per_kind("chatty")
    daily = [e for e in events if e["kind"] == "daily"]
    assert len(daily) == 3, "the 3 daily events must survive the 300-inbox flood"
    # and the failing alert fires off them
    st = _state(schedule={"daily": "0 8 * * *"}, reports=("daily",), run_events=events)
    assert any(a["kind"] == "failing" for a in asr.team_alerts([st], now=NOW))


# --- run_ops_alerts push ---


class _Tg:
    ops_operator_id = "5248565986"
    chat_ids = ("5248565986",)


class _Cfg:
    telegram = _Tg()
    slack_external_channels = frozenset()


class _Loaded:
    profile_id = "admin"
    domain = "admin"
    config = _Cfg()


class _Settings:
    write_disabled = False
    trust_mode = "guarded"  # pre-v30 behavior; the real gateway reads this in _execute

    def __init__(self, tmp):
        self.data_dir = str(tmp)


def _run(monkeypatch, tmp_path, alerts, sent):
    monkeypatch.setattr("src.runtime.agent_state_reader.team_alerts", lambda **k: alerts)

    def _fake_send(text, **kwargs):
        sent.append((text, kwargs["chat_id"]))

        class R:
            status = "executed"
        return R()

    monkeypatch.setattr("src.actions.telegram_write.send_telegram_message", _fake_send)

    class _FakeGateway:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    monkeypatch.setattr("src.actions.action_gateway.ActionGateway", _FakeGateway)
    from src.runtime.ops_alert_runner import run_ops_alerts

    return run_ops_alerts(_Loaded(), _Settings(tmp_path), now=NOW)


def test_push_sends_combined_message_once(monkeypatch, tmp_path):
    alerts = [
        {"kind": "missed_schedule", "agent_id": "hr", "message": "m", "severity": "high"},
        {"kind": "failing", "agent_id": "pm", "message": "f", "severity": "high"},
    ]
    sent: list = []
    r = _run(monkeypatch, tmp_path, alerts, sent)
    assert r["delivered"] is True
    assert len(sent) == 1  # ONE combined message, not two
    body, chat = sent[0]
    assert chat == "5248565986" and "hr" in body and "pm" in body

    # second run same day → dedup → no new send
    sent2: list = []
    r2 = _run(monkeypatch, tmp_path, alerts, sent2)
    assert r2["status"] == "no_new_alerts" and sent2 == []


def test_push_ignores_non_push_kinds(monkeypatch, tmp_path):
    # budget/approval/deny stay dashboard-only; only missed_schedule/failing are pushed.
    alerts = [{"kind": "budget", "agent_id": "hr", "message": "m", "severity": "warn"}]
    sent: list = []
    r = _run(monkeypatch, tmp_path, alerts, sent)
    assert sent == [] and r["status"] == "no_new_alerts"


def test_push_no_operator_is_noop(monkeypatch, tmp_path):
    class _NoTg:
        telegram = None
        slack_external_channels = frozenset()

    class _L:
        profile_id = "x"
        domain = "admin"
        config = _NoTg()

    from src.runtime.ops_alert_runner import run_ops_alerts
    r = run_ops_alerts(_L(), _Settings(tmp_path), now=NOW)
    assert r["status"] == "no_operator" and r["delivered"] is False


def test_writes_disabled_pushes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr("src.runtime.agent_state_reader.team_alerts",
                        lambda **k: [{"kind": "failing", "agent_id": "hr",
                                      "message": "f", "severity": "high"}])
    s = _Settings(tmp_path)
    s.write_disabled = True
    from src.runtime.ops_alert_runner import run_ops_alerts
    r = run_ops_alerts(_Loaded(), s, now=NOW)
    assert r["status"] == "writes_disabled" and r["delivered"] is False
