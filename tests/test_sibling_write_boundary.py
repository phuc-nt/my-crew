"""M3-P9 A3 Slice 2: WO-self memory write boundary (fail loud)."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from my_crew.agent.memory_node import _NAMESPACE_KIND, _assert_self_namespace, make_memory_node


class _Settings:
    dry_run = False


def test_assert_self_namespace_allows_own():
    # No raise when the namespace is the agent's own.
    _assert_self_namespace(("acme", _NAMESPACE_KIND), "acme")


def test_assert_self_namespace_rejects_foreign():
    with pytest.raises(PermissionError, match="not this agent's namespace"):
        _assert_self_namespace(("other", _NAMESPACE_KIND), "acme")


def test_assert_self_namespace_rejects_wrong_kind():
    with pytest.raises(PermissionError):
        _assert_self_namespace(("acme", "not-memory"), "acme")


def test_memory_node_writes_own_namespace(tmp_path):
    # A delivered internal run writes facts to (self, "memory") and nowhere else.
    store = InMemoryStore()
    node = make_memory_node(
        extractor=lambda text: ["A đã chốt deadline sprint 5"],
        agent_id="acme",
        memory_path=tmp_path / "MEMORY.md",
        audience="internal",
        settings=_Settings(),
    )
    out = node({"delivered": True, "report_text": "some report body"}, store=store)
    assert out["memory_written"] == 1
    assert len(store.search(("acme", _NAMESPACE_KIND))) == 1  # written to own ns
    assert store.search(("other", _NAMESPACE_KIND)) == []  # never another agent's ns
