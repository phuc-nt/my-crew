"""v35 P2: memory consolidation sweep — condense the AGENT-MEMORY section, fail-safe.

The LLM never free-writes MEMORY.md: code extracts the marker section, validates the
model's condensed fact list, archives the full original, and only then swaps the
section. Every failure path must leave MEMORY.md byte-identical.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from my_crew.agent.memory_mirror import END, START, replace_agent_section
from my_crew.memory.consolidation import (
    CONSOLIDATE_THRESHOLD_CHARS,
    _parse_fact_lines,
    _validate,
    maybe_consolidate,
)

_NOW = datetime(2026, 7, 13, 3, 0, 0)


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.cost_usd = 0.001


class _FakeLlm:
    def __init__(self, content):
        self._content = content
        self.calls = 0

    def complete(self, messages, **kw):
        self.calls += 1
        return _FakeResult(self._content)


class _Settings:
    dry_run = False


def _big_memory_file(tmp_path, agent_id="agent-x", n_facts=400):
    """A MEMORY.md whose agent section exceeds the threshold, with human text around it."""
    facts = [
        f"fact số {i}: điều đã học được trong ngày, khá dài dòng để vượt ngưỡng"
        for i in range(n_facts)
    ]
    section = "\n".join([START, *facts, END])
    text = "# Sổ tay (phần người viết)\n\n" + section + "\nGhi chú cuối của người dùng.\n"
    profile_dir = tmp_path / "profiles" / agent_id
    profile_dir.mkdir(parents=True)
    path = profile_dir / "MEMORY.md"
    path.write_text(text, encoding="utf-8")
    assert len("\n".join(facts)) > CONSOLIDATE_THRESHOLD_CHARS
    return path, facts


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point the module's path helpers at tmp so no real profile/agent data is touched."""
    monkeypatch.setattr(
        "my_crew.profile.loader.profile_memory_path",
        lambda agent_id, profiles_dir=None: tmp_path / "profiles" / agent_id / "MEMORY.md",
    )
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir",
        lambda agent_id: tmp_path / "data" / agent_id,
    )
    return tmp_path


def test_consolidates_and_archives(wired):
    path, facts = _big_memory_file(wired)
    condensed = "\n".join(f"fact gộp {i}" for i in range(10))
    llm = _FakeLlm(condensed)
    assert maybe_consolidate("agent-x", _Settings(), now=_NOW, llm=llm) is True
    new = path.read_text(encoding="utf-8")
    # Human content outside markers preserved byte-for-byte.
    assert new.startswith("# Sổ tay (phần người viết)\n\n")
    assert new.rstrip("\n").endswith("Ghi chú cuối của người dùng.")
    assert "fact gộp 3" in new and "fact số 42" not in new
    # Full original archived with a timestamp header; never loaded (different filename).
    archive = path.with_name("MEMORY.archive.md")
    assert archive.exists()
    arch = archive.read_text(encoding="utf-8")
    assert "fact số 42" in arch and "archived 2026-07-13T03:00:00" in arch


@pytest.mark.parametrize("bad_output", [
    "",  # empty
    "chỉ một dòng ngắn\n" * 2000,  # bigger than the original — no shrink
    "fact có control char \x00 bên trong",  # control chars
    f"fact chèn marker {START} phá file",  # marker injection
])
def test_bad_llm_output_keeps_original(wired, bad_output):
    path, _ = _big_memory_file(wired)
    before = path.read_text(encoding="utf-8")
    assert maybe_consolidate("agent-x", _Settings(), now=_NOW, llm=_FakeLlm(bad_output)) is False
    assert path.read_text(encoding="utf-8") == before
    assert not path.with_name("MEMORY.archive.md").exists()  # no write ⇒ no archive


