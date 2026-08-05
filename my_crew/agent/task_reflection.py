"""Reflection on a finished team task (v68 P4) — distil ONE lesson about delegating.

When a team task reaches a terminal state, a small LLM turn looks back at what was
asked, who did it, and how it ended, and writes at most one durable lesson into the
COORDINATOR's own memory namespace — `(coordinator_id, "memory")`, the same
`(agent_id, "memory")` shape `memory_node` writes and `sibling_memory` reads. The
coordinator keeps its own lessons: it is the one that assigns work, so "agent X needs
sharper acceptance criteria" is a fact about how IT should delegate, not a fact about
agent X's private state. Writing into X's namespace would also breach the WO-self
boundary (`memory_node._assert_self_namespace`) — an agent writes only its own memory.

Two guardrails do the real work here, because the failure mode of a memory that learns
from failures is that it learns the WRONG thing and then hardens it into a refusal:

1. `is_durable_lesson` rejects transient/infrastructure claims. "web_search timed out"
   is true today and false tomorrow; remembering it teaches the coordinator to avoid a
   tool that works. Only claims about how to SPECIFY and ASSIGN work survive.
2. Cooldown: a task is reflected on at most once. The marker lives in the same Store —
   no new column — but in its OWN `(coordinator_id, "reflected")` namespace, deliberately
   NOT alongside the lessons. Markers are written on every reflection while lessons are
   rare, so mixing them would bury real facts among bookkeeping rows for the three
   components that read `(agent_id, "memory")`: sibling agents' prompt injection
   (`sibling_memory`), the CEO's memory view (`visualize_views`, which would render each
   marker as an empty fact), and this module's own prior-lesson lookup. Keeping markers
   out also keeps them clear of the 90-day retention sweep over `memory_facts`
   (`storage_hygiene`), which would otherwise expire a cooldown and let a long-lived
   stalled task be re-reflected on.

   The check-then-act across the LLM call is not atomic: two ticks that both read a task
   before its terminal transition could each pay for one reflection. The terminal
   `set_task_status` runs before reflection and drops the task out of
   `list_dispatchable`, so this needs a genuine overlap to happen, and the cost is one
   duplicate call whose lesson collapses onto the same content hash — bounded, not a
   correctness break.

Cost rides the monthly cap already enforced inside `LlmClient.complete()`
(`BudgetTracker`) — reflection is bookkeeping, not the task's own work, so it is
deliberately NOT folded into the task's per-task cost cap.

Nothing here may raise into the ticker. `run_one_tick` has no except of its own, so a
reflection failure would take down a tick that otherwise did real work. The `reflect`
collaborator on `CoordinatorDeps` is hygiene — never the tick's fate.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

# `_NAMESPACE_KIND` is imported rather than re-spelled so there is ONE definition of the
# `(agent_id, "memory")` shape across the codebase.
from my_crew.agent.memory_node import _NAMESPACE_KIND

logger = logging.getLogger(__name__)

#: A lesson longer than this is a summary, not a lesson — the point is one durable line
#: the next decomposition can actually act on.
MAX_LESSON_CHARS = 240

#: The model says exactly this when the task taught nothing worth keeping. Most tasks
#: do: "it went fine" is not a lesson, and a memory that records every success drowns
#: the few entries that would change a future decision.
NOTHING_TOKEN = "KHONG_CO_GI"

#: Claims that are true only right now. A lesson mentioning any of these describes an
#: incident, not a way of working, and remembering it would teach the coordinator to
#: route around infrastructure that has since recovered.
#:
#: Written WITHOUT Vietnamese diacritics and matched against a `_fold`ed string. Models
#: asked for one short Vietnamese line emit accented and unaccented text unpredictably,
#: and a guardrail protecting durable shared memory must not depend on the model's
#: typography — an accent-sensitive pattern set fails OPEN, which is the wrong direction.
_TRANSIENT_PATTERNS = (
    r"\btimed?\s*out\b", r"\btimeout\b", r"\bqua han\b", r"\bhet gio\b",
    r"\bcrash", r"\bexception\b", r"\btraceback\b", r"\bstack ?trace\b",
    r"\b5\d{2}\b", r"\b429\b", r"\brate.?limit", r"\bqua tai\b", r"\bover ?load",
    r"\bmang\b", r"\bnetwork\b", r"\bconnection\b", r"\bket noi\b", r"\bchap chon\b",
    r"\bapi key\b", r"\bhet token\b", r"\bhet quota\b", r"\bquota\b",
    r"\bbi loi\b", r"\bloi he thong\b", r"\bhong\b", r"\bbroken\b", r"\bbug\b",
    r"\bkhong chay duoc\b", r"\bdown\b", r"\bunavailable\b", r"\bkhong kha dung\b",
    r"\bthat bai\b", r"\bsu co\b", r"\bgian doan\b",
)

#: Named tools/infrastructure. "tool X is unreliable" is the exact claim the Hermes
#: background-review write-up saw harden into a blanket refusal to use X.
_TOOL_PATTERNS = (
    r"\bweb_search\b", r"\bsearch tool\b", r"\bcong cu tim kiem\b",
    r"\bllm\b", r"\bmodel\b", r"\bmo hinh\b", r"\bopenrouter\b", r"\btelegram\b",
    r"\bsqlite\b", r"\bdatabase\b", r"\bco so du lieu\b", r"\bserver\b", r"\bmay chu\b",
)

#: "Never do X again" / "always avoid Y" — the blanket-refusal SHAPE, independent of what
#: X is. Checked on its own rather than only alongside a tool name, because the same shape
#: aimed at a teammate ("đừng bao giờ giao việc phân tích cho agent-b") is worse than one
#: aimed at a tool: it becomes a permanent, unreviewable hiring freeze on a colleague,
#: learned from a single stall that may well have been a one-off.
_BLANKET_REFUSAL_PATTERNS = (
    r"\bkhong bao gio\b", r"\bdung bao gio\b", r"\btuyet doi khong\b",
    r"\bnever\b", r"\balways avoid\b", r"\bkhong nen giao\b", r"\bdung giao\b",
    r"\btranh giao\b", r"\bkhong giao\b", r"\bthoi giao\b",
)

#: Words that turn a mention into a complaint.
# Accent-folding collapses Vietnamese `đừng` ("don't") and `dùng` ("use") onto the same
# token `dung`, so a bare `\bdung\b` reads "nên dùng web_search" as a complaint about
# web_search. `đừng` is a negator and always precedes a verb; `dùng` precedes its object.
# Match the negator only in its verb pairs, and keep the standalone token out.
_COMPLAINT_RE = (
    r"\bkhong\b|\btranh\b|\bdung (giao|dung|de|cho|lam)\b"
    r"|\bavoid\b|\bnever\b|\bunreliable\b|\bkem\b|\bte\b"
)


def _fold(text: str) -> str:
    """Casefold + strip Vietnamese diacritics, so matching sees `bi loi` and `bị lỗi`
    identically. NFD splits each accented char into base + combining mark; dropping the
    marks (Unicode category Mn) leaves the ASCII skeleton the patterns are written against."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    # Vietnamese đ/Đ carries no combining mark — NFD leaves it intact, so map it by hand.
    return stripped.replace("đ", "d")


