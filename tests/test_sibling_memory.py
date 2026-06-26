"""M3-P9 A3 Slice 1: project_group parse + sibling discovery + Store read (offline)."""

from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from src.agent.memory_node import _NAMESPACE_KIND
from src.agent.sibling_memory import (
    MAX_SIBLING_FACTS,
    build_sibling_context,
    enumerate_siblings,
    read_sibling_facts,
)
from src.profile.loader import load_profile
from src.runtime.registry import RegistryEntry


def _write_profile(profiles_dir, agent_id, yaml_text):
    d = profiles_dir / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(yaml_text, encoding="utf-8")


def _seed_facts(store, agent_id, facts):
    for i, fact in enumerate(facts):
        store.put((agent_id, _NAMESPACE_KIND), f"k{i}", {"fact": fact, "ts": "t"})


# --- AC1: project_group parse ---


def test_project_group_parsed_present_absent_blank(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "withgroup", "name: A\nproject: acme\n")
    _write_profile(profiles, "nogroup", "name: B\n")
    _write_profile(profiles, "blankgroup", "name: C\nproject: '   '\n")
    data = tmp_path / ".data"
    assert load_profile("withgroup", profiles_dir=profiles, data_dir=data).project_group == "acme"
    assert load_profile("nogroup", profiles_dir=profiles, data_dir=data).project_group is None
    assert load_profile("blankgroup", profiles_dir=profiles, data_dir=data).project_group is None


# --- AC3: sibling enumeration (group filter, self-exclude) ---


def test_enumerate_siblings_filters_group_and_excludes_self(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "A", "name: A\nproject: acme\n")
    _write_profile(profiles, "B", "name: B\nproject: acme\n")
    _write_profile(profiles, "C", "name: C\nproject: beta\n")
    registry = (
        RegistryEntry("A", True), RegistryEntry("B", True), RegistryEntry("C", True),
    )
    sibs = enumerate_siblings(
        "A", "acme", registry, profiles_dir=profiles, data_dir=tmp_path / ".d"
    )
    assert sibs == ["B"]  # not A (self), not C (other group)


def test_enumerate_no_group_returns_empty(tmp_path):
    registry = (RegistryEntry("A", True), RegistryEntry("B", True))
    assert enumerate_siblings("A", None, registry) == []


# --- AC4: disabled + unloadable siblings skipped, no crash ---


def test_enumerate_skips_disabled_and_unloadable(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "A", "name: A\nproject: acme\n")
    _write_profile(profiles, "B", "name: B\nproject: acme\n")
    # C is in the registry + same group conceptually, but its profile dir is MISSING.
    # E's profile.yaml is present but MALFORMED YAML (raises yaml.YAMLError, not RuntimeError)
    # — a corrupt sibling must NOT crash the reader's run (blast-radius isolation).
    _write_profile(profiles, "E", "name: E\nproject: : : broken\n  bad: [indent\n")
    registry = (
        RegistryEntry("A", True),
        RegistryEntry("B", True),
        RegistryEntry("C", True),       # unloadable: no profiles/C/profile.yaml
        RegistryEntry("D", False),      # disabled: skipped before load
        RegistryEntry("E", True),       # malformed YAML: skipped (warn), no raise
    )
    sibs = enumerate_siblings(
        "A", "acme", registry, profiles_dir=profiles, data_dir=tmp_path / ".d"
    )
    assert sibs == ["B"]  # B kept; C/E skipped (warn, no raise); D skipped (disabled)


# --- AC3 / decision 5: read sibling facts from the Store namespace ---


def test_read_sibling_facts_from_store_namespace():
    store = InMemoryStore()
    _seed_facts(store, "B", ["B fact one", "B fact two"])
    _seed_facts(store, "A", ["A own fact"])  # self facts must NOT appear when reading B
    facts = read_sibling_facts(["B"], store)
    assert set(facts) == {"B fact one", "B fact two"}
    assert "A own fact" not in facts


def test_read_sibling_facts_capped():
    store = InMemoryStore()
    _seed_facts(store, "B", [f"fact {i}" for i in range(MAX_SIBLING_FACTS + 10)])
    assert len(read_sibling_facts(["B"], store)) == MAX_SIBLING_FACTS


# --- AC2: allocation-free no-op (no LlmClient when nothing to do) ---


class _Loaded:
    def __init__(self, group):
        self.profile_id = "A"
        self.project_group = group


def _boom_llm(*_a, **_k):
    raise AssertionError("LlmClient must NOT be constructed on the no-op path")


def test_build_sibling_context_noop_no_group(monkeypatch):
    monkeypatch.setattr("src.llm.client.LlmClient", _boom_llm)
    store = InMemoryStore()
    skills, selector = build_sibling_context(_Loaded(None), object(), store, ())
    assert skills == () and selector is None


def test_build_sibling_context_noop_lone_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("src.llm.client.LlmClient", _boom_llm)
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "A", "name: A\nproject: acme\n")
    store = InMemoryStore()
    registry = (RegistryEntry("A", True),)  # only self in the group
    facts, selector = build_sibling_context(
        _Loaded("acme"), object(), store, registry, profiles_dir=profiles, data_dir=tmp_path / ".d"
    )
    assert facts == () and selector is None


def test_build_sibling_context_returns_facts_and_selector(tmp_path, monkeypatch):
    # Non-empty path: helper returns the sibling facts tuple + the real LLM ranker.
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr("src.llm.client.LlmClient", lambda *_a, **_k: object())
    profiles = tmp_path / "profiles"
    _write_profile(profiles, "A", "name: A\nproject: acme\n")
    _write_profile(profiles, "B", "name: B\nproject: acme\n")
    store = InMemoryStore()
    _seed_facts(store, "B", ["B shared a milestone fact"])
    registry = (RegistryEntry("A", True), RegistryEntry("B", True))
    facts, selector = build_sibling_context(
        _Loaded("acme"), object(), store, registry, profiles_dir=profiles, data_dir=tmp_path / ".d"
    )
    assert facts == ("B shared a milestone fact",)
    assert selector is not None  # real ranker paired on the non-empty path
