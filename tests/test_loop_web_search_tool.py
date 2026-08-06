"""The tool-calling loop can SEARCH the web, not just scrape a URL it already knows.

The gap this closes (v73): the loop tier's toolset had `web.scrape` but no search — while
the native tier had search but no loop. Neither could do "tìm → đọc trang → rút số → tìm
tiếp", so a research step could not produce a real figure on ANY tier. Production shape:
`research_prices` was interrupted four times with "trình bày số liệu đi" and never could —
the coordinator's guidance even said "dùng browse nếu cần" about a tool the agent did not
have. The fix reuses the same `web_search` engine (redact → fail-closed → provider →
audit) and the same per-agent profile flag as the native hook: one opt-in, both tiers.

No LLM and no network here — provider calls are stubbed at the `web_search` seam. The loop
itself is exercised in the E2E tier with a real model.
"""

from __future__ import annotations

from my_crew.runtime_backends.read_only_toolset import build_read_toolset
from my_crew.tools.search_result_formatter import SearchResult


class _FakeConfig:
    """Stand-in ReportingConfig — read callables only close over it, never call here."""


class _Settings:
    def __init__(self, tavily="tk"):
        self.tavily_api_key = tavily
        self.brave_api_key = None
        self.firecrawl_base_url = None
        self.firecrawl_api_key = None


def test_the_flag_and_a_key_together_arm_the_tool():
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(), web_search=True)
    assert "web.search" in tools


def test_no_flag_means_no_tool_even_with_a_key():
    """The per-agent opt-in gates egress — a configured key alone must not arm it,
    or every loop agent silently gains network search the operator never enabled."""
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(), web_search=False)
    assert "web.search" not in tools


def test_no_key_means_no_tool_even_with_the_flag():
    """Same two-gate rule as the native hook (`_resolve_search_hook`): flag without a
    provider key degrades to the tool simply not being offered, never a crashing tool."""
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(tavily=None), web_search=True)
    assert "web.search" not in tools


def test_results_arrive_spotlight_wrapped(monkeypatch):
    """Search snippets are third-party text — the classic injection carrier. They must
    reach the model through the same delimiter/spotlight wrap the native hook applies,
    not as bare strings the loop would read as instructions."""
    monkeypatch.setattr(
        "my_crew.tools.web_search_tool.web_search",
        lambda query, *, config, audit_log=None: [
            SearchResult(title="Giá thuê Q1", snippet="Hạng A ~55 USD/m²/tháng",
                         source="https://example.com/bao-cao/q1-2026"),
        ],
    )
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(), web_search=True)
    out = tools["web.search"]({"query": "giá thuê văn phòng quận 1"})
    assert "55 USD" in out
    # The FULL result URL (path included) must survive into the body — hostname-only
    # makes every hit a dead end: the model can cite the site but never open the page,
    # and the whole point of search inside a loop is the follow-up scrape.
    assert "https://example.com/bao-cao/q1-2026" in out
    assert out != "Hạng A ~55 USD/m²/tháng", "snippet must be wrapped, not returned bare"


def test_empty_results_tell_the_model_to_retry_differently(monkeypatch):
    """The loop's advantage over the one-shot hook is the model can rephrase and try
    again — but only if emptiness comes back as guidance, not as silence."""
    monkeypatch.setattr(
        "my_crew.tools.web_search_tool.web_search",
        lambda query, *, config, audit_log=None: [],
    )
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(), web_search=True)
    out = tools["web.search"]({"query": "abc"})
    assert "không có kết quả" in out
    assert "thử" in out


def test_a_blank_query_is_answered_not_crashed():
    tools = build_read_toolset(_FakeConfig(), settings=_Settings(), web_search=True)
    assert "cần tham số" in tools["web.search"]({"query": ""})


def test_the_step_runner_threads_the_same_profile_flag():
    """One opt-in covers both tiers: the runner must forward the agent's existing
    `web_search:` flag (the one arming the native hook) to the loop toolset."""
    import inspect

    from my_crew.runtime import team_step_runner

    src = inspect.getsource(team_step_runner)
    assert '_extra["web_search"]' in src and 'getattr(loaded, "web_search"' in src