def is_durable_lesson(text: str) -> bool:
    """True iff `text` is worth remembering forever.

    Rejects the empty/nothing answers, anything over-long, any claim resting on a
    transient condition, and any blanket refusal (about a tool OR a teammate). The bar is
    deliberately high and one-directional: wrongly dropping a real lesson costs one missed
    improvement, while wrongly keeping a transient one permanently biases every future
    decomposition.
    """
    lesson = (text or "").strip()
    if not lesson or NOTHING_TOKEN in lesson:
        return False
    if len(lesson) > MAX_LESSON_CHARS:
        return False
    low = _fold(lesson)
    if any(re.search(p, low) for p in _TRANSIENT_PATTERNS):
        return False
    # "Never/always avoid X" is refused whatever X is — tool, agent, or step type.
    if any(re.search(p, low) for p in _BLANKET_REFUSAL_PATTERNS):
        return False
    # A tool name alone is fine ("dùng web_search trước khi giao bước phân tích"); a tool
    # name in a sentence that also complains is the harden-into-refusal shape.
    if any(re.search(p, low) for p in _TOOL_PATTERNS) and re.search(_COMPLAINT_RE, low):
        return False
    return True


#: Cooldown markers live here, NOT in the `"memory"` namespace — see the module docstring.
_MARKER_NAMESPACE_KIND = "reflected"


