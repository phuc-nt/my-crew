"""`team_task_roster.pick_reviewer` (M32 Decision D): deterministic, code-only peer
selection — never the author, prefers a "kiem/qa/review" id hint, else the
alphabetically-first peer, `None` on an empty peer set (1-staff fleet).
"""

from __future__ import annotations

from my_crew.agent.team_task_roster import pick_reviewer


def test_pick_reviewer_never_returns_author():
    roster = [("author", "pm"), ("peer-a", "pm")]
    reviewer = pick_reviewer("author", roster)
    assert reviewer == "peer-a"
    assert reviewer != "author"


def test_pick_reviewer_prefers_qa_hint_over_alphabetical():
    roster = [("author", "pm"), ("agent-a", "pm"), ("agent-qa", "pm")]
    assert pick_reviewer("author", roster) == "agent-qa"


def test_pick_reviewer_prefers_kiem_hint_case_insensitive():
    roster = [("author", "pm"), ("agent-b", "pm"), ("Agent-KIEM", "pm")]
    assert pick_reviewer("author", roster) == "Agent-KIEM"


def test_pick_reviewer_ties_among_hinted_ids_broken_alphabetically():
    roster = [("author", "pm"), ("z-review", "pm"), ("a-review", "pm")]
    assert pick_reviewer("author", roster) == "a-review"


def test_pick_reviewer_falls_back_to_alphabetically_first_peer():
    roster = [("author", "pm"), ("zeta", "pm"), ("alpha", "pm")]
    assert pick_reviewer("author", roster) == "alpha"


def test_pick_reviewer_same_domain_peer_is_valid():
    roster = [("author", "pm"), ("peer-a", "pm")]
    # Both same domain — pick_reviewer must not filter by domain (Finding F4).
    assert pick_reviewer("author", roster) == "peer-a"


def test_pick_reviewer_returns_none_when_no_peer_exists():
    roster = [("author", "pm")]
    assert pick_reviewer("author", roster) is None


def test_pick_reviewer_returns_none_on_empty_roster():
    assert pick_reviewer("author", []) is None
