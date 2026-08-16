"""v80 P4: office step_activity feed — recorder callback + projection + store + config.

Contract PII: một event step_activity CHỈ được chứa đúng 6 field định danh/đếm
(`step_recorder.ACTIVITY_FIELDS`) — args/kết quả tool và nội dung LLM không có
đường code nào tới được callback. Feed là quan sát best-effort: callback nổ →
step vẫn chạy, transcript vẫn ghi.
"""

from __future__ import annotations

import json

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.office_room_store import OfficeRoomStore
from my_crew.runtime.step_recorder import (
    ACTIVITY_FIELDS,
    StepRecorder,
    open_step_recorder,
    record_event,
)
from my_crew.server.office_event_projection import VALID_KINDS, summarize_office_event


def _recorder(tmp_path, events_out):
    path = tmp_path / "t.jsonl"
    return StepRecorder(
        path, path.open("a", encoding="utf-8"),
        on_activity=events_out.append, agent="a1", task="t1", step="s1",
    )


# ---- recorder callback -------------------------------------------------------


class TestRecorderCallback:
    def test_event_contains_exactly_the_allowlist_fields(self, tmp_path):
        events: list[dict] = []
        rec = _recorder(tmp_path, events)
        rec.record({"t": "tool_call", "name": "web_search",
                    "args_head": '{"q": "bí mật khách hàng"}'})
        rec.close()
        assert len(events) == 1
        assert set(events[0]) == set(ACTIVITY_FIELDS)
        assert events[0] == {"agent": "a1", "task": "t1", "step": "s1",
                             "tool": "web_search", "count": 1, "phase": "calling-tool"}

    def test_tool_count_is_cumulative_and_prefetch_counts(self, tmp_path):
        events: list[dict] = []
        rec = _recorder(tmp_path, events)
        rec.record({"t": "prefetch", "queries": ["giá vàng"], "bytes": 9})
        rec.record({"t": "tool_call", "name": "web_search", "args_head": "{}"})
        rec.record({"t": "tool_call", "name": "scrape", "args_head": "{}"})
        rec.close()
        assert [(e["tool"], e["count"]) for e in events] == [
            ("web-prefetch", 1), ("web_search", 2), ("scrape", 3),
        ]

    def test_llm_request_maps_to_writing_and_other_events_stay_silent(self, tmp_path):
        events: list[dict] = []
        rec = _recorder(tmp_path, events)
        rec.record({"t": "meta", "agent": "a1"})
        rec.record({"t": "llm_request", "role": "content", "messages": []})
        rec.record({"t": "llm_response", "model": "m", "content": "x"})
        rec.record({"t": "tool_result", "name": "web_search", "content_head": "kq"})
        rec.record({"t": "outcome", "status": "done"})
        rec.close()
        assert [e["phase"] for e in events] == ["writing"]
        assert events[0]["tool"] == ""

    def test_raising_callback_never_breaks_recording(self, tmp_path):
        def boom(_activity):
            raise RuntimeError("feed chết")

        path = tmp_path / "t.jsonl"
        rec = StepRecorder(path, path.open("a", encoding="utf-8"), on_activity=boom)
        rec.record({"t": "tool_call", "name": "web_search", "args_head": "{}"})
        rec.close()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1  # transcript vẫn ghi đủ dù feed nổ
        assert json.loads(lines[0])["name"] == "web_search"

    def test_open_step_recorder_threads_the_callback(self, tmp_path):
        events: list[dict] = []
        settings = build_settings_from_dict({"data_dir": tmp_path})
        with open_step_recorder(settings, agent_id="a1", task_id="t1",
                                step_id="s1", attempt_id="at1",
                                on_activity=events.append):
            record_event({"t": "tool_call", "name": "web_search", "args_head": "{}"})
        assert [e["tool"] for e in events] == ["web_search"]
        assert events[0]["agent"] == "a1" and events[0]["step"] == "s1"

    def test_transcripts_off_means_no_feed_either(self, tmp_path):
        events: list[dict] = []
        settings = build_settings_from_dict(
            {"data_dir": tmp_path, "step_transcripts": False}
        )
        with open_step_recorder(settings, agent_id="a1", task_id="t1",
                                step_id="s1", attempt_id="at1",
                                on_activity=events.append):
            record_event({"t": "tool_call", "name": "web_search", "args_head": "{}"})
        assert events == []


# ---- projection + store ------------------------------------------------------


class TestProjectionAndStore:
    def test_projection_allowlists_and_drops_unknown_phase_and_extras(self):
        body = {"agent": "a1", "task": "t1", "step": "s1", "tool": "web_search",
                "count": 3, "phase": "calling-tool",
                "args_head": "PII lọt qua đây là bug"}
        projected = summarize_office_event("step_activity", body)
        assert projected == {"agent": "a1", "task": "t1", "step": "s1",
                             "tool": "web_search", "count": 3, "phase": "calling-tool"}
        assert summarize_office_event(
            "step_activity", body | {"phase": "free-text-lạ"}
        )["phase"] == ""

    def test_store_accepts_the_kind_and_persists_projected_body(self, tmp_path):
        assert "step_activity" in VALID_KINDS
        store = OfficeRoomStore(tmp_path / "office.sqlite3")
        try:
            store.append("t1", author="a1", kind="step_activity", body={
                "agent": "a1", "task": "t1", "step": "s1",
                "tool": "web_search", "count": 1, "phase": "calling-tool",
                "content_head": "không được nằm trong store",
            }, also_office=True)
            rows = store.list("t1")
        finally:
            store.close()
        assert len(rows) == 1
        assert rows[0].body["tool"] == "web_search"
        assert "content_head" not in rows[0].body


# ---- config ------------------------------------------------------------------


class TestConfig:
    def test_default_on_and_dict_off(self):
        assert build_settings_from_dict({}).step_activity_feed is True
        assert build_settings_from_dict(
            {"step_activity_feed": "false"}
        ).step_activity_feed is False

    def test_env_key_wires_through(self, monkeypatch):
        from my_crew.config.config_builders import build_settings_from_env

        monkeypatch.setenv("OPENROUTER_API_KEY", "test")
        monkeypatch.setenv("STEP_ACTIVITY_FEED", "false")
        assert build_settings_from_env().step_activity_feed is False