def _reflected_key(task_id: str, generation: int = 0) -> str:
    """Cooldown marker key — one per task GENERATION, not one per task forever.

    `generation` is the task's `reopen_count`: how many times a CEO `retry_stalled_step`
    brought it back from `stalled`. A stall that happens AFTER a retry is the most
    informative one there is — the first fix demonstrably did not work — so it must not
    be swallowed as "already looked at". Each revival costs one extra reflection call,
    which is the price of hearing about the second failure at all.
    """
    return f"reflected:{task_id}" if not generation else f"reflected:{task_id}:{generation}"


def _task_digest(task: Any, outcome: str, detail: str) -> str:
    """What the model looks back at: the ask, who held each step, and how it ended.

    Step RESULT text is deliberately NOT included. Results are attacker-influenced
    content (a step may echo an injection absorbed from a web search), and this turn's
    output is written to durable memory that every sibling can read — the highest-value
    injection target in the system. Titles, assignees and statuses are all structural
    fields the CEO or the coordinator itself authored, so the prompt stays on data that
    a step's output cannot rewrite.

    That last claim is an ASSUMPTION about `step.title` specifically, worth restating
    because it is the field most likely to drift: fan-out and review/rework steps have
    system-minted titles derived from a parent's CEO-authored title. If a future fan-out
    ever lets a step PROPOSE its children's titles from its own output, attacker-influenced
    text would reach this prompt without anything in this module changing.
    """
    lines = [f"Việc: {task.title}", f"Kết thúc: {outcome}" + (f" ({detail})" if detail else "")]
    for step in sorted(task.steps, key=lambda s: s.seq):
        lines.append(f"- [{step.status}] {step.title} → {step.assigned_to or '?'}")
    return "\n".join(lines)


def _build_prompt(digest: str, prior: list[str]) -> str:
    """The decision rule goes FIRST: a rule buried under the data gets ignored (v66)."""
    prior_block = ""
    if prior:
        prior_block = (
            "\nBÀI HỌC ĐÃ CÓ (nếu điều rút ra trùng ý, hãy viết lại bản gộp rõ hơn "
            "thay vì thêm dòng mới):\n" + "\n".join(f"- {p}" for p in prior[:10]) + "\n"
        )
    return (
        "QUY TẮC (đọc trước):\n"
        f"1. Nếu việc này không dạy được gì về CÁCH GIAO VIỆC, trả lời đúng: {NOTHING_TOKEN}. "
        "Đây là câu trả lời đúng cho phần lớn việc — đừng cố nặn ra bài học.\n"
        "2. TUYỆT ĐỐI không rút bài học từ lỗi nhất thời hay hạ tầng (timeout, mạng, "
        "công cụ hỏng, quá tải). Những cái đó mai lại khác.\n"
        "3. Chỉ rút bài học về cách MÔ TẢ và GIAO việc: tiêu chí nghiệm thu, chia bước, "
        "thứ tự phụ thuộc, cần nêu rõ đầu ra gì.\n"
        "4. KHÔNG kết luận về năng lực của ai, không viết kiểu 'đừng giao cho X nữa'. "
        "Một lần hỏng không đủ để kết luận về người — hãy nói cần mô tả việc rõ hơn "
        "thế nào.\n"
        "5. Viết MỘT câu tiếng Việt, tối đa 200 ký tự. Không giải thích thêm.\n"
        f"{prior_block}\n"
        "DỮ LIỆU:\n"
        f"{digest}"
    )


