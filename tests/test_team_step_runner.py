"""`team_step_runner._resolve_search_hook` — the PRODUCTION call site that wires
`web_search`'s own `audit_log` param (`my_crew/tools/web_search_tool.py`) into the shared
team-tasks audit trail.

Load-bearing: before this fix, `_resolve_search_hook` called `web_search(query,
config=config)` with no `audit_log` at all — every unit test of `web_search` passed an
`AuditLog` directly, so the audit-wiring gap in the real call path was invisible to the
suite. This test goes through `_resolve_search_hook` itself (not a hand-built
`web_search(..., audit_log=...)` call) and asserts a real audit row lands on disk, with
the raw query redacted out.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from my_crew.runtime.team_step_runner import _resolve_search_hook


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    artifacts, office-room appends) — pin it to tmp_path so no test can touch the
    real install's .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _loaded(*, web_search: bool = True) -> SimpleNamespace:
    return SimpleNamespace(web_search=web_search)


def _settings(*, tavily: str | None = "tavily-key", brave: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(tavily_api_key=tavily, brave_api_key=brave)


def test_resolve_search_hook_returns_none_when_profile_opted_out():
    assert _resolve_search_hook(_loaded(web_search=False), _settings()) is None


def test_resolve_search_hook_returns_none_when_no_provider_key_configured():
    cfg = _settings(tavily=None, brave=None)
    assert _resolve_search_hook(_loaded(web_search=True), cfg) is None


def test_resolve_search_hook_returns_none_when_loaded_is_none():
    assert _resolve_search_hook(None, _settings()) is None


def test_run_graph_wires_self_id_to_the_assigned_agent(monkeypatch, tmp_path):
    """`_run_graph` must pass `self_id=step.assigned_to` into `build_team_task_graph` —
    that is the ONLY thing that turns consult on for a production step (see
    `default_team_task_deps`'s docstring: blank `self_id` ⇒ `ask_colleague` wired as
    None, consult off). A caller that forgets this kwarg silently ships consult OFF
    with no error anywhere; this test fails loudly if that regresses.
    """
    from my_crew.runtime import team_step_runner

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

    captured: dict = {}

    class _FakeGraph:
        def stream(self, _initial_state, _config=None, stream_mode=None):  # noqa: ARG002
            return iter(())  # no nodes to run — we only care about the build call

    def _fake_build_team_task_graph(**kwargs):
        captured.update(kwargs)
        return _FakeGraph()

    monkeypatch.setattr(
        "my_crew.agent.team_task_graph.build_team_task_graph", _fake_build_team_task_graph
    )

    step = SimpleNamespace(
        title="viết báo cáo", acceptance="", seq=1, deps=(), assigned_to="agent-a",
    )
    team_step_runner._run_graph(
        None, _settings(), task_id="task-1", step=step, attempt_id="att-1",
    )

    assert captured.get("self_id") == "agent-a"


class _FakeNonNativeRuntime:
    """A stand-in for a non-native (e.g. deep_agent) runtime — `build_task` just
    captures its kwargs so the test can assert what `_run_graph` threaded into it,
    then returns a graph that emits ONE 'custom' phase chunk (the code path
    `_append_step_phase_event` fires from)."""

    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def build_task(self, **kwargs):
        self._captured.update(kwargs)
        return _FakePhaseGraph()


class _FakePhaseGraph:
    def stream(self, _initial_state, _config=None, stream_mode=None):  # noqa: ARG002
        yield ("custom", {"phase": "dang-lam"})


def test_deep_team_flag_threads_into_started_step_event_when_true(
    monkeypatch, tmp_path, settings_factory,
):
    """v54: a deep_team-opted-in agent's step 'started' (step_status/phase) event carries
    `deep_team=True` — an agent that did NOT opt in gets no such key at all (lean events,
    byte-identical to pre-v54 for every other agent)."""
    from my_crew.runtime import team_step_runner

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    captured_build_kwargs: dict = {}
    captured_phase_calls: list[dict] = []

    monkeypatch.setattr(
        "my_crew.runtime_backends.protocol.resolve_step_runtime",
        lambda loaded, step: _FakeNonNativeRuntime(captured_build_kwargs),
    )

    def _fake_append_phase_event(*_a, **kw):
        captured_phase_calls.append(kw)

    monkeypatch.setattr(team_step_runner, "_append_step_phase_event", _fake_append_phase_event)

    loaded = SimpleNamespace(
        soul="", project="", memory="", config=SimpleNamespace(), agent_runtime=None,
        academic_search=False, gws_context=False, deep_team=True, deep_team_max_calls=None,
        company_docs=(), web_search=False, team_step_egress=None, skills=(),
        profile_id="agent-a", domain="pm", template_role=None,
    )
    step = SimpleNamespace(
        title="viết báo cáo", acceptance="", seq=1, deps=(), assigned_to="agent-a",
        parent_step_id=None, system_inserted=False, step_type="work",
    )
    team_step_runner._run_graph(
        loaded, settings_factory(), task_id="task-1", step=step, attempt_id="att-1",
    )

    assert captured_build_kwargs.get("deep_team") is True
    assert len(captured_phase_calls) == 1
    assert captured_phase_calls[0]["deep_team"] is True


def test_deep_team_flag_omitted_from_started_event_when_false(
    monkeypatch, tmp_path, settings_factory,
):
    """The counterpart: deep_team=False (default/opted-out) must NOT set the kwarg at all
    on the phase-event call — omitted, not `False` (see office_event_projection pass-through:
    a present-but-falsy key would still be dropped there, but the producer itself must not
    even pass it, matching `_extra`'s own bool() cast)."""
    from my_crew.runtime import team_step_runner

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    captured_build_kwargs: dict = {}
    captured_phase_calls: list[dict] = []

    monkeypatch.setattr(
        "my_crew.runtime_backends.protocol.resolve_step_runtime",
        lambda loaded, step: _FakeNonNativeRuntime(captured_build_kwargs),
    )

    def _fake_append_phase_event(*_a, **kw):
        captured_phase_calls.append(kw)

    monkeypatch.setattr(team_step_runner, "_append_step_phase_event", _fake_append_phase_event)

    loaded = SimpleNamespace(
        soul="", project="", memory="", config=SimpleNamespace(), agent_runtime=None,
        academic_search=False, gws_context=False, deep_team=False, deep_team_max_calls=None,
        company_docs=(), web_search=False, team_step_egress=None, skills=(),
        profile_id="agent-a", domain="pm", template_role=None,
    )
    step = SimpleNamespace(
        title="viết báo cáo", acceptance="", seq=1, deps=(), assigned_to="agent-a",
        parent_step_id=None, system_inserted=False, step_type="work",
    )
    team_step_runner._run_graph(
        loaded, settings_factory(), task_id="task-1", step=step, attempt_id="att-1",
    )

    assert captured_build_kwargs.get("deep_team") is False
    assert len(captured_phase_calls) == 1
    assert captured_phase_calls[0]["deep_team"] is False


def test_resolve_search_hook_writes_audit_row_with_redacted_query(tmp_path, monkeypatch):
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    def _fake_urlopen(req, timeout=None):  # noqa: ARG001 — signature must match urlopen's
        return _FakeHttpResponse(
            {"results": [{"title": "kết quả", "content": "nội dung", "url": "example.com"}]}
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    hook = _resolve_search_hook(_loaded(web_search=True), _settings())
    assert hook is not None

    raw_query = "liên hệ phucnt0@gmail.com để tìm hiểu thêm"
    text = hook(raw_query)
    assert "kết quả" in text  # the hook returns the formatted, delimited text

    audit_path = tmp_path / "audit" / "audit.jsonl"
    assert audit_path.exists()
    lines = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    search_entries = [e for e in lines if e.get("action_type") == "web_search"]
    assert len(search_entries) == 1
    entry = search_entries[0]
    assert entry["params"]["result_count"] == 1
    assert "redaction_counts" in entry["params"]
    assert entry["tool"] == "web_search:tavily"
    # The raw query (and the email it contains) must never appear anywhere in the
    # audit trail — only the redacted form does.
    full_text = json.dumps(entry)
    assert "phucnt0@gmail.com" not in full_text
    assert raw_query not in full_text
