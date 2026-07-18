"""Slice 2: registry loader — parse/validate registry.yaml."""

from __future__ import annotations

import pytest

from my_crew.runtime.registry import RegistryEntry, load_registry


def _write(tmp_path, text):
    p = tmp_path / "registry.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_registry(tmp_path):
    p = _write(tmp_path, "agents:\n  - id: default\n    enabled: true\n  - id: acme\n")
    entries = load_registry(p)
    assert entries == (
        RegistryEntry(id="default", enabled=True),
        RegistryEntry(id="acme", enabled=True),  # enabled defaults True when omitted
    )


def test_enabled_false_preserved(tmp_path):
    p = _write(tmp_path, "agents:\n  - id: beta\n    enabled: false\n")
    assert load_registry(p) == (RegistryEntry(id="beta", enabled=False),)


def test_example_registry_template_loads():
    # v18: registry.yaml is user data; the COMMITTED artifact is the example template a
    # fresh checkout bootstraps from — it must parse to default + admin (registering
    # admin is what turns the CEO chat-ops box on).
    from my_crew.runtime.registry import _EXAMPLE_PATH

    assert load_registry(_EXAMPLE_PATH) == (
        RegistryEntry(id="default", enabled=True),
        RegistryEntry(id="admin", enabled=True),
    )


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        load_registry(tmp_path / "nope.yaml")


def test_no_agents_key_raises(tmp_path):
    p = _write(tmp_path, "something: else\n")
    with pytest.raises(RuntimeError, match="must be a list"):
        load_registry(p)


def test_agents_not_a_list_raises(tmp_path):
    p = _write(tmp_path, "agents: notalist\n")
    with pytest.raises(RuntimeError, match="must be a list"):
        load_registry(p)


def test_blank_id_raises(tmp_path):
    p = _write(tmp_path, "agents:\n  - id: ''\n")
    with pytest.raises(RuntimeError, match="non-empty string"):
        load_registry(p)


def test_duplicate_id_raises(tmp_path):
    p = _write(tmp_path, "agents:\n  - id: dup\n  - id: dup\n")
    with pytest.raises(RuntimeError, match="duplicate"):
        load_registry(p)


@pytest.mark.parametrize("yaml_id", ["on", "off", "yes", "no", "true", "false"])
def test_yaml_reserved_word_id_rejected(tmp_path, yaml_id):
    # Bare `on`/`yes`/`true`/... parse to a bool in YAML 1.1 → must be rejected, not
    # silently coerced to "True"/"False" and routed to the wrong agent dir.
    p = _write(tmp_path, f"agents:\n  - id: {yaml_id}\n")
    with pytest.raises(RuntimeError, match="non-empty string"):
        load_registry(p)
    # quoting it makes it a real id
    pq = _write(tmp_path, f'agents:\n  - id: "{yaml_id}"\n')
    assert load_registry(pq)[0].id == yaml_id


def test_int_id_rejected(tmp_path):
    p = _write(tmp_path, "agents:\n  - id: 123\n")
    with pytest.raises(RuntimeError, match="non-empty string"):
        load_registry(p)


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "Acme", "a b", "agent.1"])
def test_path_unsafe_id_rejected(tmp_path, bad_id):
    # The registry is the single validation boundary: a path-unsafe id can't reach a
    # worker argv or a data dir (it raises here, before any spawn).
    p = _write(tmp_path, f'agents:\n  - id: "{bad_id}"\n')
    with pytest.raises(RuntimeError, match="Invalid agent id"):
        load_registry(p)


def test_bootstrap_from_example_default_path_only(tmp_path, monkeypatch):
    """v18: a missing DEFAULT registry bootstraps from the example (atomic copy) —
    but an explicit `path` keeps the strict FileNotFoundError contract (tests,
    registry_edit tmp-validation, --registry callers)."""
    import my_crew.runtime.registry as reg

    example = tmp_path / "registry.example.yaml"
    example.write_text("agents:\n  - id: a1\n    enabled: true\n")
    target = tmp_path / "registry.yaml"
    monkeypatch.setattr(reg, "_REGISTRY_PATH", target)
    monkeypatch.setattr(reg, "_EXAMPLE_PATH", example)

    entries = reg.load_registry()  # default path → bootstrap
    assert [e.id for e in entries] == ["a1"]
    assert target.exists()  # real file minted for subsequent edits

    # bootstrap never overwrites an existing registry
    target.write_text("agents:\n  - id: real-team\n")
    assert [e.id for e in reg.load_registry()] == ["real-team"]

    # explicit path: no bootstrap, strict error
    import pytest

    with pytest.raises(FileNotFoundError):
        reg.load_registry(tmp_path / "khong-ton-tai.yaml")
