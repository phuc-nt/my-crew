"""M3-P12 S1 (B4): opt-in LangSmith tracing config — default-OFF byte-identical.

Offline, NO network. The tracer is CONSTRUCTED (not flushed) when enabled; construction
is offline. Default OFF ⇒ the invoke config has no `callbacks` key (byte-identical to
pre-P12). A profile flag alone (env missing) never enables tracing.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.run_config import (
    build_callbacks,
    invoke_config,
    invoke_config_env,
    tracing_enabled,
)

_TRACE_ENV = ("LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY")


@pytest.fixture
def clean_trace_env(monkeypatch):
    for k in _TRACE_ENV:
        monkeypatch.delenv(k, raising=False)


def test_off_default_is_byte_identical(clean_trace_env):
    s = build_settings_from_dict({})
    assert s.tracing is False
    cfg = invoke_config("t1", s)
    assert cfg == {"configurable": {"thread_id": "t1"}}
    assert "callbacks" not in cfg


def test_build_callbacks_none_when_disabled(clean_trace_env):
    assert build_callbacks(build_settings_from_dict({})) is None


def test_flag_on_env_missing_stays_off(clean_trace_env):
    """A profile flag alone never ships traces — env must also be configured."""
    s = build_settings_from_dict({"tracing": True})
    assert s.tracing is True
    assert tracing_enabled(s) is False
    assert invoke_config("t", s) == {"configurable": {"thread_id": "t"}}


def test_flag_and_env_on_adds_tracer(clean_trace_env, monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key-not-used")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    s = build_settings_from_dict({"tracing": True})
    assert tracing_enabled(s) is True
    cfg = invoke_config("t", s)
    assert "callbacks" in cfg and len(cfg["callbacks"]) == 1
    from langchain_core.tracers import LangChainTracer

    assert isinstance(cfg["callbacks"][0], LangChainTracer)


def test_api_key_alone_enables(clean_trace_env, monkeypatch):
    """LANGSMITH_API_KEY present (without the V2 flag) is enough on the env side."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake")
    s = build_settings_from_dict({"tracing": True})
    assert tracing_enabled(s) is True


def test_env_falsey_value_stays_off(clean_trace_env, monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    s = build_settings_from_dict({"tracing": True})
    assert tracing_enabled(s) is False


# --- server env-only path (RunManager has no per-run Settings) ---


def test_server_env_off_byte_identical(clean_trace_env):
    assert invoke_config_env("srv") == {"configurable": {"thread_id": "srv"}}


def test_server_env_on_adds_tracer(clean_trace_env, monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    cfg = invoke_config_env("srv")
    assert "callbacks" in cfg and len(cfg["callbacks"]) == 1


# --- resilience: tracer construction failure must NEVER break a run ---


def test_tracer_failure_degrades_to_no_tracing(clean_trace_env, monkeypatch):
    """If LangChainTracer construction raises, the run continues untraced (callbacks None)."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    def _boom(*a, **k):
        raise RuntimeError("tracer init failed")

    monkeypatch.setattr("langchain_core.tracers.LangChainTracer", _boom)
    s = build_settings_from_dict({"tracing": True})
    assert build_callbacks(s) is None
    # invoke_config stays byte-identical (no callbacks) — the run is not broken.
    assert invoke_config("t", s) == {"configurable": {"thread_id": "t"}}


def test_server_tracer_failure_degrades(clean_trace_env, monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setattr(
        "langchain_core.tracers.LangChainTracer",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert invoke_config_env("srv") == {"configurable": {"thread_id": "srv"}}


def test_api_key_only_enables_all_paths(clean_trace_env, monkeypatch):
    """M2 fix: with ONLY LANGSMITH_API_KEY set, the env-derived settings flag AND the
    server env path BOTH enable — no server-vs-worker/cli divergence."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_fakekey")
    from my_crew.config.config_builders import build_settings_from_env

    # from_env normalizes the api-key presence to tracing=True (not a literal key string).
    monkeypatch.setattr("my_crew.config.config_builders.load_dotenv", lambda *a, **k: None)
    s = build_settings_from_env()
    assert s.tracing is True
    assert tracing_enabled(s) is True  # worker/cli path ON
    assert "callbacks" in invoke_config_env("srv")  # server path ON — they agree


# --- config plumbing: profile.yaml runtime.tracing + env both reach Settings.tracing ---


def test_from_env_reads_tracing_flag(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    from my_crew.profile.loader_mapping import build_settings_dict

    out = build_settings_dict({"runtime": {"tracing": True}}, data_dir="/tmp/x")
    assert out["tracing"] is True
    assert build_settings_from_dict(out).tracing is True
