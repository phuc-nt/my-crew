"""Clarify service (v33 P4) — the ONE door between "agent wants to ask the CEO" and
the store/notify plumbing. The LLM never writes a clarification row itself: the work
node calls `ask_ceo(...)` (a deps seam), which sanitizes, caps, stores, and notifies.

Sanitize-at-source (v27 posture): the question/options come from an LLM, and they get
rendered in the CEO's Telegram and web UI — control characters are stripped and
lengths bounded HERE, before storage, so every downstream surface reads a clean row.

Notification rides the admin ops agent's own Action Gateway (`operator_notify`) with
inline answer buttons — one bot, one CEO chat, fully audited. No admin ops agent (or
no Telegram) simply degrades to web-only: the question still shows in Duyệt.
"""

from __future__ import annotations

import logging
import re

from src.runtime.clarify_store import (
    ClarifyCapError,
    ClarifyStore,
    Clarification,
)
from src.runtime.team_task_paths import clarify_db_path

logger = logging.getLogger(__name__)

_QUESTION_MAX = 400
_OPTION_MAX = 80
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
#: Callback payload shape shared with the Telegram inbox parser: clarify:<id>:<n>.
CALLBACK_PREFIX = "clarify:"


def _clean(text: str, cap: int) -> str:
    return _CTRL_RE.sub("", " ".join(str(text).split()))[:cap]


def ask_ceo(
    *, agent_id: str, task_id: str, question: str, options: list[str] | None = None,
) -> tuple[str, int | None]:
    """Record a CEO question + notify. Returns `(note, clarify_id)` — the note is what
    the asking step folds into its own context; the id (None on refusal/failure) is
    what v34's interrupt path pauses on. NEVER raises (a clarify hiccup must not fail
    the step)."""
    q = _clean(question, _QUESTION_MAX)
    if not q:
        return "", None
    opts = [o for o in (_clean(o, _OPTION_MAX) for o in (options or [])) if o]
    store = ClarifyStore(clarify_db_path())
    try:
        clarify_id = store.create_question(
            agent_id=agent_id, task_id=task_id, question=q, options=opts,
        )
    except ClarifyCapError as exc:
        logger.warning("clarify refused: %s", exc)
        return ("Không gửi được câu hỏi cho CEO (đã có quá nhiều câu hỏi chờ) — "
                "tự quyết theo phương án an toàn nhất.", None)
    except Exception:  # noqa: BLE001 — a broken queue must not fail the step
        logger.warning("clarify store failed", exc_info=True)
        return "", None
    finally:
        store.close()

    _notify(clarify_id, agent_id, q, opts)
    return (f"Đã gửi câu hỏi cho CEO (mã #{clarify_id}). Làm tiếp phần còn lại theo "
            f"phương án an toàn nhất; câu trả lời của CEO sẽ được đưa vào bước sau.",
            clarify_id)


def _notify(clarify_id: int, agent_id: str, question: str, options: list[str]) -> None:
    from src.runtime.operator_notify import notify_operator_best_effort

    lines = [f"❓ [{agent_id}] hỏi: {question}"]
    buttons = [
        {"text": opt, "callback_data": f"{CALLBACK_PREFIX}{clarify_id}:{i}"}
        for i, opt in enumerate(options)
    ]
    if not buttons:
        lines.append("Trả lời trong mục Duyệt trên web.")
    else:
        lines.append("Bấm một lựa chọn, hoặc trả lời chi tiết trong mục Duyệt trên web.")
    notify_operator_best_effort(
        "\n".join(lines),
        dedup_hint=f"clarify-{clarify_id}",
        rationale="agent hỏi CEO — cần làm rõ để tiếp tục việc",
        buttons=buttons or None,
    )


def apply_answer(clarify_id: int, answer: str) -> bool:
    """First-answer-wins. Returns True iff this call landed the answer."""
    text = _clean(answer, _QUESTION_MAX)
    if not text:
        return False
    store = ClarifyStore(clarify_db_path())
    try:
        return store.apply_answer(clarify_id, text)
    finally:
        store.close()


def answer_from_callback(data: str) -> tuple[bool, str]:
    """Handle a Telegram button tap: `clarify:<id>:<n>` → apply that option.

    Returns (landed, toast_text). Unknown/expired/answered ids and malformed data all
    read as a polite already-handled toast — the inbox never errors on a tap."""
    m = re.fullmatch(rf"{CALLBACK_PREFIX}(\d+):(\d+)", data or "")
    if not m:
        return False, "Nút không hợp lệ."
    clarify_id, idx = int(m.group(1)), int(m.group(2))
    store = ClarifyStore(clarify_db_path())
    try:
        row = store.get(clarify_id)
        if row is None or idx >= len(row.options):
            return False, "Câu hỏi không còn tồn tại."
        if row.status != "pending":
            return False, "Câu hỏi này đã được trả lời/hết hạn."
        landed = store.apply_answer(clarify_id, row.options[idx])
        return landed, ("Đã ghi nhận: " + row.options[idx] if landed
                        else "Câu hỏi này vừa được trả lời ở nơi khác.")
    finally:
        store.close()


def clarify_status(clarify_id: int) -> tuple[str, str] | None:
    """(status, answer) of one question, or None if it does not exist — the ticker's
    poll seam for resuming a `waiting_clarify` step (mirror of `approval_status`)."""
    try:
        store = ClarifyStore(clarify_db_path())
        try:
            row = store.get(int(clarify_id))
        finally:
            store.close()
    except Exception:  # noqa: BLE001 — an unreadable queue reads as "unknown"
        logger.warning("clarify status read failed", exc_info=True)
        return None
    if row is None:
        return None
    return row.status, row.answer


def expire_sweep() -> int:
    """Ticker hook: flip overdue questions to expired. Best-effort, returns count."""
    try:
        store = ClarifyStore(clarify_db_path())
        try:
            n = store.expire_due()
        finally:
            store.close()
        if n:
            logger.info("clarify: %d câu hỏi quá hạn đã chuyển expired", n)
        return n
    except Exception:  # noqa: BLE001 — sweep must never break the tick
        logger.warning("clarify expire sweep failed", exc_info=True)
        return 0


def answered_context_for_task(task_id: str) -> str:
    """Answered Q&A of a task, rendered for the NEXT step's handoff context. "" when
    none. Bounded by the store's own limit (5 most recent)."""
    try:
        store = ClarifyStore(clarify_db_path())
        try:
            rows: list[Clarification] = store.answered_for_task(task_id)
        finally:
            store.close()
    except Exception:  # noqa: BLE001 — context enrichment is best-effort
        logger.warning("clarify context read failed", exc_info=True)
        return ""
    if not rows:
        return ""
    lines = [f"- Hỏi: {r.question} → CEO trả lời: {r.answer}" for r in reversed(rows)]
    return "[CEO đã trả lời các câu hỏi của đội]\n" + "\n".join(lines)
