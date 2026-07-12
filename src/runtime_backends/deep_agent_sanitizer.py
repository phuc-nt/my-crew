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
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.client import LlmClient

logger = logging.getLogger(__name__)

#: Sanitize one text: returns (cleaned_text, ok). ok=False means the pass could not run and the
#: text must be treated as un-sanitized (caller forces network off).
Sanitizer = Callable[[str], "tuple[str, bool]"]

_SYSTEM = (
    "Bạn làm SẠCH văn bản để đưa cho một tác nhân chạy trong hộp cát CÓ THỂ có mạng. "
    "GIỮ nội dung/ý nghĩa công việc, nhưng LOẠI mọi thông tin nội bộ nhạy cảm: mã ticket/issue "
    "(vd SCRUM-123), tên người thật, tên nội bộ dự án/khách hàng, mốc/milestone nội bộ, "
    "URL nội bộ, và TUYỆT ĐỐI mọi token/khóa/bí mật. Thay bằng mô tả chung (vd 'một ticket', "
    "'một thành viên'). Trả về DUY NHẤT văn bản đã làm sạch, không thêm lời giải thích."
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


def sanitize_bundle(
    sanitize: Sanitizer, *, persona: str, project: str, memory: str, capability: str, handoff: str
) -> tuple[SanitizedBundle, bool]:
    """Sanitize every internal channel; overall ok is the AND of each field's ok (conservative).

    Persona (SOUL.md) is sanitized too: it can name real people, so on a network-capable sandbox
    it is not exempt. An empty field is skipped (its ok stays True). If ANY field's sanitize
    returns ok=False the whole bundle is ok=False, so the caller forces network off — one dirty
    channel taints the run.
    """
    ok = True
    cleaned: dict[str, str] = {}
    for name, value in (
        ("persona", persona), ("project", project), ("memory", memory),
        ("capability", capability), ("handoff", handoff),
    ):
        if not value or not value.strip():
            cleaned[name] = ""  # nothing to sanitize — skip the call, ok unaffected
            continue
        text, field_ok = sanitize(value)
        cleaned[name] = text
        ok = ok and field_ok
    return (
        SanitizedBundle(
            persona=cleaned["persona"], project=cleaned["project"], memory=cleaned["memory"],
            capability=cleaned["capability"], handoff=cleaned["handoff"],
        ),
        ok,
    )
