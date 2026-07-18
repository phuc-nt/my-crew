"""Team-step remember node folds the extraction cost into the step total (capture honesty).

The remember node runs an extra LLM call to extract facts. If its cost were dropped, a
captured "exact" cost would understate what the attempt actually spent. These tests prove the
node reads `result_text` (team-step key, not `report_text`), and when `costed=True` returns a
`cost_usd` = prior step cost + extraction cost.
"""

from __future__ import annotations

from my_crew.agent.memory_node import make_memory_node


class _Settings:
    dry_run = False


def _node(tmp_path, extractor, *, costed, key="result_text"):
    return make_memory_node(
        extractor=extractor,
        agent_id="agent-x",
        memory_path=tmp_path / "MEMORY.md",
        audience="internal",
        settings=_Settings(),
        report_state_key=key,
        costed=costed,
    )


def test_costed_node_folds_extraction_cost_into_total(tmp_path):
    # extractor returns (facts, cost); node adds cost to the prior step cost_usd.
    node = _node(tmp_path, lambda text: (["fact one"], 0.002), costed=True)
    out = node({"delivered": True, "result_text": "the output", "cost_usd": 0.010})
    assert out["memory_written"] == 1
    assert abs(out["cost_usd"] - 0.012) < 1e-9  # 0.010 work + 0.002 extract


def test_costed_node_handles_missing_prior_cost(tmp_path):
    node = _node(tmp_path, lambda text: (["f"], 0.003), costed=True)
    out = node({"delivered": True, "result_text": "out", "cost_usd": None})
    assert abs(out["cost_usd"] - 0.003) < 1e-9  # None prior treated as 0


def test_costed_node_no_cost_when_extract_cost_none(tmp_path):
    # A failed/unpriced extraction reports cost None → do not emit a cost_usd override.
    node = _node(tmp_path, lambda text: (["f"], None), costed=True)
    out = node({"delivered": True, "result_text": "out", "cost_usd": 0.01})
    assert "cost_usd" not in out


def test_reads_result_text_key_not_report_text(tmp_path):
    # Team-step state uses result_text; a node keyed on report_text would find nothing.
    node = _node(tmp_path, lambda text: (["seen: " + text], 0.0), costed=True)
    out = node({"delivered": True, "result_text": "sprint data", "cost_usd": 0.0})
    assert out["memory_written"] == 1


def test_gated_out_when_not_delivered(tmp_path):
    node = _node(tmp_path, lambda text: (["f"], 0.005), costed=True)
    out = node({"delivered": False, "result_text": "out", "cost_usd": 0.01})
    assert out == {"memory_written": 0}


def test_report_path_uncosted_stays_facts_only(tmp_path):
    # costed=False (report graphs): extractor returns a bare list, node emits no cost_usd.
    node = _node(tmp_path, lambda text: ["a fact"], costed=False, key="report_text")
    out = node({"delivered": True, "report_text": "report body", "cost_usd": 0.02})
    assert out["memory_written"] == 1 and "cost_usd" not in out
