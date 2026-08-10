"""Benchmark the sprint pipeline's spend on a standing set of briefs.

These are budget tests, not behaviour tests. The unit suite already proves the
pipeline is correct; what it does not do is notice when correctness gets more
expensive — a prompt tweak that costs one extra revise round on every brief passes
every existing test while giving back a third of what v77 bought.

Each case asserts the CODE's decisions: how many searches, how many model calls, what
the router thought the subjects were. All deterministic, all offline.
"""

from __future__ import annotations

import pytest

from my_crew.bench.brief_suite import (
    ALL_CASES,
    NO_ENUMERATION,
    OVER_CAP,
    STREAMING_SERVICES,
)
from my_crew.bench.pipeline_bench import planned_queries, run_case


def _covering_draft(case) -> str:
    """A draft that mentions every subject, so coverage passes on round one.

    Built from what the router actually parsed rather than from `expected_entities`,
    which some cases deliberately leave empty — a draft that misses a subject would
    buy a revise round and measure the wrong thing.
    """
    from my_crew.runtime.sprint_runner import resolve_entities

    entities = resolve_entities(case.goal, case.acceptance) or ["tổng quan"]
    lines = [f"| {e} | dữ liệu | https://example.com/{i} |" for i, e in enumerate(entities)]
    return "| Mục | Thông tin | Nguồn |\n" + "\n".join(lines)


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.name)
def test_each_brief_stays_inside_its_spend_budget(case, monkeypatch):
    result = run_case(case, draft=_covering_draft(case), monkeypatch=monkeypatch)
    assert result.violations(case) == [], f"{case.name}: {result.violations(case)}"


def test_a_covered_draft_costs_exactly_one_model_call():
    """The floor case. If a brief whose draft already covers everything ever costs
    more than one call, the coverage check has stopped believing its own answer."""
    case = STREAMING_SERVICES
    with pytest.MonkeyPatch.context() as mp:
        result = run_case(case, draft=_covering_draft(case), monkeypatch=mp)
    assert result.llm_calls == 1


def test_an_uncoverable_brief_still_stops_at_the_revise_ceiling():
    """The doom case: a model that never covers the gaps must not be asked forever.
    This is the 780s react loop the whole mode exists to avoid."""
    case = STREAMING_SERVICES
    with pytest.MonkeyPatch.context() as mp:
        result = run_case(
            case,
            draft="Chưa có dữ liệu.",
            revisions=["Vẫn chưa có.", "Vẫn chưa có.", "Vẫn chưa có."],
            monkeypatch=mp,
        )
    # draft + at most MAX_REVISE_ROUNDS revisions, and never more than the budget.
    assert result.llm_calls <= case.max_llm_calls
    assert result.searches <= case.max_searches


def test_a_brief_with_no_entity_list_does_not_fan_out():
    """No enumeration means no per-entity searches to invent."""
    with pytest.MonkeyPatch.context() as mp:
        result = run_case(NO_ENUMERATION, draft=_covering_draft(NO_ENUMERATION), monkeypatch=mp)
    assert result.searches <= NO_ENUMERATION.max_searches
    assert result.entities == []


def test_the_prefetch_cap_holds_when_the_brief_lists_more_than_the_budget():
    """Nine subjects must not buy nine searches: the cap is the code's decision, not
    the brief's. Otherwise a long enough brief reopens the unbounded-spend hole."""
    from my_crew.runtime.sprint_runner import listed_entities

    subjects = listed_entities(OVER_CAP.goal)
    queries = planned_queries(OVER_CAP)
    assert len(subjects) > len(queries), "expected more subjects than the query cap allows"

    with pytest.MonkeyPatch.context() as mp:
        result = run_case(OVER_CAP, draft=_covering_draft(OVER_CAP), monkeypatch=mp)
    assert result.searches <= OVER_CAP.max_searches


def test_every_planned_query_carries_its_subject_and_the_topic():
    """The UAT bug that cost a whole benchmark run: a topic phrase cut mid-noun made
    every query search for nothing in particular. Each query must name one subject
    AND enough topic to disambiguate it."""
    queries = planned_queries(STREAMING_SERVICES)
    for entity in STREAMING_SERVICES.expected_entities:
        assert any(entity in q for q in queries), f"no query names {entity}"
    for q in queries:
        assert "streaming" in q.lower(), f"query lost its topic: {q!r}"
