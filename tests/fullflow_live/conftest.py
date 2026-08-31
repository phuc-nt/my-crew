"""Gating, budget guard, and measurement for the live full-flow suite.

Three things this file owns and no test should re-implement:

1. **Gating.** Live is opt-in (`-m live`, see `addopts` in `pyproject.toml`), and without
   an `OPENROUTER_API_KEY` the whole package skips cleanly on top of that. CI never runs
   live, a contributor without a key sees skips rather than a wall of red, and nobody
   spends money by typing plain `pytest`. Applied in `pytest_collection_modifyitems` —
   a `pytestmark` here would be silently ignored.
2. **A per-case budget ceiling.** Every case asserts its own spend against the store
   after the run. A pipeline that loops — the failure mode that actually costs money —
   shows up as a failed test instead of a bill.
3. **Measurement.** Each case prints cost / llm-calls / wall time read from the real
   store, so a run leaves behind numbers comparable across releases rather than a bare
   pass/fail.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from tests.fullflow.harness import FullFlowHarness

try:
    from my_crew.config.config_builders import build_settings_from_env

    _ENV_SETTINGS = build_settings_from_env()
    _HAS_KEY = bool(getattr(_ENV_SETTINGS, "openrouter_api_key", None))
except Exception:  # noqa: BLE001 — a broken .env must skip, not error the collection
    _ENV_SETTINGS = None
    _HAS_KEY = False


def pytest_collection_modifyitems(items):
    """Dán `live` + điều kiện skip lên MỌI test của package này.

    Phải làm bằng hook, không bằng `pytestmark`: pytest chỉ đọc `pytestmark` ở cấp
    module hoặc class trong file test, còn `pytestmark` đặt trong `conftest.py` thì bị
    bỏ qua HOÀN TOÀN — không báo lỗi, không cảnh báo. Đo thật: `-m live` chọn ra 0 case
    trong khi cả 18 case đều là live, tức cái gate tưởng là có thật ra chưa từng tồn
    tại. Hệ quả nếu để nguyên: máy không có key chạy `pytest` sẽ ĐỎ vì lỗi xác thực
    thay vì skip sạch, còn máy có key thì tiêu tiền thật mà không ai bấm nút đồng ý.

    Đặt ở hook cũng gom được cả hai điều kiện về một chỗ, nên không có file test nào
    tự khai lại rồi lệch.
    """
    skip_live = pytest.mark.skipif(not _HAS_KEY, reason="OPENROUTER_API_KEY not configured")
    for item in items:
        if Path(str(item.fspath)).parent == Path(__file__).parent:
            item.add_marker(pytest.mark.live)
            item.add_marker(skip_live)


#: Per-case ceiling. Sized well above a healthy case (cents) and well below anything a
#: runaway loop would reach, so it fails on the pathology, not on normal variance.
MAX_COST_PER_CASE_USD = 0.15


def has_search() -> bool:
    """Whether this environment can really search.

    Cases that assert on freshness need it. Without it the sprint takes its existing
    NO_SEARCH path, which is correct behaviour but not what those cases measure — so
    they skip rather than assert something the environment cannot deliver.
    """
    for attr in ("brave_api_key", "tavily_api_key"):
        if getattr(_ENV_SETTINGS, attr, "") or "":
            return True
    return False


requires_search = pytest.mark.skipif(
    not has_search(), reason="no live search key (brave/tavily) configured"
)


#: Ceiling for a topology journey. Higher than the in-process cases: a journey drives a
#: whole brief through a real coordinator (plan → steps → review → deliver), so it is
#: several model calls where a unit-shaped live case is one or two. Still far below a
#: runaway loop, which is what the guard is actually for.
MAX_COST_PER_JOURNEY_USD = 0.30


def _live_api_key() -> str:
    """The real key, for handing to a child process's environment.

    Read through the same settings object the gate uses, so a case can never run
    against a key the gate did not see.
    """
    key = getattr(_ENV_SETTINGS, "openrouter_api_key", "") or ""
    if not key:  # pragma: no cover — the collection gate already skips these cases
        pytest.skip("OPENROUTER_API_KEY not configured")
    return key


@pytest.fixture
def live_api_key() -> str:
    """Function-scoped key — the default, used by every per-case live fixture."""
    return _live_api_key()


@pytest.fixture(scope="module")
def live_api_key_module() -> str:
    """Module-scoped key, for a fleet that several cases deliberately SHARE.

    A module-scoped fixture cannot request a function-scoped one (pytest raises
    ScopeMismatch at setup — not at collection, so it surfaces only once a real run
    starts). Both variants delegate to one implementation so the two can never read
    the key differently.
    """
    return _live_api_key()


class JourneyBudget:
    """Accumulates what a topology case spent and enforces the ceiling in teardown.

    Separate from `LiveRun` on purpose: `LiveRun` reads an in-process harness, while a
    topology case's spend lives in a store owned by another process and is only visible
    through HTTP. Same discipline, different source of truth.
    """

    def __init__(self, name: str):
        self.name = name
        self.started = time.monotonic()
        self.costs: list[float] = []
        #: The last task-status payload this journey observed, kept whole rather than
        #: picked apart here: the baseline recorder reads terminal state, lane spread and
        #: call count off it, and a journey should not have to know which of those the
        #: baseline happens to want this month.
        self.status: dict[str, Any] | None = None

    def note_cost(self, usd: float, status: dict[str, Any] | None = None) -> None:
        """Record spend, and optionally the task-status payload it came from.

        `status` is optional so the negative-control cases — which have no single task to
        be the journey's subject — keep working unchanged and simply contribute no
        baseline row. Passing it is what puts a journey INTO the baseline.
        """
        self.costs.append(float(usd or 0.0))
        if status:
            self.status = dict(status)

    @property
    def total(self) -> float:
        return round(sum(self.costs), 6)

    @property
    def llm_calls(self) -> int:
        """Captured model calls for this journey's task.

        One row per capture, so this counts calls the fleet actually made — not the
        number of steps, which hides retries and reviews behind a single row.
        """
        cost = (self.status or {}).get("cost") or {}
        return len(cost.get("steps") or [])


#: Set to a path to also WRITE what the journeys measured into a baseline JSON. Off by
#: default on purpose: an ordinary live run must not rewrite the committed baseline as a
#: side effect, or "compare against baseline" quietly becomes "compare against whatever
#: ran last" and can never fail.
BASELINE_OUT_ENV = "MY_CREW_JOURNEY_BASELINE_OUT"


def _record_baseline(budget: JourneyBudget, wall_s: float) -> None:
    """Append this journey's numbers to the baseline file named by the env var.

    Appends across the whole session rather than writing once at the end, so a suite that
    dies halfway still leaves the journeys that DID finish. A partial baseline is honest
    and obvious (missing journeys show up as one-sided rows in the delta table); losing
    a 20-minute paid run because the last case failed is neither.
    """
    out = os.environ.get(BASELINE_OUT_ENV, "").strip()
    if not out or budget.status is None:
        # No status means the case never got far enough to observe a terminal state.
        # Recording a placeholder would put a fabricated number in a file whose whole
        # job is to be trusted later.
        return

    from my_crew.bench.journey_bench import build_baseline, make_metric

    path = Path(out)
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("journeys", {})

    metric = make_metric(
        budget.name,
        cost_usd=budget.total,
        wall_s=wall_s,
        llm_calls=budget.llm_calls,
        terminal_state=_terminal_state(budget.status),
        lanes=Counter(s.get("step_type") or "?" for s in budget.status.get("steps", [])),
    )
    merged = build_baseline([], version=os.environ.get("MY_CREW_VERSION", "") or _version())
    merged["journeys"] = {**existing, budget.name: asdict(metric)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def _terminal_state(status: dict[str, Any]) -> str:
    """How this journey ended, as `is_settled` actually decided it.

    `state.status` alone is NOT enough. A task settles by either of two independent
    routes: its own status reaches a terminal value, or every step parks on a human while
    the task row still reads `open`. Journeys really do finish the second way, so
    recording `state.status` verbatim writes `open` for a journey that ended — and then a
    release that made the task row say `done` would read as a regression when it was a
    fix. Naming the parked case keeps the two apart, because "finished" and "waiting on
    the CEO" are different outcomes to regress between.
    """
    from tests.fullflow_live.topology import SETTLED_STEP_STATES, SETTLED_TASK_STATES

    state = (status.get("state") or {}).get("status") or ""
    if state in SETTLED_TASK_STATES:
        return state
    steps = status.get("steps") or []
    if steps and all(s.get("status") in SETTLED_STEP_STATES for s in steps):
        return f"parked:{state or 'open'}"
    return state


def _version() -> str:
    """Installed distribution version, same lookup `mpm` uses.

    A checkout without an install has no metadata, and the fallback says so out loud
    rather than guessing a number — a baseline mislabelled with a version it was not cut
    from is worse than one labelled "uninstalled".
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("my-crew")
    except PackageNotFoundError:
        return "0.0.0+uninstalled"