def test_below_threshold_no_llm_call(wired):
    profile_dir = wired / "profiles" / "agent-x"
    profile_dir.mkdir(parents=True)
    small = "\n".join([START, "một fact nhỏ", END]) + "\n"
    (profile_dir / "MEMORY.md").write_text(small, encoding="utf-8")
    llm = _FakeLlm("x")
    assert maybe_consolidate("agent-x", _Settings(), now=_NOW, llm=llm) is False
    assert llm.calls == 0


def test_cooldown_blocks_second_attempt(wired):
    path, _ = _big_memory_file(wired)
    llm = _FakeLlm("")  # invalid output — attempt fails, but cooldown still stamps
    s = _Settings()
    assert maybe_consolidate("agent-x", s, now=_NOW, llm=llm) is False
    assert llm.calls == 1
    # 1 minute later: cooldown active — NO second LLM call.
    assert maybe_consolidate("agent-x", s, now=_NOW + timedelta(minutes=1), llm=llm) is False
    assert llm.calls == 1
    # 25h later: cooldown expired — attempts again.
    assert maybe_consolidate("agent-x", s, now=_NOW + timedelta(hours=25), llm=llm) is False
    assert llm.calls == 2


def test_dry_run_skips_before_llm(wired):
    _big_memory_file(wired)

    class _Dry:
        dry_run = True

    llm = _FakeLlm("x")
    assert maybe_consolidate("agent-x", _Dry(), now=_NOW, llm=llm) is False
    assert llm.calls == 0


def test_no_agent_section_untouched(wired):
    profile_dir = wired / "profiles" / "agent-x"
    profile_dir.mkdir(parents=True)
    text = "Toàn bộ file là ghi chú tay của người dùng, không có marker.\n" * 500
    path = profile_dir / "MEMORY.md"
    path.write_text(text, encoding="utf-8")
    llm = _FakeLlm("x")
    assert maybe_consolidate("agent-x", _Settings(), now=_NOW, llm=llm) is False
    assert llm.calls == 0
    assert path.read_text(encoding="utf-8") == text


def test_llm_exception_keeps_original(wired):
    path, _ = _big_memory_file(wired)
    before = path.read_text(encoding="utf-8")

    class _Boom:
        def complete(self, messages, **kw):
            raise ConnectionError("provider down")

    assert maybe_consolidate("agent-x", _Settings(), now=_NOW, llm=_Boom()) is False
    assert path.read_text(encoding="utf-8") == before


def test_parse_fact_lines_strips_fences_and_bullets():
    raw = "```\n- fact một\nfact hai\n\n```"
    assert _parse_fact_lines(raw) == ["fact một", "fact hai"]


def test_validate_rejects_growth_in_count():
    original = ["một fact khá dài " * 50]  # 1 fact, big
    condensed = ["a", "b"]  # smaller chars but MORE facts
    assert _validate(original, condensed) is not None


def test_replace_agent_section_swaps_not_merges():
    text = "trên\n" + "\n".join([START, "cũ 1", "cũ 2", END]) + "\ndưới\n"
    out = replace_agent_section(text, ["mới"])
    assert "cũ 1" not in out and "mới" in out
    assert out.startswith("trên\n") and out.endswith("\ndưới\n")


def test_service_gate_only_fires_at_sweep_hour(monkeypatch):
    from my_crew.runtime import service

    calls = []
    monkeypatch.setattr(
        "my_crew.memory.consolidation.run_consolidation_sweep",
        lambda now=None: calls.append(now) or 0,
    )
    service._consolidate_memories_best_effort(datetime(2026, 7, 13, 14, 0))
    assert calls == []
    service._consolidate_memories_best_effort(datetime(2026, 7, 13, 3, 5))
    assert len(calls) == 1
    # A sweep crash must not propagate into the tick.
    monkeypatch.setattr(
        "my_crew.memory.consolidation.run_consolidation_sweep",
        lambda now=None: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    service._consolidate_memories_best_effort(datetime(2026, 7, 13, 3, 6))  # no raise
