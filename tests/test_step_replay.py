"""v80 P2: work-order freeze + `step-replay` sandbox re-run.

The work-order snapshots one attempt's STEP-LEVEL input (handoff, acceptance, runtime
kind, model chains) next to the transcript; replay re-runs the tier pipeline from that
frozen input inside a throwaway sandbox — read-only against the real store, network off.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact
from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.step_replay import REPLAY_NET_OFF, replay_step
from my_crew.runtime.step_work_order import (
    load_work_order,
    work_order_path,
    write_work_order,
)
from my_crew.runtime.team_task_store import TeamTaskStore


def _settings(tmp_path, **overrides):
    return build_settings_from_dict({"data_dir": tmp_path, **overrides})


def _seed_store(tmp_path, *, needs_web=False, step_type="work"):
    """Real store layout: s1 done (artifact = the handoff) + s2, the step under test."""
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(
        task_id="t1", title="Nhiệm vụ", original_request="brief gốc của CEO",
        assigned_by="ceo",
    )
    store.set_plan(
        "t1",
        [
            {"step_id": "s1", "title": "draft", "assigned_to": "a1", "deps": []},
            {
                "step_id": "s2", "title": "tổng hợp", "assigned_to": "a1",
                "deps": ["s1"], "acceptance": "đủ 3 ý", "step_type": step_type,
                "needs_web": needs_web,
            },
        ],
        plan_hash="ph-1",
    )
    write_step_artifact(tmp_path, "t1", 1, {"status": "done", "result_text": "dữ liệu bước 1"})
    step = store.get_step("t1", "s2")
    store.close()
    return step


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.cost_usd = 0.01


# ---- work-order writer -------------------------------------------------------


class TestWorkOrder:
    def test_write_freezes_step_input_with_transcript_pointer(self, tmp_path):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path)
        write_work_order(
            settings, task_id="t1", step=step, attempt_id="a1",
            effective_kind="NativeGraphRuntime", task_title="Nhiệm vụ",
            plan_hash="ph-1", original_request="brief gốc của CEO", guidance="chỉ dẫn",
        )
        path = work_order_path(tmp_path, "t1", "s2", "a1")
        assert path.is_file()
        order = json.loads(path.read_text(encoding="utf-8"))
        assert order["version"] == 1
        assert order["step_seq"] == 2
        assert order["acceptance"] == "đủ 3 ý"
        assert order["handoff"] == "dữ liệu bước 1"
        assert order["guidance"] == "chỉ dẫn"
        assert order["effective_runtime"] == "NativeGraphRuntime"
        assert order["transcript"] == "transcripts/s2-a1.jsonl"
        assert "content" in order["model_roles"]  # role → chain snapshot
        assert isinstance(order["model_roles"]["content"], list)

    def test_setting_off_writes_nothing(self, tmp_path):
        settings = _settings(tmp_path, step_transcripts=False)
        step = _seed_store(tmp_path)
        write_work_order(
            settings, task_id="t1", step=step, attempt_id="a1", effective_kind="X",
        )
        assert not work_order_path(tmp_path, "t1", "s2", "a1").exists()

    def test_unsafe_ids_never_raise_into_the_step(self, tmp_path):
        settings = _settings(tmp_path)
        step = SimpleNamespace(step_id="../evil", seq=1, title="t", assigned_to="a",
                               deps=(), acceptance="", step_type="work")
        write_work_order(
            settings, task_id="t1", step=step, attempt_id="a1", effective_kind="X",
        )  # must not raise; nothing written outside the confined dir either
        assert not (tmp_path / "artifacts").exists()

    def test_load_without_attempt_picks_newest(self, tmp_path):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path)
        for attempt in ("old1", "new1"):
            write_work_order(
                settings, task_id="t1", step=step, attempt_id=attempt,
                effective_kind="NativeGraphRuntime",
            )
        old = work_order_path(tmp_path, "t1", "s2", "old1")
        os.utime(old, (old.stat().st_atime - 100, old.stat().st_mtime - 100))
        order = load_work_order(tmp_path, "t1", "s2")
        assert order["attempt_id"] == "new1"

    def test_load_missing_is_a_clear_file_not_found(self, tmp_path):
        _seed_store(tmp_path)
        with pytest.raises(FileNotFoundError, match="work-order"):
            load_work_order(tmp_path, "t1", "s2")
        with pytest.raises(FileNotFoundError, match="attempt"):
            load_work_order(tmp_path, "t1", "s2", attempt_id="ghost1")


# ---- replay engine -----------------------------------------------------------


def _freeze(tmp_path, step, **kw):
    write_work_order(
        _settings(tmp_path), task_id="t1", step=step, attempt_id="a1",
        effective_kind="NativeGraphRuntime", task_title="Nhiệm vụ",
        plan_hash="ph-1", original_request="brief gốc của CEO", **kw,
    )


class TestReplay:
    def test_full_native_pipeline_without_touching_the_real_store(
        self, tmp_path, monkeypatch
    ):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path)
        write_step_artifact(tmp_path, "t1", 2, {"status": "done",
                                                "result_text": "kết quả gốc"})
        _freeze(tmp_path, step)

        seen_messages: list = []

        class _FakeLlm:
            def __init__(self, _settings):
                pass

            def complete(self, messages, **_kw):
                seen_messages.append(messages)
                return _FakeResult("kết quả replay")

        import my_crew.llm.client as llm_client_mod

        monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

        store_bytes_before = (tmp_path / "team_tasks.sqlite3").read_bytes()
        result = replay_step(
            None, settings, task_id="t1", step_id="s2", data_dir=tmp_path,
        )

        assert result["result_text"] == "kết quả replay"
        assert result["effective_kind"] == "NativeGraphRuntime"
        assert "gốc" in result["diff_summary"]
        # The frozen handoff rode the real perceive path into the work prompt.
        flat = json.dumps(seen_messages, ensure_ascii=False)
        assert "dữ liệu bước 1" in flat
        # Read-only contract: real store byte-identical, original artifact untouched.
        assert (tmp_path / "team_tasks.sqlite3").read_bytes() == store_bytes_before
        assert read_step_artifact(tmp_path, "t1", 2)["result_text"] == "kết quả gốc"

    def test_model_override_replaces_every_role_chain(self, tmp_path, monkeypatch):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path)
        _freeze(tmp_path, step)

        chains: list = []

        class _FakeLlm:
            def __init__(self, inner_settings):
                chains.append(inner_settings.effective_model_chain())

            def complete(self, _messages, **_kw):
                return _FakeResult("x")

        import my_crew.llm.client as llm_client_mod

        monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

        replay_step(
            None, settings, task_id="t1", step_id="s2", data_dir=tmp_path,
            model="test/model-x",
        )
        assert chains and all(c == ("test/model-x",) for c in chains)

    def test_needs_web_step_gets_the_net_off_marker_not_a_crash(
        self, tmp_path, monkeypatch
    ):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path, needs_web=True)
        _freeze(tmp_path, step)

        seen_messages: list = []

        class _FakeLlm:
            def __init__(self, _settings):
                pass

            def complete(self, messages, **_kw):
                seen_messages.append(messages)
                return _FakeResult("kết quả không có web")

        import my_crew.llm.client as llm_client_mod

        monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

        result = replay_step(
            None, settings, task_id="t1", step_id="s2", data_dir=tmp_path,
        )
        assert result["result_text"] == "kết quả không có web"
        flat = json.dumps(seen_messages, ensure_ascii=False)
        assert REPLAY_NET_OFF in flat

    def test_review_step_is_refused(self, tmp_path):
        settings = _settings(tmp_path)
        step = _seed_store(tmp_path, step_type="review")
        _freeze(tmp_path, step)
        with pytest.raises(ValueError, match="review"):
            replay_step(None, settings, task_id="t1", step_id="s2", data_dir=tmp_path)


# ---- CLI ---------------------------------------------------------------------


class TestCli:
    def _patch_registry(self, monkeypatch, settings):
        import my_crew.entrypoints.mpm_step_replay_cmd as cmd

        monkeypatch.setattr(cmd, "load_registry", lambda: [SimpleNamespace(id="a1")])
        monkeypatch.setattr(
            cmd, "_load_agent", lambda _id: SimpleNamespace(settings=settings)
        )
        return cmd

    def test_usage_and_flag_errors_exit_2(self, capsys):
        from my_crew.entrypoints.mpm_step_replay_cmd import run_step_replay

        assert run_step_replay([]) == 2
        assert run_step_replay(["a1", "t1", "s2", "--attempt"]) == 2
        assert run_step_replay(["a1", "t1", "s2", "--model"]) == 2
        assert "step-replay" in capsys.readouterr().err

    def test_unknown_agent_exits_1(self, tmp_path, monkeypatch, capsys):
        cmd = self._patch_registry(monkeypatch, _settings(tmp_path))
        assert cmd.run_step_replay(["ghost", "t1", "s2"]) == 1
        assert "unknown agent" in capsys.readouterr().err

    def test_missing_work_order_exits_1_with_clear_error(
        self, tmp_path, monkeypatch, capsys
    ):
        settings = _settings(tmp_path)
        _seed_store(tmp_path)
        cmd = self._patch_registry(monkeypatch, settings)
        # The CLI passes no data_dir → replay_step resolves team_tasks_root().
        import my_crew.runtime.team_task_paths as paths

        monkeypatch.setattr(paths, "team_tasks_root", lambda: tmp_path)
        assert cmd.run_step_replay(["a1", "t1", "s2"]) == 1
        assert "work-order" in capsys.readouterr().err

    def test_success_prints_diff_and_head(self, tmp_path, monkeypatch, capsys):
        settings = _settings(tmp_path)
        cmd = self._patch_registry(monkeypatch, settings)

        def _fake_replay(_loaded, _settings, **_kw):
            return {
                "result_text": "kết quả", "cost_usd": 0.01,
                "diff_summary": "gốc 10 ký tự, replay 7 ký tự",
                "effective_kind": "NativeGraphRuntime",
                "work_order": {"attempt_id": "a1"},
            }

        assert cmd.run_step_replay(["a1", "t1", "s2"], replay=_fake_replay) == 0
        out = capsys.readouterr().out
        assert "diff vs artifact gốc" in out
        assert "kết quả" in out
