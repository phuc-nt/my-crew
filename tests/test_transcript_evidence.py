"""v80 P3: review đọc transcript — extractor + prompt section + wiring vào review_graph.

Contract: evidence là quan sát best-effort. Không transcript / cap 0 / file hỏng →
prompt review y hệt pre-P3 (test so bằng chuỗi, không so ước lượng); có transcript →
prompt chứa tool đã gọi + nguồn đã mở + usage, bọc qua format_internal_content.
"""

from __future__ import annotations

import json

import pytest

import my_crew.llm.client as llm_client_mod
from my_crew.agent.review_graph import ReviewStepInput, run_review_step
from my_crew.agent.team_task_artifact import write_step_artifact
from my_crew.config.config_builders import build_settings_from_dict
from my_crew.llm.team_task_prompt import build_review_messages
from my_crew.runtime.step_recorder import transcripts_dir
from my_crew.runtime.transcript_evidence import (
    extract_review_evidence,
    find_transcript_for_version,
)


def _write_transcript(tmp_path, task_id, filename, events):
    d = transcripts_dir(tmp_path, task_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return path


_EVENTS = [
    {"t": "meta", "agent": "a1", "task": "t1", "step": "s1", "attempt": "v1"},
    {"t": "prefetch", "queries": ["giá vàng SJC"], "bytes": 1234, "kept_sentinels": False},
    {"t": "tool_call", "name": "web_search", "args_head": '{"q": "giá vàng"}'},
    {"t": "tool_result", "name": "web_search", "content_head": "SJC 89.5 triệu/lượng"},
    {"t": "llm_response", "model": "m/fleet", "content": "x", "prompt_tokens": 100,
     "completion_tokens": 50, "cost_usd": 0.01},
    {"t": "llm_response", "model": "m/fleet", "content": "y", "prompt_tokens": 30,
     "completion_tokens": 20, "cost_usd": 0.005},
]


# ---- extractor ---------------------------------------------------------------


class TestExtractor:
    def test_renders_tools_sources_and_summed_usage(self, tmp_path):
        path = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        text = extract_review_evidence(path, 8000)
        assert "web_search" in text
        assert "SJC 89.5" in text
        assert "giá vàng SJC" in text  # prefetch query
        assert "2 lượt LLM" in text
        assert "130 prompt + 70 completion" in text
        assert "m/fleet" in text

    def test_tolerates_broken_lines_and_flags_no_tools(self, tmp_path):
        path = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", [_EVENTS[4]])
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"t": "tool_call", "name": "cut-off\n')  # attempt died mid-write
        text = extract_review_evidence(path, 8000)
        assert "KHÔNG có tool call" in text
        assert "1 lượt LLM" in text

    def test_cap_truncates_with_marker(self, tmp_path):
        events = [_EVENTS[3] | {"content_head": f"nguồn {i}: " + "x" * 400}
                  for i in range(30)]
        path = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS + events)
        text = extract_review_evidence(path, 1000)
        assert len(text) <= 1000
        assert "cắt theo cap" in text

    def test_prefetch_and_fetch_carry_content_not_just_byte_counts(self, tmp_path):
        """A reviewer cannot check a figure against a byte count.

        The baseline run of the v84 benchmark passed a fabricated price table at review
        round 0. Its reviewer had no handoff (the sprint step has `deps_json = []`, so
        `_read_handoff` yields "") and no transcript at all, leaving prose as the only
        thing to grade. Once a transcript exists, the prefetch/fetch events must carry
        enough of what the page actually SAID for the "every figure has a source" rule
        to be checkable — recording only `bytes: 18079` proves a page was opened, not
        what price was on it.
        """
        events = [
            {"t": "prefetch", "queries": ["giá Spotify Premium"], "bytes": 900,
             "content_head": "spotify.com/vn-vi/premium — Individual 65.000 ₫/tháng"},
            {"t": "fetch", "urls": ["https://www.spotify.com/vn-vi/premium/"],
             "bytes": 18079,
             "content_head": "Premium Individual 65.000 ₫/tháng cho 1 tài khoản"},
        ]
        text = extract_review_evidence(
            _write_transcript(tmp_path, "t1", "s1-v1.jsonl", events), 8000
        )
        # The figure a reviewer must cross-check the deliverable against.
        assert "65.000" in text
        # And the page it came from, so the source LABEL is checkable too.
        assert "spotify.com/vn-vi/premium" in text

    def test_fetch_content_absent_degrades_to_metadata_line(self, tmp_path):
        """Old transcripts (and a skipped fetch round) have no `content_head` — they must
        still render, without inventing evidence that the page was read."""
        events = [
            {"t": "fetch", "urls": ["https://x.vn/vip"], "bytes": 260},
            {"t": "fetch", "urls": [], "bytes": 0, "skipped": "no-firecrawl"},
        ]
        text = extract_review_evidence(
            _write_transcript(tmp_path, "t1", "s1-v1.jsonl", events), 8000
        )
        assert "x.vn/vip" in text
        assert "no-firecrawl" in text

    def test_missing_file_empty_file_and_cap_zero_are_none(self, tmp_path):
        assert extract_review_evidence(tmp_path / "ghost.jsonl", 8000) is None
        empty = _write_transcript(tmp_path, "t1", "s1-v1.jsonl", [])
        assert extract_review_evidence(empty, 8000) is None
        real = _write_transcript(tmp_path, "t1", "s2-v2.jsonl", _EVENTS)
        assert extract_review_evidence(real, 0) is None


