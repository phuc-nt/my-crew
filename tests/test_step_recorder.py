"""Step transcript recorder (v80 pi-sessions): recorder contract + the three hooks.

The recorder's contract is observation that NEVER breaks the step: no-op outside a
step context, swallowed write errors, secret scrub, and a per-attempt JSONL whose
events arrive in seq order. Hooks are tested against fakes at their real seams:
`LlmClient.complete` (Hook 1), `invoke_capped`/`record_loop_result` (Hook 2), and
`prefetch_queries` (Hook 3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.step_recorder import (
    StepRecorder,
    open_step_recorder,
    record_event,
    scrub_secrets,
    step_transcript_path,
)


@pytest.fixture(autouse=True)
def _no_recorder_leak():
    """A test that dies inside `open_step_recorder` must not leak its recorder into
    the next test — the contextvar itself is reset by the context manager, this just
    asserts the invariant so a leak fails loudly here, not three tests later."""
    from my_crew.runtime.step_recorder import _current_recorder

    yield
    assert _current_recorder.get() is None


def _settings(tmp_path, **overrides):
    return build_settings_from_dict({"data_dir": tmp_path, **overrides})


def _read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _transcript(tmp_path):
    return step_transcript_path(tmp_path, "task1", "step1", "att1")


class TestRecorderCore:
    def test_events_appended_with_meta_seq_ts(self, tmp_path):
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            record_event({"t": "llm_request", "messages": []})
            record_event({"t": "outcome", "status": "done"})
        events = _read_events(_transcript(tmp_path))
        assert [e["t"] for e in events] == ["meta", "llm_request", "outcome"]
        assert [e["seq"] for e in events] == [0, 1, 2]
        assert events[0]["agent"] == "a1" and events[0]["attempt"] == "att1"
        assert all("ts" in e for e in events)

    def test_noop_outside_context(self, tmp_path):
        record_event({"t": "llm_request"})  # must not raise, must not write anywhere
        assert not (tmp_path / "artifacts").exists()

    def test_setting_off_creates_nothing(self, tmp_path):
        settings = _settings(tmp_path, step_transcripts=False)
        with open_step_recorder(settings, agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1") as recorder:
            assert recorder is None
            record_event({"t": "llm_request"})
        assert not (tmp_path / "artifacts").exists()

    def test_secret_scrub(self, tmp_path):
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            record_event({"t": "llm_request",
                          "messages": [{"content": "key sk-or-v1-abcdef1234567890 and "
                                                   "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"}]})
        raw = _transcript(tmp_path).read_text(encoding="utf-8")
        assert "sk-or-v1" not in raw and "eyJhbGciOiJIUzI1NiJ9" not in raw
        assert "[REDACTED]" in raw

    def test_scrub_function_direct(self):
        assert "[REDACTED]" in scrub_secrets("x sk-abcdefgh1234 y")
        assert scrub_secrets("plain text") == "plain text"

    def test_write_error_swallowed_one_warning(self, tmp_path, caplog):
        class BrokenFile:
            def write(self, _):
                raise OSError("disk full")

            def flush(self):
                pass

            def close(self):
                pass

        recorder = StepRecorder(tmp_path / "t.jsonl", BrokenFile())
        with caplog.at_level("WARNING"):
            recorder.record({"t": "a"})
            recorder.record({"t": "b"})
        warnings = [r for r in caplog.records if "transcript write failed" in r.message]
        assert len(warnings) == 1  # one warning, no spam, no raise

    def test_unsafe_ids_degrade_to_no_recorder(self, tmp_path):
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="../evil", attempt_id="att1") as recorder:
            assert recorder is None  # bad segment → no transcript, step continues

    def test_unserializable_payload_swallowed(self, tmp_path):
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            record_event({"t": "odd", "obj": object()})  # default=str handles it
        events = _read_events(_transcript(tmp_path))
        assert events[-1]["t"] == "odd"


class TestLlmClientHook:
    def test_complete_records_request_and_response(self, tmp_path, monkeypatch):
        from my_crew.llm import client as client_mod

        settings = _settings(tmp_path, openrouter_api_key="k", openrouter_model="m1")
        llm = client_mod.LlmClient(settings)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))])
        monkeypatch.setattr(llm, "_call_with_retry", lambda messages, model: response)
        monkeypatch.setattr(
            client_mod, "extract_usage",
            lambda _r: SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                       cost_usd=0.01),
        )
        with open_step_recorder(settings, agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            result = llm.complete([{"role": "user", "content": "hi"}], role="content")
        assert result.content == "hello"
        events = _read_events(_transcript(tmp_path))
        req = next(e for e in events if e["t"] == "llm_request")
        assert req["role"] == "content" and req["messages"][0]["content"] == "hi"
        resp = next(e for e in events if e["t"] == "llm_response")
        assert resp["model"] == "m1" and resp["content"] == "hello"
        assert resp["prompt_tokens"] == 10 and resp["cost_usd"] == 0.01


class _FakeToolMessage:
    """Duck-typed ToolMessage: has tool_call_id + content, no tool_calls."""

    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.tool_call_id = "tc1"


class _FakeAIMessage:
    def __init__(self, content="", tool_calls=()):
        self.content = content
        self.tool_calls = list(tool_calls)


class _StreamAgent:
    """Yields values-mode states: initial → +tool_call turn → +tool_result → +final."""

    def __init__(self, base_messages):
        big = "R" * 5000  # forces the 2KB head cap
        turns = [
            _FakeAIMessage(tool_calls=[{"name": "web_search",
                                        "args": {"query": "giá vàng"}}]),
            _FakeToolMessage("web_search", big),
            _FakeAIMessage(content="final answer"),
        ]
        self._states = []
        acc = list(base_messages)
        for turn in turns:
            acc = [*acc, turn]
            self._states.append({"messages": list(acc)})

    def stream(self, _inputs, config=None, stream_mode=None):
        yield from self._states


class TestLoopHook:
    def test_stream_records_loop_input_and_incremental_tool_events(self, tmp_path):
        from my_crew.runtime_backends.community_loop_core import invoke_capped

        base = [_FakeAIMessage(content="system-ish seed")]
        agent = _StreamAgent(base)
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            result = invoke_capped(agent, base, recursion_limit=25)
        assert result["messages"][-1].content == "final answer"
        events = _read_events(_transcript(tmp_path))
        kinds = [e["t"] for e in events]
        assert kinds == ["meta", "loop_input", "tool_call", "tool_result"]
        tool_call = events[2]
        assert tool_call["name"] == "web_search" and "giá vàng" in tool_call["args_head"]
        tool_result = events[3]
        assert tool_result["name"] == "web_search"
        assert len(tool_result["content_head"]) < 3000  # head-capped, not the full 5000
        assert "…[+" in tool_result["content_head"]

    def test_invoke_path_records_diff_once(self, tmp_path):
        from my_crew.runtime_backends.community_loop_core import invoke_capped

        base = [_FakeAIMessage(content="seed")]
        final_messages = [*base,
                          _FakeToolMessage("read_file", "data"),
                          _FakeAIMessage(content="done")]
        agent = SimpleNamespace(
            stream=None,
            invoke=lambda _inputs, config=None: {"messages": final_messages},
        )
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            invoke_capped(agent, base, recursion_limit=25)
        kinds = [e["t"] for e in _read_events(_transcript(tmp_path))]
        assert kinds == ["meta", "loop_input", "tool_result"]

    def test_record_loop_result_emits_aggregate_llm_response(self, tmp_path):
        from my_crew.runtime_backends.community_loop_core import record_loop_result

        final = _FakeAIMessage(content="tổng hợp cuối")
        final.usage_metadata = {"input_tokens": 100, "output_tokens": 40}
        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            text, _cost = record_loop_result({"messages": [final]}, model_name="m1")
        assert text == "tổng hợp cuối"
        events = _read_events(_transcript(tmp_path))
        resp = next(e for e in events if e["t"] == "llm_response")
        assert resp["aggregate"] is True and resp["prompt_tokens"] == 100


class TestPrefetchHook:
    def test_prefetch_records_even_on_no_capability(self, tmp_path):
        from my_crew.runtime.collect_prefetch import prefetch_queries

        with open_step_recorder(_settings(tmp_path), agent_id="a1", task_id="task1",
                                step_id="step1", attempt_id="att1"):
            bundle = prefetch_queries(None, _settings(tmp_path), ["giá vàng SJC"],
                                      keep_sentinels=True)
        assert "KHÔNG CÓ KHẢ NĂNG" in bundle
        events = _read_events(_transcript(tmp_path))
        pf = next(e for e in events if e["t"] == "prefetch")
        assert pf["queries"] == ["giá vàng SJC"] and pf["bytes"] == len(bundle)


class TestHygieneSweep:
    def test_sweep_removes_old_traces_keeps_fresh_and_artifacts(self, tmp_path, monkeypatch):
        from my_crew.runtime import team_task_paths
        from my_crew.runtime.storage_hygiene import RETENTION_DAYS, _sweep_step_transcripts

        monkeypatch.setattr(team_task_paths, "team_tasks_root", lambda: tmp_path)
        task_dir = tmp_path / "artifacts" / "team-tasks" / "task1"
        (task_dir / "transcripts").mkdir(parents=True)
        (task_dir / "work-orders").mkdir(parents=True)
        old = datetime.now(UTC) - timedelta(days=RETENTION_DAYS["step_transcripts"] + 5)
        old_ts = old.timestamp()
        files = {
            "old_transcript": task_dir / "transcripts" / "s1-a1.jsonl",
            "fresh_transcript": task_dir / "transcripts" / "s1-a2.jsonl",
            "old_work_order": task_dir / "work-orders" / "s1-a1.json",
            "artifact": task_dir / "step-1.json",
        }
        for f in files.values():
            f.write_text("{}", encoding="utf-8")
        import os

        os.utime(files["old_transcript"], (old_ts, old_ts))
        os.utime(files["old_work_order"], (old_ts, old_ts))
        os.utime(files["artifact"], (old_ts, old_ts))  # old but NOT a trace — kept

        deleted: dict[str, int] = {}
        _sweep_step_transcripts(deleted, datetime.now(UTC))
        assert deleted["step_transcripts"] == 2
        assert not files["old_transcript"].exists()
        assert not files["old_work_order"].exists()
        assert files["fresh_transcript"].exists()
        assert files["artifact"].exists()  # step artifacts are business history

    def test_sweep_absent_root_reports_zero(self, tmp_path, monkeypatch):
        from my_crew.runtime import team_task_paths
        from my_crew.runtime.storage_hygiene import _sweep_step_transcripts

        monkeypatch.setattr(team_task_paths, "team_tasks_root", lambda: tmp_path / "nope")
        deleted: dict[str, int] = {}
        _sweep_step_transcripts(deleted, datetime.now(UTC))
        assert deleted["step_transcripts"] == 0
