"""v3 M5 S6: generic Task/Event model + PM Issue↔Task mapping.

Proves the generic cross-domain model is sufficient for PM (the abstraction proof M6
relies on):
- Task/Event construct with neutral fields + sensible defaults.
- PM's Issue → Task → Issue round-trips losslessly.
- The risk + resource analyzers produce IDENTICAL output whether fed the original
  Issues or Issues reconstructed through the generic Task mapping — so routing PM data
  through the generic shape changes nothing.
"""

from __future__ import annotations

import importlib.util
from datetime import date

from my_crew.agent.resource_analyzer import build_resource_report
from my_crew.agent.risk_analyzer import analyze
from my_crew.config.settings import REPO_ROOT
from my_crew.tools.models import Event, Issue, Task


def _pm_models():
    """Load the pm-pack Issue↔Task mapping module (hyphenated dir → importlib)."""
    path = REPO_ROOT / "domain-packs" / "pm-pack" / "models.py"
    spec = importlib.util.spec_from_file_location("_pm_models", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ISSUES = [
    Issue("PM-1", "Login bug", "In Progress", "alice",
          date(2026, 6, 1), ("blocker",), True),
    Issue("PM-2", "Add export", "To Do", "bob", date(2026, 7, 1), (), False),
    Issue("PM-3", "Refactor", "To Do", None, None, ("tech-debt",), False),
]


# --- generic models construct ---


def test_task_constructs_with_defaults():
    t = Task(id="X-1", title="t", status="open")
    assert t.assignee is None and t.labels == () and t.kind == "task" and t.extra == ()


def test_event_constructs_with_defaults():
    e = Event(id="E-1", summary="hired")
    assert e.actor is None and e.kind == "event" and e.occurred_on is None


# --- PM mapping is lossless ---


def test_issue_to_task_preserves_all_fields():
    m = _pm_models()
    t = m.issue_to_task(_ISSUES[0])
    assert (t.id, t.title, t.status, t.assignee, t.due_date, t.labels, t.flagged) == (
        "PM-1", "Login bug", "In Progress", "alice", date(2026, 6, 1), ("blocker",), True
    )
    assert t.kind == "issue"


def test_issue_task_round_trip_is_identity():
    m = _pm_models()
    for issue in _ISSUES:
        assert m.task_to_issue(m.issue_to_task(issue)) == issue


# --- analyzers are byte-identical when PM data routes through the generic shape ---


def test_risk_analyzer_identical_through_task_mapping():
    m = _pm_models()
    via_task = [m.task_to_issue(m.issue_to_task(i)) for i in _ISSUES]
    today = date(2026, 6, 15)
    assert analyze(_ISSUES, [], [], today=today) == analyze(via_task, [], [], today=today)


def test_resource_analyzer_identical_through_task_mapping():
    m = _pm_models()
    via_task = [m.task_to_issue(m.issue_to_task(i)) for i in _ISSUES]
    today = date(2026, 6, 15)
    kw = {"today": today, "overload_ratio": 1.5, "blocker_label_substring": "block"}
    assert build_resource_report(_ISSUES, **kw) == build_resource_report(via_task, **kw)
