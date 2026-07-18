"""`team_task_consult_propose.propose_consult_targets` (M33): the ONE structured LLM
call deciding whether/who/what to pre-work consult about.

Load-bearing:
- happy path: valid JSON -> up to MAX_PROPOSALS (agent_id, question) pairs.
- empty roster -> no LLM call at all, `[]`.
- malformed JSON / bad schema -> degrade to `[]`, never raises.
- a proposed agent_id NOT in the given roster is filtered out (never trust the model's
  own claim of a valid id).
- more than MAX_PROPOSALS proposed items are truncated, not passed through.
"""

from __future__ import annotations

import my_crew.llm.client as llm_client_mod
from my_crew.agent.team_task_consult_propose import (
    ConsultProposalError,
    parse_consult_proposal,
    propose_consult_targets,
)
from my_crew.config.config_builders import build_settings_from_dict


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


def _wire_llm(monkeypatch, *, content: str):
    calls = []

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages):
            calls.append(messages)
            return _FakeResult(content)

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    return calls


def _settings(tmp_path):
    return build_settings_from_dict({"data_dir": tmp_path})


def test_propose_consult_targets_happy_path(tmp_path, monkeypatch):
    _wire_llm(
        monkeypatch,
        content='{"consults":[{"agent_id":"colleague-1","question":"Ưu tiên gì?"}]}',
    )
    result = propose_consult_targets(
        "step title", "handoff", [("colleague-1", "pm")], settings=_settings(tmp_path),
    )
    assert result == [("colleague-1", "Ưu tiên gì?", [])]


def test_propose_consult_targets_empty_roster_skips_llm_call(tmp_path, monkeypatch):
    calls = _wire_llm(monkeypatch, content='{"consults":[]}')
    result = propose_consult_targets(
        "step title", "handoff", [], settings=_settings(tmp_path),
    )
    assert result == []
    assert calls == []  # no LLM call made when there is no valid target at all


def test_propose_consult_targets_degrades_on_malformed_json(tmp_path, monkeypatch):
    _wire_llm(monkeypatch, content="not json at all")
    result = propose_consult_targets(
        "step title", "handoff", [("colleague-1", "pm")], settings=_settings(tmp_path),
    )
    assert result == []


def test_propose_consult_targets_filters_agent_id_not_in_roster(tmp_path, monkeypatch):
    _wire_llm(
        monkeypatch,
        content='{"consults":[{"agent_id":"not-in-roster","question":"q"}]}',
    )
    result = propose_consult_targets(
        "step title", "handoff", [("colleague-1", "pm")], settings=_settings(tmp_path),
    )
    assert result == []


def test_propose_consult_targets_filters_blank_question(tmp_path, monkeypatch):
    _wire_llm(
        monkeypatch,
        content='{"consults":[{"agent_id":"colleague-1","question":"   "}]}',
    )
    result = propose_consult_targets(
        "step title", "handoff", [("colleague-1", "pm")], settings=_settings(tmp_path),
    )
    assert result == []


def test_parse_consult_proposal_truncates_to_max_proposals():
    raw = (
        '{"consults":['
        '{"agent_id":"a","question":"q1"},'
        '{"agent_id":"b","question":"q2"},'
        '{"agent_id":"c","question":"q3"}'
        "]}"
    )
    proposal = parse_consult_proposal(raw)
    assert len(proposal.consults) == 2  # MAX_PROPOSALS == 2


def test_parse_consult_proposal_rejects_non_json():
    import pytest

    with pytest.raises(ConsultProposalError):
        parse_consult_proposal("not json")


def test_parse_consult_proposal_rejects_non_object_json():
    import pytest

    with pytest.raises(ConsultProposalError):
        parse_consult_proposal("[1, 2, 3]")


def test_parse_consult_proposal_rejects_bad_schema():
    import pytest

    with pytest.raises(ConsultProposalError):
        parse_consult_proposal('{"consults":[{"agent_id": 5}]}')