def make_reflect(coordinator_id: str, settings: Any, store: Any = None):
    """Build the `reflect(task, outcome, detail)` collaborator for `CoordinatorDeps`.

    `store` is injected for tests; production passes None and gets the settings-selected
    Store (the same shared file `memory_node` writes). Returns a callable that NEVER
    raises — see the module docstring.
    """

    def _reflect(task: Any, outcome: str, detail: str = "") -> None:
        try:
            _reflect_inner(coordinator_id, settings, store, task, outcome, detail)
        except Exception:  # noqa: BLE001 — hygiene must never be the tick's fate
            logger.warning(
                "team-tick: reflection failed for task %s (bỏ qua)",
                getattr(task, "id", "?"), exc_info=True,
            )

    return _reflect


def _reflect_inner(
    coordinator_id: str, settings: Any, store: Any, task: Any, outcome: str, detail: str
) -> None:
    if not coordinator_id:
        return
    if store is None:
        from my_crew.agent.store import get_store

        store = get_store(settings)

    namespace = (coordinator_id, _NAMESPACE_KIND)
    marker_ns = (coordinator_id, _MARKER_NAMESPACE_KIND)
    # Cooldown BEFORE the LLM call — the whole point is to not re-spend on a task the
    # ticker re-reads (a stalled task stays in the store, and a later sweep may re-touch
    # it).
    marker = _reflected_key(task.id, int(getattr(task, "reopen_count", 0) or 0))
    if store.get(marker_ns, marker) is not None:
        return

    if not getattr(settings, "openrouter_api_key", ""):
        return  # no key ⇒ no reflection; the tick's own work already happened

    prior = _prior_lessons(store, namespace)
    prompt = _build_prompt(_task_digest(task, outcome, detail), prior)

    from my_crew.llm.client import LlmClient

    # The monthly budget cap is supreme: `LlmClient.complete` raises BudgetExceededError
    # through BudgetTracker, and the outer `_reflect` turns that into a skipped
    # reflection rather than a failed tick.
    result = LlmClient(settings).complete([{"role": "user", "content": prompt}])
    lesson = (result.content or "").strip()

    ts = datetime.now(UTC).isoformat()
    # The marker is written whether or not a lesson survived: "we already looked at this
    # task and it taught nothing" is exactly as worth remembering as the lesson, and
    # without it every future tick would pay for the same negative answer again.
    store.put(marker_ns, marker, {"task_id": task.id, "outcome": outcome, "ts": ts})

    if not is_durable_lesson(lesson):
        logger.info("team-tick: reflection on task %s gave nothing durable", task.id)
        return

    # Same content-hash keying as `memory_node`, so an identical lesson learned from two
    # different tasks collapses into one entry instead of accumulating duplicates.
    key = hashlib.sha256(lesson.encode("utf-8")).hexdigest()[:16]
    store.put(namespace, key, {"fact": lesson, "ts": ts})
    logger.info("team-tick: lesson học được từ task %s: %s", task.id, lesson[:120])


def _prior_lessons(store: Any, namespace: tuple[str, str]) -> list[str]:
    """Existing facts, so the prompt can prefer rewriting one over piling on a new line."""
    try:
        items = store.search(namespace, limit=20)
    except Exception:  # noqa: BLE001 — a search failure must not block writing a lesson
        return []
    out: list[str] = []
    for item in items:
        value = getattr(item, "value", None) or {}
        fact = value.get("fact")
        if fact:
            out.append(str(fact))
    return out
