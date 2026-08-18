"""The tool-loop tier must TELL the model which tools it holds.

The gap this closes: the loop tier reuses the native tier's system prompt so persona/skills/
red-lines stay identical — but that prompt was written for a tier with no tools (search fires
once before the model speaks, output pasted in). Nothing told the loop model it actually holds
`web.search`/`web.scrape`, and the one tool-shaped clause it did see listed file scratch only.
Production shape (task d4679e1fbe14/step1): the researcher, holding a working search tool,
returned "Xin phép thực hiện tra cứu web để..." instead of searching — a step burnt, an
intervention spent, and $0.017 paid for a request for permission it never needed.

No LLM and no network — the assertions read the composed system prompt.
"""

from __future__ import annotations

from my_crew.runtime_backends.react_loop import _tool_capability_contract


def _contract(*names: str) -> str:
    return _tool_capability_contract({n: (lambda _q: "") for n in names})


def test_the_contract_names_every_tool_actually_bound():
    """Built from the live tools_map, not a hardcoded list — an agent whose profile denies
    web egress must never be told it can search."""
    out = _contract("web.search", "web.scrape", "history.search")
    assert "web_search" in out and "web_scrape" in out and "history_search" in out


def test_tool_names_match_the_bound_callable_names():
    """`_as_lc_tools` binds `web.search` as `web_search` (dots are illegal in tool names).
    Advertising the dotted form would name a tool the model cannot call."""
    out = _contract("web.search")
    assert "web_search" in out
    assert "web.search" not in out


def test_an_agent_without_web_tools_is_not_told_it_can_search():
    out = _contract("history.search", "jira.issues")
    assert "web_search" not in out and "web_scrape" not in out


def test_the_contract_forbids_asking_permission_to_use_a_tool():
    """The exact production failure: the model asked to be ALLOWED to search rather than
    searching. Holding the tool IS the permission."""
    out = _contract("web.search")
    assert "KHÔNG cần xin phép" in out
    assert "không hỏi xin phép" in out


def test_the_contract_states_the_loop_shape():
    """One search is rarely enough. The model must know it may call again after reading —
    that iteration is the entire difference from the native one-shot tier."""
    out = _contract("web.search")
    assert "VÒNG LẶP" in out
    assert "gọi tiếp" in out


def test_empty_toolset_adds_nothing():
    """A tools-tier run with no tools bound must not claim capabilities it lacks."""
    assert _tool_capability_contract({}) == ""


def test_exhausted_search_must_report_the_gap_not_invent_data():
    """The honesty rule has to survive into the tier that can actually go looking: a model
    told to keep calling tools must still say 'không tìm được' rather than fill the hole."""
    out = _contract("web.search")
    assert "KHÔNG bịa" in out


def test_a_browsing_tier_is_held_to_the_source_standard():
    """Blind-judge losses repeated on one axis: the loop settled for dealer/blog hits
    while the baseline cited official pages with access dates. The contract must set
    the bar — official pages of the subject entity first, domain + access date next
    to every figure."""
    out = _contract("web.search", "web.scrape")
    assert "CHUẨN NGUỒN" in out
    assert "CHÍNH THỨC" in out
    assert "ngày" in out and "truy cập" in out
    assert "thứ" in out and "cấp" in out  # secondary sources named as the fallback


def test_internal_search_is_not_scored_against_the_web_source_standard():
    """`history.search` can search — but only internal history. It cannot reach an
    official page, so demanding one would set an unmeetable bar."""
    out = _contract("history.search", "jira.issues")
    assert "CHUẨN NGUỒN" not in out


def test_the_scratch_clause_no_longer_reads_as_the_whole_toolset():
    """`_STATE_SCRATCH_CONTRACT` opened with "GHI CHÚ CÔNG CỤ: bạn có..." — the only
    tool-shaped sentence in the prompt, listing file scratch alone. That framing actively
    confirmed the model's wrong belief that it had no way to look anything up."""
    from my_crew.runtime_backends.react_loop import _STATE_SCRATCH_CONTRACT

    assert _STATE_SCRATCH_CONTRACT.lstrip().startswith("NGOÀI RA")
