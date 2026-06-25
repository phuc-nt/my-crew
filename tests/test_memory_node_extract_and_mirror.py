"""M2-P8 Slice 3: memory extract + mirror node (offline, fake extractor + InMemoryStore).

Covers the pure MEMORY.md rewrite (markers/preserve/cap), the gated node end-to-end,
the negatives (dry-run / not-delivered / external write nothing), and the guardrails
(no gateway call; external never reads memory; the agent section never clobbers human
content).
"""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from src.agent.memory_mirror import END, START, rewrite_agent_section, write_memory_file
from src.agent.memory_node import make_memory_node

# --- pure rewrite fn (the most important unit) ---


def test_rewrite_creates_markers_when_absent():
    out = rewrite_agent_section("Human notes here.", ["fact A", "fact B"])
    assert START in out and END in out
    assert "Human notes here." in out  # human content preserved
    assert "fact A" in out and "fact B" in out


def test_rewrite_preserves_human_above_and_below():
    existing = f"TOP human\n\n{START}\nold fact\n{END}\n\nBOTTOM human"
    out = rewrite_agent_section(existing, ["new fact"])
    assert "TOP human" in out and "BOTTOM human" in out
    assert "old fact" in out and "new fact" in out  # appended within the section
    # human content untouched: only the marker region changed
    assert out.startswith("TOP human")
    assert out.rstrip().endswith("BOTTOM human")


def test_rewrite_dedupes_identical_facts():
    existing = f"{START}\nfact X\n{END}\n"
    out = rewrite_agent_section(existing, ["fact X", "fact Y"])
    assert out.count("fact X") == 1  # not duplicated
    assert "fact Y" in out


def test_rewrite_caps_to_last_n():
    existing = f"{START}\n" + "\n".join(f"f{i}" for i in range(5)) + f"\n{END}\n"
    out = rewrite_agent_section(existing, ["f5", "f6"], cap=3)
    # only the last 3 of [f0..f6 deduped] survive
    kept = [ln for ln in out.splitlines() if ln.startswith("f")]
    assert kept == ["f4", "f5", "f6"]


def test_write_memory_file_atomic(tmp_path):
    p = tmp_path / "MEMORY.md"
    p.write_text("HUMAN\n", encoding="utf-8")
    write_memory_file(p, ["remembered thing"])
    text = p.read_text(encoding="utf-8")
    assert "HUMAN" in text and "remembered thing" in text and START in text
    assert not list(tmp_path.glob("MEMORY.md.*.tmp"))  # temp cleaned up by os.replace


def test_repeated_writes_keep_exactly_one_marker_pair():
    # Regression: each write must REPLACE the section in place, not double the markers.
    text = "Human note.\n"
    for i in range(1, 6):
        text = rewrite_agent_section(text, [f"fact-{i}"])
        assert text.count(START) == 1, f"START doubled after write {i}"
        assert text.count(END) == 1, f"END doubled after write {i}"
    assert "Human note." in text  # human content survives every write
    assert all(f"fact-{i}" in text for i in range(1, 6))  # all facts accumulated


def test_malformed_markers_normalize_to_one_pair():
    # END before START / single marker / human-pasted marker → one clean pair, no append.
    for bad in (f"{END}\nx\n{START}", f"{START}\nx", f"y\n{END}", f"{START}\n{START}\nz\n{END}"):
        out = rewrite_agent_section(bad, ["f"])
        assert out.count(START) == 1 and out.count(END) == 1
        assert "f" in out


# --- the node: end-to-end + gates ---


class _Settings:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run


def _node(tmp_path, *, audience="internal", dry_run=False, facts=("F1", "F2")):
    return make_memory_node(
        extractor=lambda text: list(facts),
        agent_id="acme",
        memory_path=tmp_path / "MEMORY.md",
        audience=audience,
        settings=_Settings(dry_run=dry_run),
    )


def test_node_writes_store_and_memory_on_internal_delivered(tmp_path):
    store = InMemoryStore()
    node = _node(tmp_path)
    out = node({"delivered": True, "report_text": "<p>sprint 4 slipped</p>"}, store=store)
    assert out["memory_written"] == 2
    # Store has the facts under (agent_id, "memory")
    items = store.search(("acme", "memory"))
    vals = {it.value["fact"] for it in items}
    assert vals == {"F1", "F2"}
    # MEMORY.md mirrors them
    text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "F1" in text and "F2" in text and START in text


def test_node_dry_run_writes_nothing(tmp_path):
    store = InMemoryStore()
    out = _node(tmp_path, dry_run=True)({"delivered": True, "report_text": "x"}, store=store)
    assert out["memory_written"] == 0
    assert list(store.search(("acme", "memory"))) == []
    assert not (tmp_path / "MEMORY.md").exists()


def test_node_not_delivered_writes_nothing(tmp_path):
    store = InMemoryStore()
    out = _node(tmp_path)({"delivered": False, "report_text": "x"}, store=store)
    assert out["memory_written"] == 0
    assert list(store.search(("acme", "memory"))) == []


def test_node_external_writes_nothing(tmp_path):
    store = InMemoryStore()
    out = _node(tmp_path, audience="external")(
        {"delivered": True, "report_text": "x"}, store=store
    )
    assert out["memory_written"] == 0
    assert list(store.search(("acme", "memory"))) == []


def test_node_dedupes_store_by_content_hash(tmp_path):
    store = InMemoryStore()
    node = _node(tmp_path, facts=("same fact", "same fact"))
    node({"delivered": True, "report_text": "x"}, store=store)
    # identical facts collapse to ONE store entry (content-hash key)
    assert len(list(store.search(("acme", "memory")))) == 1


def test_node_does_not_import_action_gateway(tmp_path, monkeypatch):
    # Guardrail: the memory node is INTERNAL — it must never call the Action Gateway.
    import src.actions.action_gateway as gw_mod

    calls = []
    monkeypatch.setattr(gw_mod.ActionGateway, "execute", lambda self, *a, **k: calls.append(1))
    store = InMemoryStore()
    _node(tmp_path)({"delivered": True, "report_text": "x"}, store=store)
    assert calls == []  # zero gateway calls
