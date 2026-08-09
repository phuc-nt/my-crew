"""v76 phase 2: honest-data metrics — Wilson CI, min-sample, zero-contrast, degrade."""

from __future__ import annotations

from my_crew.runtime.agent_metrics import (
    MIN_SAMPLE,
    agent_metrics,
    render_team_metrics_vi,
    wilson_ci,
)


def test_wilson_ci_behaves_at_edges():
    lo, hi = wilson_ci(0, 0)
    assert (lo, hi) == (0.0, 1.0)  # no data → total uncertainty, not a crash
    lo, hi = wilson_ci(5, 5)
    assert hi == 1.0 and lo > 0.4  # all-pass at n=5 still leaves real uncertainty
    lo, hi = wilson_ci(50, 100)
    assert lo < 0.5 < hi and (hi - lo) < 0.25  # tightens with n


def _seed(tmp_path, monkeypatch, rows):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path

    cs = CaptureStore(capture_db_path())
    try:
        for i, (agent, status) in enumerate(rows):
            cs.record(attempt_id=f"a{i}", task_id="t1", step_id=f"s{i}",
                      agent_id=agent, engine="native", status=status,
                      duration_ms=1000, cost_usd=0.01)
    finally:
        cs.close()


def test_metrics_rates_ci_and_min_sample(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch,
          [("researcher", "done")] * 6 + [("researcher", "needs_decision")] * 2
          + [("content", "done")] * 2)
    m = agent_metrics()
    r = m["agents"]["researcher"]
    assert r["attempts"] == 8 and r["tentative"] is False
    assert r["done_rate"]["value"] == 0.75
    lo, hi = r["done_rate"]["ci"]
    assert lo < 0.75 < hi
    c = m["agents"]["content"]
    assert c["tentative"] is True and c["attempts"] < MIN_SAMPLE  # small-n badge


def test_all_pass_bucket_reports_no_contrast(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [("qa", "done")] * 7)
    m = agent_metrics()
    assert m["agents"]["qa"]["done_rate"].get("no_contrast") is True
    text = render_team_metrics_vi(m)
    assert "chưa có ca hỏng để so" in text


def test_render_marks_tentative_rows(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [("pong", "done")] * 2)
    text = render_team_metrics_vi(agent_metrics())
    assert "pong*" in text


def test_broken_store_degrades_to_error_section(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import capture_db_path

    capture_db_path().parent.mkdir(parents=True, exist_ok=True)
    capture_db_path().write_text("not a database")
    m = agent_metrics()
    assert "error" in m  # soft error, no raise
    assert "Chưa đọc được" in render_team_metrics_vi(m)
