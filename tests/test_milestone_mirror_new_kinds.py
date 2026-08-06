"""Milestone kinds raised while a task is still in flight (`stuck`, `gave_up`,
`step_failed`) and their dedup identity.

The task-level dedup key `(task_id, milestone, date)` is correct for once-per-task
events like `received`/`done`, but a task whose three different steps each get stuck
would collapse into one Telegram ping and the CEO would never learn about the other two.
Per-step milestones therefore carry `step_id` in their key; task-level ones must NOT, or
a re-queued task would ping twice for the same completion.
"""

from __future__ import annotations

from tests.test_milestone_mirror import NOW, _patch_send, _room, _run  # noqa: F401


def test_two_stuck_steps_same_task_same_day_both_reach_telegram(monkeypatch, tmp_path):
    room = _room(tmp_path)
    for step in ("step-1", "step-2"):
        room.append(
            "task-a", author="coordinator", kind="milestone",
            body={"task_id": "task-a", "step_id": step, "task_title": "Demo",
                  "milestone": "stuck", "message": f"kẹt ở {step}"},
            also_office=True,
        )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert r["delivered"] is True
    body, _chat = sent[0]
    assert "kẹt ở step-1" in body and "kẹt ở step-2" in body


def test_same_step_stuck_twice_same_day_pings_once(monkeypatch, tmp_path):
    """Per-step keying widens the dedup, it must not disable it — the same step
    reported stuck again on the same day is still the same news."""
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "task_title": "Demo",
              "milestone": "stuck", "message": "kẹt"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True

    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "task_title": "Demo",
              "milestone": "stuck", "message": "vẫn kẹt"},
        also_office=True,
    )
    room.close()
    r2 = _run(monkeypatch, tmp_path)
    assert r2["status"] == "no_new_milestones"
    assert len(sent) == 1


def test_task_level_milestone_keeps_task_only_key(monkeypatch, tmp_path):
    """`done` carries no step_id; two `done` rows for one task in a day stay one ping."""
    room = _room(tmp_path)
    for msg in ("xong", "xong lần nữa"):
        room.append(
            "task-a", author="coordinator", kind="milestone",
            body={"task_id": "task-a", "task_title": "Demo", "milestone": "done",
                  "message": msg},
            also_office=True,
        )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert r["delivered"] is True
    body, _chat = sent[0]
    assert body.count("Demo") == 1


def test_gave_up_renders_its_own_label(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "task_title": "Demo", "milestone": "gave_up",
              "message": "thiếu công cụ tra cứu"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True
    body, _chat = sent[0]
    assert "Không làm được" in body and "thiếu công cụ tra cứu" in body


def test_unknown_milestone_kind_falls_back_without_raising(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "task_title": "Demo", "milestone": "some_future_kind",
              "message": "gì đó"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True
    body, _chat = sent[0]
    assert "Cập nhật" in body


def test_a_second_intervention_on_the_same_step_still_reaches_the_ceo(monkeypatch, tmp_path):
    """Review H1: the coordinator may rule on one stuck step more than once (retry with
    guidance, then reassign). Keying on (task, kind, step) alone told the CEO about the
    first ruling and silently swallowed the second — `attempt` separates them."""
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "attempt": 1, "task_title": "Demo",
              "milestone": "stuck", "message": "giao lại kèm chỉ dẫn"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True

    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "attempt": 2, "task_title": "Demo",
              "milestone": "stuck", "message": "chuyển cho người khác"},
        also_office=True,
    )
    room.close()
    assert _run(monkeypatch, tmp_path)["delivered"] is True
    assert len(sent) == 2
    assert "chuyển cho người khác" in sent[1][0]


def test_the_same_intervention_reported_twice_still_pings_once(monkeypatch, tmp_path):
    """Widening the key must not disable dedup: the SAME ruling seen twice is one piece
    of news, so an identical `attempt` still collapses."""
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "attempt": 1, "task_title": "Demo",
              "milestone": "stuck", "message": "kẹt"},
        also_office=True,
    )
    room.close()
    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True

    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "step_id": "step-1", "attempt": 1, "task_title": "Demo",
              "milestone": "stuck", "message": "kẹt"},
        also_office=True,
    )
    room.close()
    assert _run(monkeypatch, tmp_path)["status"] == "no_new_milestones"
    assert len(sent) == 1


def test_two_steps_timing_out_the_same_day_both_reach_telegram(monkeypatch, tmp_path):
    """Review H2: `step_timeout` is per-step like `stuck`/`step_failed`, but was keyed
    per-task — the second step's timeout was deduped into silence."""
    room = _room(tmp_path)
    for step in ("step-2", "step-4"):
        room.append(
            "task-a", author="coordinator", kind="milestone",
            body={"task_id": "task-a", "step_id": step, "task_title": "Demo",
                  "milestone": "step_timeout", "message": f"quá hạn ở {step}"},
            also_office=True,
        )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    assert _run(monkeypatch, tmp_path)["delivered"] is True
    body, _chat = sent[0]
    assert "quá hạn ở step-2" in body and "quá hạn ở step-4" in body
    assert "Một bước quá hạn" in body
