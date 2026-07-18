"""Two-way form ↔ markdown for SOUL.md / PROJECT.md (v7 M18b).

The CEO edits a small FORM (a few labelled fields) instead of raw markdown. Each field is
rendered into the .md between HTML-comment markers so the file can be parsed back INTO the
form on the next load — a genuine round-trip, not a one-way generate.

If the operator edits the raw markdown by hand and breaks the markers, the parse fails
gracefully: `parse` returns `raw_mode=True` and the UI shows "đang ở chế độ nâng cao" (edit
raw), never silently overwriting hand-written prose.

Markers look like:  <!-- field:tone -->\n...text...\n<!-- /field:tone -->
Only known field keys are emitted/parsed; unknown markers are left untouched on re-render
of a raw-mode file (we simply don't touch a file we couldn't fully parse).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The form fields per document. (key, label, multiline?) — order = render order.
SOUL_FIELDS = [
    ("role", "Vai trò của agent (1 câu)", False),
    ("tone", "Giọng điệu khi trả lời", False),
    ("rules", "Quy tắc riêng (mỗi dòng một ý)", True),
]
PROJECT_FIELDS = [
    ("team", "Thành viên đội + vai trò", True),
    ("conventions", "Quy ước (nhãn, quy trình…)", True),
    ("notes", "Ghi chú khác", True),
]

_FIELDS = {"soul": SOUL_FIELDS, "project": PROJECT_FIELDS}
_TITLE = {"soul": "# SOUL", "project": "# PROJECT"}

#: The recognized field-key set per doc — callers use this to tell a genuine (all-keys) form
#: submit from an empty/keyless one that would blank the file.
FIELD_KEYS = {doc: frozenset(k for k, _, _ in fs) for doc, fs in _FIELDS.items()}


class MarkerInValueError(ValueError):
    """A field value contains our HTML-comment marker syntax, so it can't be stored in a form
    without corrupting the round-trip. Raised by `render` so the PUT boundary fails LOUD
    instead of silently truncating the value on the next parse (see the round-trip contract)."""


@dataclass(frozen=True)
class ParsedKnowledge:
    raw_mode: bool  # True ⇒ markers absent/broken; the form can't safely represent this file
    fields: dict[str, str]  # empty when raw_mode
    raw: str  # the file text as-is (always available for the raw editor)


#: Any occurrence of our marker comment inside a VALUE breaks the round-trip (the parser would
#: match the injected close tag and drop the rest). We forbid it rather than escape, since the
#: values are short human prose — a literal `<!-- field:x -->` in them is a red flag, not data.
_MARKER_RE = re.compile(r"<!--\s*/?\s*field:", re.IGNORECASE)


def _marker_open(key: str) -> str:
    return f"<!-- field:{key} -->"


def _marker_close(key: str) -> str:
    return f"<!-- /field:{key} -->"


def render(doc: str, fields: dict[str, str]) -> str:
    """Form fields → marker-wrapped markdown for `doc` in {'soul','project'}.

    Raises MarkerInValueError if any value embeds our marker syntax (would break the
    round-trip). A final render→parse self-check asserts the result is losslessly
    parseable — corruption fails loud here rather than silently on the next read.
    """
    if doc not in _FIELDS:
        raise ValueError(f"unknown knowledge doc {doc!r}")
    parts = [_TITLE[doc], ""]
    out_fields: dict[str, str] = {}
    for key, label, _multiline in _FIELDS[doc]:
        value = (fields.get(key) or "").strip()
        if _MARKER_RE.search(value):
            raise MarkerInValueError(
                f"Trường '{label}' chứa cú pháp đánh dấu nội bộ (<!-- field:… -->) — "
                f"không lưu được ở dạng form. Bỏ đoạn đó hoặc dùng chế độ nâng cao (raw)."
            )
        out_fields[key] = value
        parts.append(_marker_open(key))
        parts.append(f"## {label}")
        parts.append(value)
        parts.append(_marker_close(key))
        parts.append("")
    text = "\n".join(parts).rstrip() + "\n"
    # Self-check: the file we just built MUST parse back to exactly these values.
    back = parse(doc, text)
    if back.raw_mode or back.fields != out_fields:
        raise MarkerInValueError("nội dung không round-trip được ở dạng form")
    return text


def parse(doc: str, text: str) -> ParsedKnowledge:
    """Marker-wrapped markdown → form fields. Missing/partial markers ⇒ raw_mode.

    A file is form-parseable only when EVERY field's markers are present (a partially
    marked file means someone hand-edited — treat the whole thing as raw to avoid guessing).
    An empty file parses to empty fields (fresh agent), NOT raw mode.
    """
    if doc not in _FIELDS:
        raise ValueError(f"unknown knowledge doc {doc!r}")
    if not text.strip():
        return ParsedKnowledge(raw_mode=False, fields={k: "" for k, _, _ in _FIELDS[doc]},
                               raw=text)
    fields: dict[str, str] = {}
    for key, _label, _multiline in _FIELDS[doc]:
        m = re.search(
            re.escape(_marker_open(key)) + r"(.*?)" + re.escape(_marker_close(key)),
            text, re.DOTALL,
        )
        if m is None:
            return ParsedKnowledge(raw_mode=True, fields={}, raw=text)
        # strip the "## label" heading line the renderer added, keep the value
        block = m.group(1).strip()
        block = re.sub(r"^##[^\n]*\n?", "", block, count=1).strip()
        fields[key] = block
    return ParsedKnowledge(raw_mode=False, fields=fields, raw=text)
