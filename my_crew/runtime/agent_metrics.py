"""Per-agent performance metrics over the capture store (v76 phase 2).

The CAPTURE side has existed since v43 (one telemetry row per attempt); this is the
missing ANALYZE side, built with my-dandori's honest-data discipline:

- every rate carries a Wilson 95% CI and its sample size — no bare point estimates;
- `tentative=True` under MIN_SAMPLE completed attempts: display with a `*`, and any
  automated consumer (the v76 phase-3 closed loop) must refuse to act on it;
- a bucket where nothing ever failed reports `no_contrast=True` ("no failing run to
  compare against") instead of a 100% that reads like signal;
- every metric names its `formula` — a number nobody can trace is a number nobody
  should trust;
- reading NEVER raises: a broken store yields `{"error": ...}` per section (metrics
  are observability, they must not take a surface down with them).

Measurement is fail-open by plan invariant: nothing in this module is consulted on
any dispatch/step path.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

#: Below this many completed attempts a rate is decoration, not evidence.
MIN_SAMPLE = 5
#: Terminal capture statuses that count as a completed attempt (denominator).
_TERMINAL = ("done", "needs_decision", "failed")


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial rate — behaves at small n and at 0%/100%,
    which is exactly where naive ±z·SE lies the most."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def _rate(successes: int, n: int, formula: str) -> dict[str, Any]:
    low, high = wilson_ci(successes, n)
    out: dict[str, Any] = {
        "value": round(successes / n, 4) if n else None,
        "ci": (round(low, 4), round(high, 4)),
        "n": n,
        "tentative": n < MIN_SAMPLE,
        "formula": formula,
    }
    if n and successes == n:
        # All-pass bucket: a 100% with no failing run to contrast against is absence
        # of evidence, not excellence — flagged, never silently displayed as signal.
        out["no_contrast"] = True
    return out


def agent_metrics(window_days: int = 14) -> dict[str, Any]:
    """Per-agent metrics over the last `window_days`. Never raises."""
    since = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    result: dict[str, Any] = {"window_days": window_days, "since": since, "agents": {}}

    rows: list[tuple] = []
    try:
        from my_crew.runtime.capture_store import CaptureStore
        from my_crew.runtime.team_task_paths import capture_db_path

        cs = CaptureStore(capture_db_path())
        try:
            rows = cs._conn.execute(
                "SELECT agent_id, status, step_type, cost_usd, duration_ms, engine "
                "FROM captures WHERE ts >= ? AND agent_id != ''", (since,),
            ).fetchall()
        finally:
            cs.close()
    except Exception as exc:  # noqa: BLE001 — per-section degrade, never raise
        logger.warning("agent_metrics: capture read failed", exc_info=True)
        result["error"] = f"capture store unavailable: {exc}"
        return result

    interventions: dict[str, int] = {}
    try:
        import sqlite3

        from my_crew.runtime.team_task_store import team_tasks_db_path

        con = sqlite3.connect(team_tasks_db_path())
        try:
            for agent_id, iv in con.execute(
                "SELECT assigned_to, COALESCE(SUM(intervention_count),0) "
                "FROM team_steps GROUP BY assigned_to",
            ):
                interventions[str(agent_id)] = int(iv)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — the section simply reports without this column
        logger.warning("agent_metrics: interventions read failed", exc_info=True)
        result["interventions_error"] = "team store unavailable"

    per_agent: dict[str, list[tuple]] = {}
    for row in rows:
        per_agent.setdefault(str(row[0]), []).append(row)

    for agent_id, agent_rows in sorted(per_agent.items()):
        work = [r for r in agent_rows if r[2] != "review" and r[1] in _TERMINAL]
        n = len(work)
        done = sum(1 for r in work if r[1] == "done")
        needs_decision = sum(1 for r in work if r[1] == "needs_decision")
        durations = [r[4] for r in work if r[4]]
        costs = [r[3] for r in work if r[3]]
        result["agents"][agent_id] = {
            "attempts": n,
            "done_rate": _rate(done, n, "done / terminal work attempts (window)"),
            "needs_decision_rate": _rate(
                needs_decision, n, "needs_decision / terminal work attempts (window)"),
            "avg_duration_s": round(sum(durations) / len(durations) / 1000, 1)
            if durations else None,
            "avg_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
            "interventions_total": interventions.get(agent_id),
            "tentative": n < MIN_SAMPLE,
        }
    return result


def render_team_metrics_vi(metrics: dict[str, Any]) -> str:
    """Compact Vietnamese rendering for the Telegram `team_metrics` command.

    `*` marks tentative (n < MIN_SAMPLE) rows; an all-pass bucket says so in words —
    the honest-data rules travel with the number wherever it is displayed."""
    if metrics.get("error"):
        return f"Chưa đọc được số liệu: {metrics['error']}"
    agents = metrics.get("agents") or {}
    if not agents:
        return (f"Chưa có attempt nào trong {metrics.get('window_days', '?')} ngày qua "
                "— giao việc xong quay lại xem nhé.")
    lines = [f"Số liệu đội {metrics.get('window_days')} ngày qua "
             f"(* = mẫu nhỏ <{MIN_SAMPLE}, chỉ tham khảo):"]
    for agent_id, m in agents.items():
        star = "*" if m.get("tentative") else ""
        dr = m.get("done_rate") or {}
        if dr.get("no_contrast"):
            done_txt = f"{dr['n']}/{dr['n']} xong (chưa có ca hỏng để so)"
        elif dr.get("value") is not None:
            lo, hi = dr.get("ci", (0, 1))
            done_txt = f"xong {dr['value']:.0%} (CI {lo:.0%}–{hi:.0%}, n={dr['n']})"
        else:
            done_txt = "chưa có attempt"
        extras = []
        if m.get("avg_duration_s") is not None:
            extras.append(f"~{m['avg_duration_s']:.0f}s/bước")
        if m.get("avg_cost_usd") is not None:
            extras.append(f"~${m['avg_cost_usd']:.3f}/bước")
        if m.get("interventions_total"):
            extras.append(f"{m['interventions_total']} lần can thiệp")
        tail = f" · {' · '.join(extras)}" if extras else ""
        lines.append(f"- {agent_id}{star}: {done_txt}{tail}")
    return "\n".join(lines)
