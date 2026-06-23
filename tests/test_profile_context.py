"""Slice 2: ProfileContext helpers — empty ⇒ identity, non-empty ⇒ prepend/wrap."""

from __future__ import annotations

from src.profile.context import EMPTY, ProfileContext, build_context_block, prepend_persona


def test_empty_context_defaults():
    assert EMPTY == ProfileContext(persona="", project="", memory="")


def test_prepend_persona_empty_is_identity():
    system = "SYSTEM RULES"
    assert prepend_persona(system, "") is system
    assert prepend_persona(system, "   ") is system  # whitespace-only ⇒ identity


def test_prepend_persona_non_empty():
    out = prepend_persona("SYSTEM", "Tone: ngắn gọn.")
    assert out == "Tone: ngắn gọn.\n\nSYSTEM"
    assert out.endswith("SYSTEM")  # original system kept as authoritative tail


def test_build_context_block_both_empty_is_blank():
    assert build_context_block("", "") == ""
    assert build_context_block("  ", "\n") == ""  # whitespace-only ⇒ blank


def test_build_context_block_project_only():
    out = build_context_block("label p0 = blocker", "")
    assert "label p0 = blocker" in out
    assert "Bối cảnh dự án" in out
    assert "Bộ nhớ agent" not in out
    assert out.endswith("\n\n")  # ready to prepend to a user message


def test_build_context_block_both():
    out = build_context_block("proj", "mem")
    assert "proj" in out and "mem" in out
    assert out.index("Bối cảnh dự án") < out.index("Bộ nhớ agent")  # project first