class TestResolve:
    def test_finds_by_locked_version_across_step_ids(self, tmp_path):
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        # round ≥1: rework row has a DIFFERENT step_id — version is the stable key
        rework = _write_transcript(tmp_path, "t1", "s1-rework-1-v2.jsonl", _EVENTS)
        assert find_transcript_for_version(tmp_path, "t1", "v2") == rework
        assert find_transcript_for_version(tmp_path, "t1", "v1").name == "s1-v1.jsonl"

    def test_absent_or_unsafe_version_is_none(self, tmp_path):
        assert find_transcript_for_version(tmp_path, "t1", "ghost") is None
        assert find_transcript_for_version(tmp_path, "t1", "") is None
        assert find_transcript_for_version(tmp_path, "t1", "../evil") is None
        assert find_transcript_for_version(tmp_path, "../t1", "v1") is None


# ---- prompt ------------------------------------------------------------------


class TestPrompt:
    _BASE = dict(result_text="kq", acceptance="tc", persona="p", handoff="hd")

    def test_default_none_is_byte_identical_to_pre_p3(self):
        assert build_review_messages(**self._BASE) == build_review_messages(
            **self._BASE, transcript_evidence=None
        )

    def test_evidence_is_wrapped_and_instruction_present(self):
        messages = build_review_messages(
            **self._BASE, transcript_evidence="- gọi tool web_search"
        )
        user = messages[1]["content"]
        assert "BẰNG CHỨNG QUÁ TRÌNH" in user
        assert "- gọi tool web_search" in user
        assert "THIẾU bằng chứng KHÔNG phải lỗi" in user

    def test_empty_string_evidence_behaves_like_none(self):
        assert build_review_messages(**self._BASE, transcript_evidence="") == \
            build_review_messages(**self._BASE)

    def test_source_label_must_be_traceable_to_an_opened_page(self):
        """The `nguon` axis scores the source LABEL, so the label itself needs checking.

        The v84 candidate wrote "trang chính thức" next to figures taken from secondary
        pages (`zingmp3.vn/vip/upgrade` and `nhaccuatui.com` both returned 0 price
        tokens). The numbers WERE in its inputs, so this is not fabrication — but calling
        a reseller blog "official" is exactly what the axis penalizes, and no rule told
        the grader to check the label against what was actually opened.
        """
        system = build_review_messages(**self._BASE)[0]["content"]
        assert "chính thức" in system
        assert "thứ cấp" in system


# ---- review_graph wiring -----------------------------------------------------


def _wire_llm(monkeypatch):
    calls: list[list[dict]] = []

    class _FakeResult:
        content = json.dumps({"passed": True, "failures": []})
        cost_usd = 0.02
        prompt_tokens = 1
        completion_tokens = 1

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **_kw):
            calls.append(messages)
            return _FakeResult()

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    return calls


def _seed_review(tmp_path):
    write_step_artifact(tmp_path, "t1", 1, {
        "status": "done", "result_text": "SJC 89.5 triệu", "version": "v1",
    })
    return ReviewStepInput(
        task_id="t1", graded_seq=1, verdict_seq=1, review_round=0,
        locked_version="v1", acceptance="phải có nguồn",
    )


class TestReviewWiring:
    @pytest.mark.parametrize("with_transcript", [True, False])
    def test_evidence_reaches_the_review_prompt_only_when_transcript_exists(
        self, tmp_path, monkeypatch, with_transcript
    ):
        settings = build_settings_from_dict({"data_dir": tmp_path})
        review_input = _seed_review(tmp_path)
        if with_transcript:
            _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        calls = _wire_llm(monkeypatch)
        result = run_review_step(
            None, settings, data_dir=tmp_path, review_input=review_input
        )
        assert result["status"] == "done"
        user = calls[0][1]["content"]
        assert ("BẰNG CHỨNG QUÁ TRÌNH" in user) is with_transcript

    def test_cap_zero_setting_disables_evidence_entirely(self, tmp_path, monkeypatch):
        settings = build_settings_from_dict({
            "data_dir": tmp_path, "review_transcript_evidence_max_chars": 0,
        })
        review_input = _seed_review(tmp_path)
        _write_transcript(tmp_path, "t1", "s1-v1.jsonl", _EVENTS)
        calls = _wire_llm(monkeypatch)
        run_review_step(None, settings, data_dir=tmp_path, review_input=review_input)
        assert "BẰNG CHỨNG QUÁ TRÌNH" not in calls[0][1]["content"]

    def test_env_key_wires_the_cap(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REVIEW_TRANSCRIPT_EVIDENCE_MAX_CHARS", "0")
        from my_crew.config.config_builders import build_settings_from_env

        monkeypatch.setenv("OPENROUTER_API_KEY", "test")
        assert build_settings_from_env().review_transcript_evidence_max_chars == 0
