"""v19 Phase 4: auto-generated capability block (internal-only)."""

from __future__ import annotations

from src.profile.capability_block import build_capability_block


class _LP:
    """Minimal LoadedProfile stand-in."""

    def __init__(self, *, domain="pm", skills=(), web_search=False, provider="static"):
        self.domain = domain
        self.skills = skills
        self.web_search = web_search
        self.memory_config = type("MC", (), {"provider": provider})()


class _Pack:
    def __init__(self, kinds):
        self.report_kinds = {k: None for k in kinds}


def test_block_lists_domain_and_memory_provider():
    block = build_capability_block(_LP(domain="office", provider="static"), None)
    assert "Lĩnh vực: office" in block
    assert "Bộ nhớ: static" in block
    assert block.startswith("--- Năng lực nhân sự ---")


def test_block_deterministic_sorted():
    lp = _LP(skills=("zebra", "alpha"))
    b1 = build_capability_block(lp, None)
    b2 = build_capability_block(lp, None)
    assert b1 == b2  # deterministic
    assert "alpha, zebra" in b1  # sorted


def test_block_includes_pack_report_kinds_sorted():
    block = build_capability_block(_LP(), _Pack(["weekly", "daily", "okr"]))
    assert "Loại báo cáo: daily, okr, weekly" in block


def test_block_web_search_flag():
    assert "Tra cứu web: bật" in build_capability_block(_LP(web_search=True), None)
    assert "Tra cứu web" not in build_capability_block(_LP(web_search=False), None)


def test_block_capped_600_chars():
    lp = _LP(skills=tuple(f"ky-nang-{i}" for i in range(200)))
    block = build_capability_block(lp, None)
    assert len(block) <= 600


def test_kioku_provider_shown():
    assert "Bộ nhớ: kioku" in build_capability_block(_LP(provider="kioku"), None)
