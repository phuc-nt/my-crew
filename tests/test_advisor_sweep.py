"""Advisor ride-along sweep — silence by default, one note per step, never fatal.

Load-bearing:
- both flags off ⇒ zero LLM calls (a fleet that never opted in pays nothing);
- a silent verdict advances the cursor but writes NOTHING anywhere;
- `nit` lands in the office room, `concern` lands in the step's guidance;
- the same point twice is said once (dedupe), and after speaking the advisor is
  quiet for `COOLDOWN_SWEEPS` sweeps;
- malformed / oversized model output is quarantined, never forwarded;
- an advisor call that raises leaves the tick (and the rest of the sweep) intact.
"""

from __future__ import annotations

import json

import pytest

from my_crew.runtime import advisor_sweep as adv
from my_crew.runtime.team_task_store import TeamTaskStore


class _Settings:
    def __init__(self, *, advisor_enabled=True, step_transcripts=True):
        self.advisor_enabled = advisor_enabled
        self.step_transcripts = step_transcripts


class _Result:
    def __init__(self, content):
        self.content = content


class _FakeLlm:
    """Returns a queued reply per call; records every call it received."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def complete(self, messages, *, role=None):
        self.calls.append({"messages": messages, "role": role})
        reply = self._replies.pop(0) if self._replies else '{"severity": "silent"}'
        if isinstance(reply, Exception):
            raise reply
        return _Result(reply)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    s = TeamTaskStore(team_tasks_db_path())
    yield s
    s.close()


@pytest.fixture()
def room(monkeypatch):
    """Capture office appends instead of touching the real room store."""
    events = []
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda room_id, *, author, kind, body, also_office=False: events.append(
            {"room": room_id, "author": author, "kind": kind, "body": body}
        ),
    )
    monkeypatch.setattr("my_crew.runtime.office_room_append.room_for_task", lambda t: t)
    return events


def _running_step(store, tmp_path, *, task_id="t1", step_id="s1", body="x"):
    """A running step with a transcript on disk; returns its attempt_id."""
    store.create_task(task_id=task_id, title="Việc thử", pic_id="")
    store.set_plan(task_id, [{"step_id": step_id, "title": "Viết báo cáo",
                              "assigned_to": "content", "deps": []}], "h")
    attempt_id = store.reserve_step(task_id, step_id)
    from my_crew.runtime.step_recorder import step_transcript_path

    path = step_transcript_path(tmp_path, task_id, step_id, attempt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return attempt_id


def _delta(marker="a"):
    """Transcript text comfortably over MIN_DELTA_CHARS."""
    return json.dumps({"t": "tool_call", "tool": "web.search", "note": marker * 500}) + "\n"


def test_disabled_advisor_never_calls_the_model(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "concern", "note": "đi sai hướng"}')

    assert adv.run_advisor_sweep(store, _Settings(advisor_enabled=False),
                                 llm=llm, data_dir=tmp_path) == 0
    assert llm.calls == []
    assert room == []


def test_transcripts_off_is_a_no_op(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "nit", "note": "x"}')

    assert adv.run_advisor_sweep(store, _Settings(step_transcripts=False),
                                 llm=llm, data_dir=tmp_path) == 0
    assert llm.calls == []


def test_silence_advances_the_cursor_and_writes_nothing(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "silent"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert len(llm.calls) == 1
    assert room == []
    assert store.get_step("t1", "s1").guidance == ""
    # cursor moved, so an unchanged transcript is not re-read next sweep
    state = json.loads((tmp_path / adv.SIDECAR_NAME).read_text())
    assert state["t1/s1"]["offset"] > 0

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert len(llm.calls) == 1  # nothing new to read ⇒ no second call


def test_nit_goes_to_the_room_not_the_agent(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "nit", "note": "nguồn hơi cũ"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    assert len(room) == 1
    assert room[0]["kind"] == "advisor"
    assert room[0]["body"]["severity"] == "nit"
    assert room[0]["body"]["message"] == "nguồn hơi cũ"
    assert store.get_step("t1", "s1").guidance == ""  # a nit never steers the agent


def test_concern_reaches_the_next_attempt_as_guidance(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "concern", "note": "đang trả lời sai câu hỏi"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    assert "đang trả lời sai câu hỏi" in store.get_step("t1", "s1").guidance
    assert room == []  # the concern channel is the store, not the feed


def test_the_same_point_is_only_made_once(store, tmp_path, room):
    attempt = _running_step(store, tmp_path, body=_delta())
    note = '{"severity": "nit", "note": "Nguồn hơi cũ."}'
    llm = _FakeLlm(note, note)

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    _grow(tmp_path, "t1", "s1", attempt, _delta("b"))
    # cooldown must not be what hides the second note — clear it, keep the dedupe
    _clear_cooldown(tmp_path, "t1/s1")

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert len(room) == 1


def test_after_speaking_the_advisor_stays_quiet_for_the_cooldown(store, tmp_path, room):
    attempt = _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "nit", "note": "một"}',
                   '{"severity": "nit", "note": "hai"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    for _ in range(adv.COOLDOWN_SWEEPS):
        _grow(tmp_path, "t1", "s1", attempt, _delta("c"))
        assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert len(llm.calls) == 1  # cooldown skips before spending a call

    _grow(tmp_path, "t1", "s1", attempt, _delta("d"))
    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    assert len(room) == 2


@pytest.mark.parametrize("raw", [
    "không phải JSON gì cả",
    '{"severity": "concern"}',            # no note
    '{"severity": "shout", "note": "x"}',  # severity outside the enum
    '{"severity": "concern", "note": ""}',
    "",
])
def test_malformed_output_is_quarantined(store, tmp_path, room, raw):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm(raw)

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert room == []
    assert store.get_step("t1", "s1").guidance == ""


def test_an_essay_instead_of_a_note_is_quarantined(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm(json.dumps({"severity": "concern",
                               "note": "x" * (adv.MAX_NOTE_CHARS + 1)}))

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert store.get_step("t1", "s1").guidance == ""


def test_a_fenced_json_reply_still_parses(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('```json\n{"severity": "nit", "note": "ổn thôi nhưng chậm"}\n```')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    assert room[0]["body"]["message"] == "ổn thôi nhưng chậm"


def test_a_raising_advisor_does_not_break_the_sweep(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm(RuntimeError("provider down"))

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert room == []


def test_a_short_delta_is_not_worth_a_call(store, tmp_path, room):
    _running_step(store, tmp_path, body='{"t":"heartbeat"}\n')
    llm = _FakeLlm('{"severity": "nit", "note": "x"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert llm.calls == []


def test_only_running_steps_are_advised(store, tmp_path, room):
    attempt = _running_step(store, tmp_path, body=_delta())
    store.mark_done("t1", "s1")
    llm = _FakeLlm('{"severity": "nit", "note": "x"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 0
    assert llm.calls == []
    assert attempt  # the transcript is still on disk; status is what gates the read


def test_the_advisor_role_is_what_pays_for_the_call(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "silent"}')

    adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path)
    assert llm.calls[0]["role"] == "advisor"


def test_a_finished_step_leaves_no_cursor_behind(store, tmp_path, room):
    _running_step(store, tmp_path, body=_delta())
    llm = _FakeLlm('{"severity": "silent"}')
    adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path)
    assert "t1/s1" in json.loads((tmp_path / adv.SIDECAR_NAME).read_text())

    store.mark_done("t1", "s1")
    _running_step(store, tmp_path, task_id="t2", step_id="s1", body=_delta())
    adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path)

    state = json.loads((tmp_path / adv.SIDECAR_NAME).read_text())
    assert "t1/s1" not in state
    assert "t2/s1" in state


def test_a_transcript_in_the_assignees_jail_is_found(store, tmp_path, room):
    """A spawned worker records into ITS OWN data dir (`.data/agents/<id>/`), not the
    shared team-tasks root. The sweep must look there or it advises on nothing at all
    for every step that ran out-of-process — which is most of them."""
    from my_crew.runtime.step_recorder import step_transcript_path

    store.create_task(task_id="t9", title="Việc thật", pic_id="")
    store.set_plan("t9", [{"step_id": "s1", "title": "Tra cứu",
                           "assigned_to": "researcher", "deps": []}], "h")
    attempt_id = store.reserve_step("t9", "s1")
    jailed = step_transcript_path(tmp_path / "agents" / "researcher", "t9", "s1", attempt_id)
    jailed.parent.mkdir(parents=True, exist_ok=True)
    jailed.write_text(_delta(), encoding="utf-8")
    llm = _FakeLlm('{"severity": "concern", "note": "lặp lại tra cứu hỏng"}')

    assert adv.run_advisor_sweep(store, _Settings(), llm=llm, data_dir=tmp_path) == 1
    assert "lặp lại tra cứu hỏng" in store.get_step("t9", "s1").guidance


def _grow(tmp_path, task_id, step_id, attempt_id, text):
    from my_crew.runtime.step_recorder import step_transcript_path

    path = step_transcript_path(tmp_path, task_id, step_id, attempt_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _clear_cooldown(tmp_path, key):
    path = tmp_path / adv.SIDECAR_NAME
    state = json.loads(path.read_text())
    state[key]["cooldown"] = 0
    path.write_text(json.dumps(state))
