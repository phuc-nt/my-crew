"""v80 P5: reflection + bench đọc transcript — behavior summary, usage per-step, config.

Contract: cả hai read-only với transcript, vắng transcript → hành vi cũ y hệt (so
bằng chuỗi/giá trị, không ước lượng). Behavior summary cho reflection CHỈ chứa tên
tool + số đếm — không args, không content head, không prefetch query (threat model
trong `task_reflection._task_digest`).
"""

from __future__ import annotations

import json
import sqlite3

from my_crew.agent.task_reflection import _behavior_summary, _build_prompt
from my_crew.bench.task_metrics import load_task_metric
from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.step_recorder import transcripts_dir
from my_crew.runtime.transcript_evidence import (
    extract_task_behavior_summary,
    summarize_transcript_usage,
)


def _write_transcript(data_dir, task_id, filename, events):
    d = transcripts_dir(data_dir, task_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


_EVENTS = [
    {"t": "meta", "agent": "a1", "task": "t1", "step": "s1", "attempt": "v1"},
    {"t": "prefetch", "queries": ["giá vàng SJC"], "bytes": 1234},
    {"t": "tool_call", "name": "web_search", "args_head": '{"q": "bí mật"}'},
    {"t": "tool_call", "name": "web_search", "args_head": "{}"},
    {"t": "tool_result", "name": "web_search", "content_head": "SJC 89.5 triệu"},
    {"t": "llm_response", "model": "m/fleet", "content": "x", "prompt_tokens": 100,
     "completion_tokens": 50, "cost_usd": 0.01},
    {"t": "llm_response", "model": "m/fleet", "content": "y", "prompt_tokens": 30,
     "completion_tokens": 20, "cost_usd": 0.005},
]


# ---- usage summary (bench nguồn) ---------------------------------------------


class TestUsageSummary:
    def test_sums_llm_response_events(self, tmp_path):
        path = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        usage = summarize_transcript_usage(path)
        assert usage == {"llm_calls": 2, "prompt_tokens": 130,
                         "completion_tokens": 70, "cost_usd": 0.015,
                         "models": ["m/fleet"]}

    def test_missing_or_empty_file_is_none(self, tmp_path):
        assert summarize_transcript_usage(tmp_path / "ghost.jsonl") is None
        empty = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", [])
        assert summarize_transcript_usage(empty) is None


# ---- behavior summary (reflection nguồn) -------------------------------------


class TestBehaviorSummary:
    def test_counts_only_never_content(self, tmp_path):
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        _write_transcript(tmp_path, "t1", "s2-v2.jsonl", [
            {"t": "tool_call", "name": "scrape", "args_head": "{}"},
            {"t": "llm_response", "model": "m", "prompt_tokens": 1, "completion_tokens": 1},
        ])
        text = extract_task_behavior_summary(tmp_path, "t1", 4000)
        assert "web_search ×2" in text
        assert "scrape ×1" in text
        assert "prefetch web ×1" in text
        assert "3 lượt LLM" in text and "131 prompt + 71 completion" in text
        # threat model: nội dung attacker-influenceable không được lọt vào
        assert "bí mật" not in text and "SJC" not in text and "giá vàng" not in text

    def test_no_transcripts_or_cap_zero_is_none(self, tmp_path):
        assert extract_task_behavior_summary(tmp_path, "t1", 4000) is None
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        assert extract_task_behavior_summary(tmp_path, "t1", 0) is None

    def test_cap_truncates(self, tmp_path):
        events = [{"t": "tool_call", "name": f"tool-{i}", "args_head": "{}"}
                  for i in range(200)]
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", events)
        text = extract_task_behavior_summary(tmp_path, "t1", 300)
        assert len(text) <= 300
        assert "cắt theo cap" in text


# ---- reflection prompt wiring ------------------------------------------------


class TestReflectionPrompt:
    def test_empty_behavior_is_byte_identical_to_pre_p5(self):
        assert _build_prompt("digest", ["bài học cũ"]) == _build_prompt(
            "digest", ["bài học cũ"], behavior=""
        )

    def test_behavior_section_present_when_given(self):
        prompt = _build_prompt("digest", [], behavior="- web_search ×3")
        assert "QUÁ TRÌNH LÀM" in prompt
        assert "- web_search ×3" in prompt
        assert prompt.index("QUY TẮC") < prompt.index("QUÁ TRÌNH LÀM")

    def test_behavior_summary_helper_reads_settings_and_degrades(self, tmp_path):
        class _Task:
            id = "t1"

        settings = build_settings_from_dict({"data_dir": tmp_path})
        assert _behavior_summary(settings, _Task()) == ""  # chưa có transcript
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        assert "web_search ×2" in _behavior_summary(settings, _Task())
        off = build_settings_from_dict(
            {"data_dir": tmp_path, "reflection_transcript_evidence_max_chars": 0}
        )
        assert _behavior_summary(off, _Task()) == ""

    def test_env_key_wires_the_cap(self, monkeypatch):
        from my_crew.config.config_builders import build_settings_from_env

        monkeypatch.setenv("OPENROUTER_API_KEY", "test")
        monkeypatch.setenv("REFLECTION_TRANSCRIPT_EVIDENCE_MAX_CHARS", "0")
        assert build_settings_from_env().reflection_transcript_evidence_max_chars == 0


# ---- bench per-step usage ----------------------------------------------------


def _seed_bench_db(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE team_tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
        "created_at TEXT, cost_usd_total REAL)"
    )
    conn.execute(
        "CREATE TABLE team_steps (task_id TEXT, step_id TEXT, seq INTEGER, "
        "step_type TEXT, status TEXT, cost_usd REAL, spawned_at TEXT, last_seen TEXT)"
    )
    conn.execute(
        "INSERT INTO team_tasks VALUES ('t1', 'Đo thử', 'done', "
        "'2026-08-16T00:00:00+00:00', 0.02)"
    )
    conn.execute(
        "INSERT INTO team_steps VALUES ('t1', 's1', 1, 'work', 'done', 0.015, "
        "'2026-08-16T00:00:10+00:00', '2026-08-16T00:01:00+00:00')"
    )
    conn.execute(
        "INSERT INTO team_steps VALUES ('t1', 's2', 2, 'review', 'done', 0.005, "
        "'2026-08-16T00:01:00+00:00', '2026-08-16T00:01:30+00:00')"
    )
    conn.commit()
    conn.close()


class TestBenchTranscriptUsage:
    def test_data_dir_attaches_per_step_usage_summed_across_attempts(self, tmp_path):
        db = tmp_path / "team_tasks.sqlite3"
        _seed_bench_db(db)
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        # attempt retry của cùng step — usage phải cộng dồn như cost_usd trong store
        _write_transcript(tmp_path, "t1", "s1-v2.jsonl", [
            {"t": "llm_response", "model": "m", "prompt_tokens": 10,
             "completion_tokens": 5, "cost_usd": 0.001},
        ])
        metric = load_task_metric(db, "t1", data_dir=tmp_path)
        s1 = next(s for s in metric.steps if s.step_id == "s1")
        s2 = next(s for s in metric.steps if s.step_id == "s2")
        assert (s1.llm_calls, s1.prompt_tokens, s1.completion_tokens) == (3, 140, 75)
        assert (s2.llm_calls, s2.prompt_tokens, s2.completion_tokens) == (0, 0, 0)

    def test_without_data_dir_behaves_exactly_as_before(self, tmp_path):
        db = tmp_path / "team_tasks.sqlite3"
        _seed_bench_db(db)
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        metric = load_task_metric(db, "t1")
        assert all(s.llm_calls == 0 for s in metric.steps)
        assert metric.cost_usd == 0.02  # ledger vẫn là nguồn sự thật kế toán

    def test_tool_error_counts_attach_per_step_and_aggregate(self, tmp_path):
        db = tmp_path / "team_tasks.sqlite3"
        _seed_bench_db(db)
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS + [
            {"t": "tool_call", "name": "bash", "args_head": "{}"},
            {"t": "tool_result", "name": "bash",
             "content_head": "Tool 'bash' không tồn tại. Công cụ có: web_search."},
        ])
        metric = load_task_metric(db, "t1", data_dir=tmp_path)
        s1 = next(s for s in metric.steps if s.step_id == "s1")
        # _EVENTS has 2 tool_call + 1 clean tool_result; the appended pair is the error
        assert (s1.tool_calls, s1.tool_errors) == (3, 1)
        assert s1.tool_error_kinds == {"invented_tool": 1}
        assert (metric.tool_calls, metric.tool_errors) == (3, 1)
        assert metric.tool_error_kinds == {"invented_tool": 1}
        assert metric.llm_calls == 2

    def test_transcripts_in_an_agent_jail_are_found(self, tmp_path):
        """A spawned worker records into `.data/agents/<id>/` — its steps must not
        read as zero rounds / zero tool calls in the bench table."""
        db = tmp_path / "team_tasks.sqlite3"
        _seed_bench_db(db)
        _write_transcript(tmp_path / "agents" / "researcher", "t1", "s1-v1.jsonl", _EVENTS)
        metric = load_task_metric(db, "t1", data_dir=tmp_path)
        s1 = next(s for s in metric.steps if s.step_id == "s1")
        assert s1.llm_calls == 2
        assert s1.tool_calls == 2
