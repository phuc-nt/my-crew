"""Sanitize a deep_agent's input before it enters a network-capable sandbox.

A deep_agent runs shell freely inside its sandbox. If that sandbox has network (opt-in), any
internal company data that reached the agent's prompt could be POSTed out. That data arrives on
TWO channels: the profile context (project/memory/capability) AND the handoff string — and the
handoff is the sharper leak, because it carries upstream steps' results (produced by fully-
grounded tool-calling agents) plus colleague-consult answers drawn from raw SOUL.md/PROJECT.md.

Rather than withhold that grounding (which would blunt the deep_agent), the input is SANITIZED
at the source: an LLM pass rewrites each channel to remove internal-sensitive tokens (issue keys,
person names, internal milestones, secrets) while keeping the substance, so the deep_agent runs
at full power on a cleaned brief. The sanitizer is the trust boundary that makes a network-on
deep_agent safe.

The pass can fail (LLM down/timeout). It signals that via an `ok` flag rather than silently
passing raw text through — and the caller responds by forcing the sandbox network OFF, so
un-sanitized data can never reach a networked sandbox. `ok=False` is the fail-closed signal.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.llm.client import LlmClient

logger = logging.getLogger(__name__)

#: Sanitize one text: returns (cleaned_text, ok). ok=False means the pass could not run and the
#: text must be treated as un-sanitized (caller forces network off).
Sanitizer = Callable[[str], "tuple[str, bool]"]

_SYSTEM = (
    "Bạn làm SẠCH văn bản để đưa cho một tác nhân chạy trong hộp cát CÓ THỂ có mạng. "
    "GIỮ nội dung/ý nghĩa công việc, nhưng LOẠI mọi thông tin nội bộ nhạy cảm: mã ticket/issue "
    "(vd SCRUM-123), tên người thật, tên nội bộ dự án/khách hàng, mốc/milestone nội bộ, "
    "URL nội bộ (domain công ty, localhost, IP nội bộ), và TUYỆT ĐỐI mọi token/khóa/bí mật. "
    "Thay bằng mô tả chung (vd 'một ticket', 'một thành viên'). QUAN TRỌNG: URL CÔNG KHAI "
    "(https:// đến trang web công cộng — báo chí, tài liệu vendor, nguồn trích dẫn) KHÔNG "
    "phải thông tin nội bộ — PHẢI GIỮ NGUYÊN VẸN từng ký tự, vì bước sau cần chúng làm "
    "trích dẫn nguồn. Số liệu, bảng, và chi tiết kết quả các bước trước cũng GIỮ NGUYÊN. "
    "Văn bản gồm nhiều PHẦN, mỗi phần mở đầu bằng một dòng đánh dấu dạng "
    "===KENH:tên=== — GIỮ NGUYÊN VẸN từng dòng đánh dấu đó (không thêm, không bớt, "
    "không đổi tên) để hệ thống tách lại đúng phần. "
    "Trả về DUY NHẤT văn bản đã làm sạch, không thêm lời giải thích."
)


@dataclass(frozen=True)
class SanitizedBundle:
    """The deep_agent's internal input channels after sanitization."""

    persona: str
    project: str
    memory: str
    capability: str
    handoff: str


def make_llm_sanitizer(client: LlmClient) -> Sanitizer:
    """Default sanitizer: ask the LLM to redact internal-sensitive tokens from one text.

    Returns `(cleaned, True)` on success, `("", False)` on any failure — an empty string plus the
    fail signal, never the raw input (which would defeat the point on the failure path).
    """

    def _sanitize(text: str) -> tuple[str, bool]:
        if not text or not text.strip():
            return "", True  # nothing to clean; not a failure
        try:
            result = client.complete(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ]
            )
            return result.content, True
        except Exception as exc:  # noqa: BLE001 — a failed pass must fail closed, not pass raw
            logger.warning("deep_agent input sanitize failed (forcing network off): %s", exc)
            return "", False

    return _sanitize


#: Section marker for the batched sanitize call. Charset deliberately outside anything
#: the sanitizer is asked to rewrite; the LLM is instructed to keep these lines verbatim.
_SECTION = "===KENH:{name}==="
_SECTION_RE = re.compile(r"^===KENH:([a-z]+)===$", re.MULTILINE)


def sanitize_bundle(
    sanitize: Sanitizer, *, persona: str, project: str, memory: str, capability: str, handoff: str
) -> tuple[SanitizedBundle, bool]:
    """Sanitize the internal channels in ONE pass; conservative ok semantics unchanged.

    Persona (SOUL.md) is sanitized too: it can name real people, so on a network-capable
    sandbox it is not exempt. Empty fields are skipped. The five per-field LLM calls
    (measured: the dominant fixed cost of every network-on deep step) are batched into a
    single call over a section-delimited payload; the cleaned text is split back on the
    same markers. ANY integrity failure — sanitizer ok=False, a marker lost or renamed by
    the model — fails CLOSED exactly like a per-field failure did: empty bundle, ok=False,
    caller forces network off.
    """
    fields = {
        "persona": persona or "", "project": project or "", "memory": memory or "",
        "capability": capability or "", "handoff": handoff or "",
    }
    non_empty = {k: v for k, v in fields.items() if v.strip()}
    empty_bundle = SanitizedBundle(persona="", project="", memory="", capability="", handoff="")
    if not non_empty:
        return empty_bundle, True  # nothing to sanitize — not a failure

    # A field's own content must never be able to FORGE a marker: a hostile handoff
    # embedding "===KENH:persona===" would otherwise smuggle attacker text into the
    # persona slot (which `prepend_persona` renders into the SYSTEM prompt). Defused
    # by breaking the marker charset inside values before the payload is built.
    def _defuse(value: str) -> str:
        return value.replace("===KENH:", "=== KENH:")

    payload = "\n".join(
        f"{_SECTION.format(name=name)}\n{_defuse(value)}" for name, value in non_empty.items()
    )
    cleaned_text, call_ok = sanitize(payload)
    if not call_ok:
        return empty_bundle, False

    # Split the cleaned text back on the markers; any mismatch with what was sent in
    # (missing/extra/renamed/DUPLICATED section) means the structure was damaged —
    # treat it exactly like a failed pass rather than guessing which text belongs where.
    parts: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(cleaned_text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned_text)
        parts[m.group(1)] = cleaned_text[m.end():end].strip("\n")
    if set(parts) != set(non_empty) or len(matches) != len(non_empty):
        logger.warning(
            "deep_agent sanitize: section markers damaged (%s vs %s) — failing closed",
            sorted(parts), sorted(non_empty),
        )
        return empty_bundle, False

    cleaned = {name: parts.get(name, "") for name in fields}
    return (
        SanitizedBundle(
            persona=cleaned["persona"], project=cleaned["project"], memory=cleaned["memory"],
            capability=cleaned["capability"], handoff=cleaned["handoff"],
        ),
        True,
    )