@pytest.fixture
def journey_budget(request):
    budget = JourneyBudget(request.node.name)
    yield budget
    wall = round(time.monotonic() - budget.started, 1)
    print(f"\n[journey {budget.name}] cost_usd={budget.total} wall_s={wall}")
    _record_baseline(budget, wall)
    assert budget.total <= MAX_COST_PER_JOURNEY_USD, (
        f"journey spent ${budget.total} > ${MAX_COST_PER_JOURNEY_USD} ceiling"
    )


class LiveRun:
    """One live scenario: the harness plus the numbers its run left in the store."""

    def __init__(self, harness: FullFlowHarness):
        self.h = harness
        self.started = time.monotonic()

    # -- measurement -------------------------------------------------------------

    def cost(self) -> float:
        store = self.h.store()
        try:
            return sum(
                store.sum_cost(row["id"]) for row in self.h.task_rows()
            )
        finally:
            store.close()

    def route(self, task_id: str) -> dict[str, Any]:
        store = self.h.store()
        try:
            return store.get_route(task_id) or {}
        finally:
            store.close()

    def only_task(self) -> dict[str, Any]:
        rows = self.h.task_rows()
        assert len(rows) == 1, f"expected exactly one task, got {rows}"
        return rows[0]

    def deliverable(self, task_id: str) -> str:
        """The text the CEO would actually receive, read off the real artifact dir."""
        from my_crew.agent.team_task_artifact import task_artifact_dir
        from my_crew.runtime.team_task_paths import team_tasks_root

        root: Path = task_artifact_dir(team_tasks_root(), task_id)
        if not root.exists():
            return ""
        parts = [
            p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(root.rglob("*")) if p.is_file()
        ]
        return "\n\n".join(parts)

    def measure(self) -> dict[str, Any]:
        return {
            "cost_usd": round(self.cost(), 4),
            "wall_s": round(time.monotonic() - self.started, 1),
            "llm_calls": sum(
                1 for e in self.h.trace if e.get("event") == "llm_call"
            ),
            "tasks": self.h.task_rows(),
        }


@pytest.fixture
def live_run(tmp_path, monkeypatch, request):
    """Build a live harness; on teardown print the numbers and enforce the ceiling.

    The budget check runs in teardown rather than inside each test so it applies even to
    a case that failed early — a run that fails AND overspends is exactly when the number
    matters most.
    """
    built: list[LiveRun] = []

    def _build(**kwargs) -> LiveRun:
        run = LiveRun(FullFlowHarness(tmp_path, monkeypatch, live=True, **kwargs))
        built.append(run)
        return run

    yield _build

    for run in built:
        trace = run.h.write_trace()
        try:
            measured = run.measure()
        except Exception as exc:  # noqa: BLE001 — measurement must never mask a failure
            print(f"\n[live {request.node.name}] measure failed: {exc}")
            continue
        print(f"\n[live {request.node.name}] {measured} trace={trace}")
        assert measured["cost_usd"] <= MAX_COST_PER_CASE_USD, (
            f"case spent ${measured['cost_usd']} > ${MAX_COST_PER_CASE_USD} ceiling — "
            "a live pipeline that loops is the failure this guard exists to catch"
        )
