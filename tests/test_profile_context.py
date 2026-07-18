"""Slice 2: ProfileContext helpers — empty ⇒ identity, non-empty ⇒ prepend/wrap."""

from __future__ import annotations

from my_crew.profile.context import EMPTY, ProfileContext, build_context_block, prepend_persona


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


# --- HTML-comment placeholders (scaffolded profile md files) count as empty ---


def test_comment_only_persona_is_identity():
    # A scaffolded SOUL.md holds only an HTML-comment placeholder; it must NOT be
    # prepended (its meta-text would confuse the model).
    system = "SYSTEM"
    placeholder = "<!-- Persona. Empty ⇒ the v1 system prompt is used unchanged. -->\n"
    assert prepend_persona(system, placeholder) is system


def test_comment_only_context_block_is_blank():
    proj = "<!-- Project context. Empty ⇒ no extra context added. -->"
    mem = "<!-- Agent memory. Empty by default. -->"
    assert build_context_block(proj, mem) == ""


def test_comment_stripped_but_real_text_kept():
    # A file with a leading comment AND real content injects only the real content.
    out = prepend_persona("SYS", "<!-- note -->\nTone: ngắn gọn.")
    assert "note" not in out  # comment stripped
    assert "Tone: ngắn gọn." in out and out.endswith("SYS")
