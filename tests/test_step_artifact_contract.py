"""Artifact contracts: what a step OWES its dependents, checked by code before any grader.

A dep-less web collect owes at least one URL; the terminal deliverable owes a readable
body; intermediate drafts and review verdicts add a prompt line but no gap. Unknown or
blank input never adds a gap (fail open) — the empty-result guard in self-check owns
blank output.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.agent.step_artifact_contract import (
    FINAL_MIN_CHARS,
    ArtifactContract,
    artifact_contract_gaps,
    artifact_contract_line,
    artifact_kind_for,
    contract_for,
)


def _step(**kw):
    base = {"step_type": "work", "deps": (), "needs_web": False, "final_deliverable": False}
    return SimpleNamespace(**{**base, **kw})


def test_kind_is_derived_from_dag_position_and_flags():
    assert artifact_kind_for(_step(needs_web=True)) == "findings"
    assert artifact_kind_for(_step(needs_web=True, deps=("a",))) == "draft"
    assert artifact_kind_for(_step(final_deliverable=True, needs_web=True)) == "final"
    assert artifact_kind_for(_step(step_type="review", final_deliverable=True)) == "verdict"
    assert artifact_kind_for(_step(deps=("a",))) == "draft"


def test_findings_with_web_must_carry_a_url():
    c = ArtifactContract(kind="findings", needs_web=True)
    assert artifact_contract_gaps(c, "Giá Shopee 1.2tr, Lazada 1.1tr (nguồn: báo)") != []
    assert artifact_contract_gaps(c, "Giá Shopee 1.2tr — https://shopee.vn/x") == []
    # a findings step that never had web access is not asked for a URL it cannot produce
    assert artifact_contract_gaps(ArtifactContract("findings", needs_web=False), "ghi chú") == []


def test_final_must_be_a_readable_body_not_a_stub():
    c = ArtifactContract(kind="final")
    assert artifact_contract_gaps(c, "Đã xong.") != []
    assert artifact_contract_gaps(c, "x" * FINAL_MIN_CHARS) == []


def test_blank_text_and_no_contract_add_no_gap():
    assert artifact_contract_gaps(ArtifactContract("final"), "   ") == []
    assert artifact_contract_gaps(None, "") == []
    assert artifact_contract_gaps(ArtifactContract("draft"), "ngắn") == []


def test_prompt_line_names_the_owed_artifact():
    assert "link nguồn" in artifact_contract_line(ArtifactContract("findings", needs_web=True))
    assert "BẢN NỘP CUỐI" in artifact_contract_line(ArtifactContract("final"))
    assert "BẢN NHÁP" in artifact_contract_line(ArtifactContract("draft"))
    assert artifact_contract_line(None) == ""


def test_contract_for_reads_the_step_itself():
    c = contract_for(_step(needs_web=True))
    assert c == ArtifactContract(kind="findings", needs_web=True)
