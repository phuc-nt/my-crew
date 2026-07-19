"""End-to-end: running a team step writes one capture row with the attempt's telemetry.

Drives the same worker entrypoint the coordinator spawns (`_run_team_step_kind`) against an
isolated tmp root, then asserts the capture store gained a row for that attempt with the
engine, status, timing, and cost the step produced. A best-effort capture that silently no-oped
would leave the table empty — this is the regression guard the plan requires.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.capture_store import CaptureStore
from my_crew.runtime.team_task_store import TeamTaskStore


def _patch_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _fake_loaded():
    return SimpleNamespace(
        soul="", project="", memory="", company_docs=(), skills=(), domain="pm",
        web_search=False,
    )


def _fake_llm(monkeypatch, *, cost=0.02):
    class _Result:
        content = "step output"
        cost_usd = cost
        prompt_tokens = 120
        completion_tokens = 80

    class _Llm:
        def __init__(self, _s):
            pass

        def complete(self, _m):
            return _Result()

    import my_crew.llm.client as mod
    monkeypatch.setattr(mod, "LlmClient", _Llm)


def _plan(store: TeamTaskStore):
    # One single-step task; the step is unblocked so reserve→run drives the whole path.
    steps = [{"step_id": "s1", "title": "Do it", "assigned_to": "a1", "deps": []}]
    store.create_task(task_id="t1", title="demo", original_request="cap test")
    store.set_plan("t1", steps, plan_hash="")


def test_team_step_run_writes_capture_row(tmp_path, monkeypatch):
    from my_crew.runtime.worker import _run_team_step_kind

    _patch_root(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, cost=0.02)

    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    _plan(store)
    attempt = store.reserve_step("t1", "s1")
    store.close()

    settings = build_settings_from_dict({"data_dir": tmp_path})
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1", "--attempt-id", attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings,
        data_dir=tmp_path / "agents" / "a1",
    )
    assert rc == 0

    cs = CaptureStore(tmp_path / "captures.sqlite3")
    row = cs.get(attempt)
    cs.close()
    assert row is not None, "a completed step must write exactly one capture row"
    assert row["engine"] == "native"  # _fake_loaded has no agent_runtime → native default
    assert row["status"] == "done"
    assert row["cost_source"] == "exact"
    assert row["input_tokens"] == 120 and row["output_tokens"] == 80
    assert row["duration_ms"] >= 0
    assert row["started_at"] and row["ended_at"]


def test_review_step_path_threads_telemetry(monkeypatch):
    # Regression: run_team_step dispatches review steps through _run_review, passing the
    # telemetry collector. _run_review must accept it and thread it to run_review_step — a
    # signature mismatch here TypeErrors every review step in production while the work-only
    # tests stay green. This drives the review branch directly.
    from types import SimpleNamespace

    import my_crew.runtime.team_step_runner as runner

    captured = {}

    def _fake_run_review_step(loaded, settings, *, data_dir, review_input, telemetry=None):
        captured["telemetry"] = telemetry  # proves the kwarg reached the callee
        return {"status": "done", "cost_usd": 0.001, "delivered": True,
                "room_message": "", "passed": True, "failures": []}

    monkeypatch.setattr(runner, "run_review_step", _fake_run_review_step, raising=False)
    monkeypatch.setattr("my_crew.agent.review_graph.run_review_step", _fake_run_review_step)

    step = SimpleNamespace(
        step_id="s1-review-0-0", parent_step_id="s1", deps=("s1",), review_round=0,
        seq=5, title="review", assigned_to="reviewer",
    )
    sentinel = object()

    class _Store:
        def get_step(self, _task, step_id):
            # parent + graded dep both resolve to a delivered content step
            return SimpleNamespace(
                seq=2, attempt_id="v1", acceptance="", title="content", step_id=step_id,
            )

    out = runner._run_review(
        SimpleNamespace(soul="", project="", memory="", company_docs=(), skills=(), domain="pm"),
        None, task_id="t1", step=step, store=_Store(), telemetry=sentinel,
    )
    assert out["status"] == "done"
    assert captured["telemetry"] is sentinel  # telemetry threaded through, no TypeError


def test_review_step_run_writes_criteria_to_its_own_capture_row(tmp_path, monkeypatch):
    """v54 P4b end-to-end: running a REVIEW step through the real worker entrypoint
    persists the per-criterion list to ITS capture row (keyed by the review's own
    attempt_id) — the content step's capture row (a different attempt_id) is untouched."""
    from my_crew.runtime.worker import _run_team_step_kind

    _patch_root(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, cost=0.02)

    # Content step delivered through the real worker path — it gets its own capture row.
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    _plan(store)
    content_attempt = store.reserve_step("t1", "s1")
    store.close()
    settings = build_settings_from_dict({"data_dir": tmp_path})
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", content_attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings,
        data_dir=tmp_path / "agents" / "a1",
    )
    assert rc == 0

    # Mint the review row exactly like the ticker's review-insert rule would.
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.insert_step(
        "t1",
        {
            "step_id": "s1-review-0-0", "title": "Soát chéo: Do it", "assigned_to": "a1",
            "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 0,
        },
    )
    review_attempt = store.reserve_step("t1", "s1-review-0-0")
    store.close()

    criteria = [
        {"criterion": "handles empty input", "passed": True, "note": ""},
        {"criterion": "returns typed errors", "passed": False, "note": "missing validation"},
    ]

    def _fake_run_review_step(loaded, settings, *, data_dir, review_input, telemetry=None):
        return {
            "status": "done", "cost_usd": 0.001, "delivered": True, "room_message": "",
            "passed": False, "failures": ["returns typed errors"], "criteria": criteria,
        }

    monkeypatch.setattr(
        "my_crew.agent.review_graph.run_review_step", _fake_run_review_step,
    )

    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1-review-0-0",
         "--attempt-id", review_attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings,
        data_dir=tmp_path / "agents" / "a1",
    )
    assert rc == 0

    cs = CaptureStore(tmp_path / "captures.sqlite3")
    review_row = cs.get(review_attempt)
    content_row = cs.get(content_attempt)
    cs.close()

    assert review_row is not None
    assert review_row["step_type"] == "review"
    import json
    assert json.loads(review_row["criteria_json"]) == criteria
    # the reviewed content step's OWN capture row must stay untouched (no criteria)
    assert content_row is not None
    assert content_row["criteria_json"] is None
