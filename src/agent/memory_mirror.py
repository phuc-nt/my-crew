"""MEMORY.md agent-section mirror (v2 M2-P8 Slice 3).

The agent's extracted memory facts are mirrored into the HUMAN-readable MEMORY.md so an
operator can see (and edit) what the agent remembered. To never clobber human-authored
content, the agent writes ONLY between two markers:

    <!-- AGENT-MEMORY:START -->
    ... agent facts, one per line ...
    <!-- AGENT-MEMORY:END -->

Everything outside the markers (human content above/below) is preserved verbatim. The
core `rewrite_agent_section` is a PURE function (existing text + facts → new text) so it
is fully unit-testable; `write_memory_file` adds the read + atomic temp-and-rename.
"""

from __future__ import annotations

import os
from pathlib import Path

START = "<!-- AGENT-MEMORY:START -->"
END = "<!-- AGENT-MEMORY:END -->"
DEFAULT_CAP = 50  # keep at most the last N agent facts (bounds MEMORY.md growth)


def rewrite_agent_section(existing: str, facts: list[str], *, cap: int = DEFAULT_CAP) -> str:
    """Return `existing` with the agent-memory section updated to hold (prior + new) facts.

    Pure. Preserves all content outside the markers byte-for-byte. There is ALWAYS
    exactly one marker pair afterward: if a well-formed pair exists it is replaced
    in place; if the markers are absent OR malformed (only one present, or END before
    START), the agent block is (re)built at the end and any stray marker lines are
    stripped so the file never accumulates duplicate markers. New facts are appended
    after any prior agent facts, deduped (order-preserving), trimmed to the last `cap`.
    """
    before, prior_facts, after = _split(existing)
    merged = _dedupe(prior_facts + [f.strip() for f in facts if f.strip()])
    kept = merged[-cap:] if cap and len(merged) > cap else merged
    block = "\n".join([START, *kept, END])
    if before is None:
        # No well-formed pair: strip any stray marker lines (malformed/duplicate state),
        # then append a single fresh block. Never appends a SECOND marker pair.
        base = _strip_marker_lines(existing).rstrip("\n")
        return f"{base}\n\n{block}\n" if base else f"{block}\n"
    return f"{before}{block}{after}"


def write_memory_file(path: Path, facts: list[str], *, cap: int = DEFAULT_CAP) -> None:
    """Read MEMORY.md, rewrite the agent section with `facts`, write atomically.

    Atomic = write a temp file in the same dir then `os.replace` it over the target, so
    a crash mid-write never leaves a half-written MEMORY.md.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    new = rewrite_agent_section(existing, facts, cap=cap)
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid-suffixed temp so two concurrent writers don't share one .tmp (torn file).
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, path)


def _split(text: str) -> tuple[str | None, list[str], str]:
    """Split a well-formed file into (before, [agent facts], after).

    `before` is everything strictly BEFORE the START marker (+ a newline); `after` is
    everything strictly AFTER the END marker. Neither includes a marker — the caller
    re-adds exactly one pair via `block`, so markers never double. Returns
    (None, [], "") when there is no well-formed pair (absent or malformed: only one
    marker, or END before START, or a duplicate START before the first END).
    """
    s = text.find(START)
    e = text.find(END)
    if s == -1 or e == -1 or e < s:
        return None, [], ""
    inner = text[s + len(START) : e]
    # A second START inside the region ⇒ the file is in a doubled/malformed state;
    # treat as no-pair so rewrite normalizes to a single clean block.
    if START in inner:
        return None, [], ""
    before = text[:s] + "\n" if text[:s] and not text[:s].endswith("\n") else text[:s]
    after = text[e + len(END) :]
    facts = [ln for ln in inner.strip("\n").splitlines() if ln.strip()]
    return before, facts, after


def _strip_marker_lines(text: str) -> str:
    """Remove any lines that are exactly a START/END marker (cleanup of a malformed file)."""
    return "\n".join(ln for ln in text.splitlines() if ln.strip() not in (START, END))


def _dedupe(facts: list[str]) -> list[str]:
    """Order-preserving dedupe — identical facts collapse, keeping the FIRST occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for f in facts:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out
