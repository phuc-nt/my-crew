"""v3 M5 S3: ToolProvider seam — graph reads via pack.tools, not hardcoded imports.

Proves the report graph's source reads flow through the active pack's ToolProvider:
- PackRegistry loads the PM provider onto Pack.tools.
- A fake provider injected into default_report_deps drives the fetchers (the seam is
  real, not bypassed) — daily uses get_open_issues; weekly uses sprint reads.
- The PM provider conforms to the ToolProvider Protocol contract.
"""

from __future__ import annotations

from my_crew.agent.report_graph import default_report_deps
from my_crew.packs import PackRegistry


class _FakeSprint:
    """Minimal stand-in: only `.id` is read by the weekly fetch path."""

    id = 42


class _FakeTools:
    """Records which reads the deps call. Returns empty record lists — these tests
    assert call routing through the provider, not the analyzed content."""

    def __init__(self, *, sprint=None) -> None:
        self.calls: list[str] = []
        self._sprint = sprint

    def get_open_issues(self, *, config):
        self.calls.append("get_open_issues")
        return []

    def get_active_sprint(self, *, config):
        self.calls.append("get_active_sprint")
        return self._sprint

    def get_sprint_issues(self, sprint_id, *, config):
        self.calls.append(f"get_sprint_issues:{sprint_id}")
        return []

    def get_open_prs(self, *, config):
        self.calls.append("get_open_prs")
        return []

    def get_recent_ci(self, *, config):
        self.calls.append("get_recent_ci")
        return []


def _deps_with(tools, *, config, settings, report_kind="daily"):
    return default_report_deps(
        config=config, settings=settings, report_kind=report_kind, tools=tools
    )


# --- registry binds the PM provider onto the pack ---


def test_registry_loads_pm_tool_provider():
    pack = PackRegistry().load("pm")
    assert pack.tools is not None
    # The provider exposes the PM read surface the report graph drives.
    for m in ("get_open_issues", "get_active_sprint", "get_sprint_issues",
              "get_open_prs", "get_recent_ci"):
        assert callable(getattr(pack.tools, m))


def test_pm_provider_exposes_the_reads_the_graph_drives():
    # The report graph calls these five reads; the provider must own all of them so the
    # graph never imports jira_read/github_read directly (the seam S3 removes).
    pack = PackRegistry().load("pm")
    for m in ("get_open_issues", "get_active_sprint", "get_sprint_issues",
              "get_open_prs", "get_recent_ci"):
        assert callable(getattr(pack.tools, m, None)), f"PM provider missing {m}"


# --- the seam is real: an injected provider drives the fetchers ---


def test_daily_fetchers_use_injected_provider(settings_factory):
    settings = settings_factory()
    config = _config(settings)
    fake = _FakeTools()
    deps = _deps_with(fake, config=config, settings=settings, report_kind="daily")

    deps.fetch_issues()
    deps.fetch_prs()
    deps.fetch_ci()

    assert fake.calls == ["get_open_issues", "get_open_prs", "get_recent_ci"]


def test_weekly_uses_active_sprint_through_provider(settings_factory):
    settings = settings_factory()
    config = _config(settings)
    fake = _FakeTools(sprint=_FakeSprint())
    deps = _deps_with(fake, config=config, settings=settings, report_kind="weekly")

    deps.fetch_issues()

    assert fake.calls == ["get_active_sprint", "get_sprint_issues:42"]


def test_weekly_no_active_sprint_falls_back_to_open_issues(settings_factory):
    settings = settings_factory()
    config = _config(settings)
    fake = _FakeTools(sprint=None)
    deps = _deps_with(fake, config=config, settings=settings, report_kind="weekly")

    deps.fetch_issues()

    assert fake.calls == ["get_active_sprint", "get_open_issues"]


def _config(settings):
    from my_crew.config.config_builders_reporting import build_reporting_config_from_dict

    return build_reporting_config_from_dict({})
