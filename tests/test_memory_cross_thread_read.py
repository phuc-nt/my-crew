"""M2-P8 Slice 3: cross-thread memory read + real-graph wiring (offline).

Proves the loop end-to-end without a real LLM/network: a real report graph wired with
the `remember` node writes facts to a tmp MEMORY.md on an internal delivery; a later
`load_profile` reads those facts back into `LoadedProfile.memory` (the P2 inject path),
and the internal prompt injects them while the external prompt does NOT.
"""

from __future__ import annotations

from datetime import date

from langgraph.store.memory import InMemoryStore

from src.agent.memory_node import make_memory_node
from src.agent.report_graph import ReportDeps, build_report_graph
from src.tools.models import CiRun, Issue, Risk


class _Settings:
    dry_run = False


def _fake_deps():
    return ReportDeps(
        fetch_issues=lambda: [Issue(key="A-1", summary="x", status="To Do", assignee="P",
                                    due_date=date(2026, 6, 1), labels=())],
        fetch_prs=lambda: [],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: [Risk(kind="blocker", severity="high", subject="A-1",
                                            detail="d", suggested_action="a")],
        compose=lambda risks: ("<p>Sprint 4 slipped</p>", 0.0, "*short*"),
        deliver=lambda short, body, approved=False: (True, "confluence=x slack=x url=None"),
    )


def test_real_graph_remember_node_writes_then_load_profile_reads(tmp_path, monkeypatch):
    # A tmp profile dir with a minimal profile.yaml + a MEMORY.md with human content.
    pdir = tmp_path / "profiles" / "acme"
    pdir.mkdir(parents=True)
    (pdir / "profile.yaml").write_text("name: Acme\n", encoding="utf-8")
    (pdir / "MEMORY.md").write_text("Human-authored note.\n", encoding="utf-8")
    memory_path = pdir / "MEMORY.md"

    remember = make_memory_node(
        extractor=lambda text: ["Sprint 4 slipped due to the auth migration"],
        agent_id="acme",
        memory_path=memory_path,
        audience="internal",
        settings=_Settings(),
    )
    graph = build_report_graph(deps=_fake_deps(), audience="internal", store=InMemoryStore(),
                               remember=remember)
    out = graph.invoke({}, config={"configurable": {"thread_id": "acme:daily:internal"}})
    assert out["delivered"] is True
    assert out["memory_written"] == 1  # the remember node fired

    # A later load_profile reads the agent fact back into LoadedProfile.memory.
    from src.profile.loader import load_profile

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")  # loader needs a key present
    loaded = load_profile("acme", profiles_dir=tmp_path / "profiles", data_dir=tmp_path / ".data")
    assert "Human-authored note." in loaded.memory  # human content preserved
    assert "Sprint 4 slipped due to the auth migration" in loaded.memory  # agent fact present


def test_internal_prompt_injects_memory_external_does_not():
    # Re-assert the guardrail: memory reaches INTERNAL reports only (P2/P5 invariant).
    from src.llm.report_prompt import build_detail_messages

    memory = "AGENT-FACT: sprint 4 slipped"
    internal = build_detail_messages([], report_date="2026-06-25", kind="daily",
                                     sprint_context=None, audience="internal", memory=memory)
    external = build_detail_messages([], report_date="2026-06-25", kind="daily",
                                     sprint_context=None, audience="external", memory=memory)
    assert any("AGENT-FACT" in m["content"] for m in internal)  # internal injects memory
    assert not any("AGENT-FACT" in m["content"] for m in external)  # external never does
