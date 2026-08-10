"""v77 sprint mode: the code-paced work loop for a `step_type="sprint"` step.

Why this exists. A team task pays for its parallelism with orchestration: each step
is its own subprocess, its own perceive→work→self_check→deliver graph, its own
handoff round-trip, and (once review/rework rows are minted) several more of the
same. Measured on task 5d30f7b3303b that was 23 step rows and ~40 minutes of worker
time for a 5-step research report. For a brief ONE person could just do, all of that
is overhead paid for nothing.

The other obvious fix — hand the model a tool loop and let it drive — is the one
thing this repo has already measured and rejected: on the fleet model a react-style
synthesis step cost 780s against ~60-120s native for the same input (see
`runtime_backends/protocol.py`). So sprint mode keeps the model on the fast native
one-shot tier and moves the DECIDING into Python:

    prefetch (code)  →  draft (LLM)  →  coverage check (code)
                             ↑                     │
                             └── revise (LLM) ←────┘  ≤2 rounds

Python picks the queries, judges the coverage, and decides whether another round is
worth it. The model only writes. That bounds the whole step at ≤3 LLM calls and ≤8
searches, with no loop the model can wander inside.

This module is a `work_override` for `build_team_task_graph` — NOT a parallel runner.
`perceive`, `self_check`, `rework`, `deliver`→gateway, remember, clarify and the
checkpointer all stay exactly as they are, so every guardrail (mutation only via the
gateway, cost capture, band review policy) applies to a sprint step unchanged.

Honesty contract, same as everywhere else: a gap the searches could not fill is
REPORTED as missing, never invented and never quietly dropped. `coverage_check` is
what makes that automatic rather than a thing we ask the model to remember.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Hard ceilings for one sprint step. `MAX_REVISE_ROUNDS` bounds LLM calls at
#: 1 draft + 2 revises = 3; the search cap covers a 5-entity brief (5 entity queries
#: + 1 overview) plus one targeted round for whatever came back thin.
MAX_REVISE_ROUNDS = 2
MAX_TOTAL_QUERIES = 8
#: Queries issued before the draft. Kept under the total so a revise round always has
#: budget left — a doom-guard that fires because round 1 ate the whole allowance
#: would report gaps it never actually tried to fill.
#: Named apart from `collect_prefetch.MAX_PREFETCH_QUERIES` (3) on purpose: the two
#: modules sit side by side and cap different things — a collect step's title-derived
#: fan-out vs a sprint's per-entity round.
MAX_SPRINT_PREFETCH_QUERIES = 6

#: Sentinels `collect_prefetch` writes when a query returned nothing usable. Their
#: presence in the bundle is a COVERAGE fact (the source failed / has no public data),
#: not a defect in the draft — the check below reads them so a revise round targets
#: the entities that are genuinely still missing rather than re-asking for these.
_SOURCE_FAILED = "[LỖI NGUỒN TÌM KIẾM]"
_NO_RESULTS = "[KHÔNG CÓ KẾT QUẢ]"


def entity_queries(goal: str, acceptance: str = "") -> list[str]:
    """Search queries for a sprint goal: one per enumerated entity, plus an overview.

    Reuses `count_enumerated_entities`' notion of an entity list (colon-led,
    comma/`và`-separated, ≤7 words per item) so sprint mode and the team-mode fan-out
    rule agree on what "5 sàn: Shopee, Lazada, ..." means. A goal with no such list
    yields the goal itself — one honest query beats a fabricated decomposition.
    """
    goal = (goal or "").strip()
    if not goal:
        return []
    entities = resolve_entities(goal, acceptance)
    if not entities:
        return [goal]
    topic = _topic_phrase(goal, entities)
    queries = [f"{topic} {e}".strip() for e in entities]
    # The overview query goes LAST: per-entity results are the load-bearing ones, and
    # the total cap must never cost an entity its own search.
    return [*queries, goal][:MAX_SPRINT_PREFETCH_QUERIES]


def resolve_entities(goal: str, acceptance: str = "") -> list[str]:
    """The entities a sprint must cover: from the goal, else from a SINGLE-LINE criterion.

    The acceptance fallback exists because a CEO often names the list in the criteria
    ("Phải có: Netflix, Spotify") rather than the one-line goal. It is restricted to a
    single line for a reason found in testing: a multi-line rubric's bullets are full of
    colons introducing ATTRIBUTES, not entities — "- Nêu rõ: giá, tính năng và hỗ trợ"
    yielded ["giá", "tính năng", "hỗ trợ"], which then drove nonsense searches and three
    permanent coverage gaps no draft could ever close, ending in a THIẾU note that told
    the CEO the report was missing data it actually contained.
    """
    entities = listed_entities(goal)
    if entities:
        return entities
    text = (acceptance or "").strip()
    if not text or "\n" in text:
        return []
    return listed_entities(text)


def listed_entities(text: str) -> list[str]:
    """The enumeration in `text`, as a list of entity names.

    A PARENTHESISED list wins over a colon-led one whenever both are present. The two
    punctuations do not mean the same thing in a brief: parentheses name the SUBJECTS
    being compared, while a colon introduces the ATTRIBUTES to report on each of them.
    Benchmark 3d860be3c58b is the case that forced this — "So sánh 5 dịch vụ (Spotify,
    YouTube Music, Apple Music, Zing MP3, Nhaccuatui): giá gói cá nhân, kho nhạc Việt,
    chất lượng âm thanh" made the old longest-list rule pick the three attributes,
    because the five services were in parentheses and so were invisible to it. The
    sprint then searched for "So sánh 5 dịch vụ streaming giá gói cá nhân" instead of
    for the services, and the step died reporting it had no way to get the data.

    Same item-shape rule as `count_enumerated_entities` (which returns only the count);
    this returns the items themselves because sprint mode needs to search for each
    one and later check each one appears in the draft.
    """
    paren = _longest_enumeration(re.finditer(r"\(([^)\n]+)\)", text or ""))
    if paren:
        return paren
    return _longest_enumeration(re.finditer(r":\s*([^.\n:?!]+)", text or ""))


def _longest_enumeration(matches: Any) -> list[str]:
    """The longest comma/`và`-separated item list among `matches`, else []."""
    best: list[str] = []
    for m in matches:
        items = [
            part.strip(" .;–-")
            for chunk in m.group(1).split(",")
            for part in re.split(r"\s+và\s+", chunk)
        ]
        items = [i for i in items if i and len(i.split()) <= 7]
        if len(items) > len(best):
            best = items
    return best if len(best) >= 2 else []


#: Words that describe the ASSIGNMENT rather than its subject. A search engine is not
#: being asked to research the act of researching, so these are stripped from the topic:
#: leaving them in spends the phrase's limited length on the wrong half of the goal.
#: "giá" is deliberately ABSENT even though "đánh giá" is a task verb: standing alone it
#: is the noun "price", the actual subject of half the briefs sprint mode receives
#: ("giá dịch vụ Netflix"). "đánh" on its own is not a word any goal starts with by
#: accident, so dropping it is enough to strip the verb without eating the noun.
_TASK_VERBS = (
    "nghiên", "cứu", "so", "sánh", "khảo", "sát", "tổng", "hợp", "tra", "liệt", "kê",
    "tìm", "hiểu", "rà", "soát", "đánh", "phân", "tích", "báo", "cáo", "lập",
    "research", "survey", "compare", "compile", "summarise", "summarize", "list",
    "review", "analyse", "analyze", "report",
)

#: Where the SUBJECT of a goal stops and its per-entity ATTRIBUTES begin. Everything
#: from here on ("về giá gói cá nhân, kho nhạc Việt…") is what to report about each
#: entity, not what the entity is — see `_topic_phrase`.
_ATTRIBUTE_LEAD_INS = ("về", "gồm", "bao gồm", "kèm", "theo", "với các", "regarding", "about")


def _topic_phrase(goal: str, entities: list[str]) -> str:
    """The goal's words that belong to no entity — what a bare entity name is ABOUT.

    "Shopee" alone is an aimless query; "giá dịch vụ Shopee" is not.

    Two things are cut before the length limit applies, both learned from benchmark
    210e3686daf5. That goal — "Nghiên cứu và so sánh 5 dịch vụ streaming nhạc tại Việt
    Nam (…) về giá gói cá nhân, kho nhạc Việt…" — used to yield the topic "Nghiên cứu so
    sánh 5 dịch": six words of which five described the ASSIGNMENT, and the sixth chopped
    the subject in half. "dịch" without "vụ streaming nhạc" is not the Vietnamese for
    anything, so every per-entity query asked about comparison articles rather than about
    a music service, and the draft came back with pricing for one service out of five.

    So: leading task verbs go (nobody searches for the act of comparing), and the
    trailing attribute clause goes (those belong to the revise round's targeted queries,
    which ask them per entity anyway). What is left is the subject noun phrase, and the
    limit is applied to THAT — never cutting the head noun off its classifier.
    """
    entity_words = {w.lower().strip(",.():;") for e in entities for w in e.split()}
    words: list[str] = []
    for raw in goal.split():
        word = raw.strip(",.():;")
        # `và`/`and` are list GLUE, not topic words — with the entities stripped out
        # they would otherwise survive into every query ("So sánh 3 công cụ: và Notion").
        if not word or word.lower() in entity_words or word.lower() in ("và", "and"):
            continue
        if words and word.lower() in _ATTRIBUTE_LEAD_INS:
            break  # the subject ended; the rest is what to report ABOUT it
        words.append(word)

    # Only a LEADING run of task verbs is dropped. A later one is load-bearing vocabulary
    # ("bảng so sánh" as the deliverable), and stripping it mid-phrase would leave a hole.
    while words and words[0].lower().strip(",.():;") in _TASK_VERBS:
        words.pop(0)
    # A bare quantifier ("5 dịch vụ …") counts the very entities the query already names,
    # so it only crowds the phrase out — dropped wherever it sits, not just at the head.
    # A preposition immediately governing it ("của 5 …") goes too: once the number is
    # gone it governs nothing, and it would otherwise be left dangling mid-phrase.
    kept: list[str] = []
    for word in words:
        if word.strip(",.():;").isdigit():
            if kept and kept[-1].lower() in _QUANTIFIER_GOVERNORS:
                kept.pop()
            continue
        kept.append(word)
    return " ".join(_trimmed_to_whole_phrase(kept))


#: Prepositions whose only job in the goal was to govern a quantifier ("của 5 dịch vụ").
_QUANTIFIER_GOVERNORS = ("của", "cho", "ở", "tại", "trong", "of", "for", "among")


#: Words that cannot END a topic phrase: each one governs the word after it, so cutting
#: the phrase here strands it ("… tại Việt" for Việt Nam, "… của 5 dịch" for dịch vụ).
_DANGLING_TAIL_WORDS = (
    "tại", "ở", "của", "cho", "trong", "trên", "với", "và", "các", "những", "một",
    "dịch", "công", "nền", "sản", "thương", "hệ", "ứng", "phần", "gói", "bản",
    "in", "at", "of", "for", "the", "a", "an", "and", "on", "with",
)

#: How many words a topic phrase may carry. Six is enough to name a subject
#: ("dịch vụ streaming nhạc tại Việt Nam") without turning the query into the whole goal.
_MAX_TOPIC_WORDS = 6


def _governs_next(word: str, following: str) -> bool:
    """Would cutting between `word` and `following` strand `word`?

    Two ways it can. Either `word` is a known governor (a preposition or a classifier
    like "dịch" that means nothing without its head), or the pair is a multi-syllable
    proper noun — Vietnamese writes those as separate capitalised syllables, so "Việt"
    and "Nam" look like two words and a naive cut between them yields a phrase about
    neither. Capitalisation is the available signal, and mid-phrase is where it counts:
    a capitalised word that is not the first is either a proper noun or part of one.
    """
    bare = word.strip(",.():;")
    if bare.lower() in _DANGLING_TAIL_WORDS:
        return True
    return bool(bare[:1].isupper() and following.strip(",.():;")[:1].isupper())


def _trimmed_to_whole_phrase(words: list[str]) -> list[str]:
    """`words` cut to the length limit without severing a word from the one it governs.

    The limit exists so a per-entity query stays a query. Applying it by raw count alone
    is what produced "… tại Việt" (for Việt Nam) and "… của 5 dịch" (for dịch vụ họp
    online) on live benchmarks: a phrase severed from its head noun searches for nothing.

    Two ways out of that, and the cheaper one wins: if ONE more word finishes the phrase,
    take it — a seventh word costs nothing next to a query about "tại Việt". Only when
    the phrase runs longer than that do we back off and drop the dangling word instead.
    """
    if len(words) <= _MAX_TOPIC_WORDS:
        return words
    kept = words[:_MAX_TOPIC_WORDS]
    if _governs_next(kept[-1], words[_MAX_TOPIC_WORDS]):
        kept.append(words[_MAX_TOPIC_WORDS])
    while kept and kept[-1].lower().strip(",.():;") in _DANGLING_TAIL_WORDS:
        kept.pop()
    return kept


def coverage_gaps(draft: str, entities: list[str], bundle: str) -> list[str]:
    """Entities the draft does not cover, EXCLUDING ones the sources already refused.

    An entity whose query came back `[LỖI NGUỒN TÌM KIẾM]`/`[KHÔNG CÓ KẾT QUẢ]` is not
    a gap another search round can close — re-querying it burns budget to reach the
    same sentinel. Those stay out of the returned list so the doom-guard measures
    "gaps we can still act on", and the missing-data note tells the CEO about them.
    """
    text = (draft or "").lower()
    gaps: list[str] = []
    for entity in entities:
        name = entity.strip()
        if not name or name.lower() in text:
            continue
        if _source_refused(name, bundle, entities):
            continue
        gaps.append(name)
    return gaps


def _source_refused(entity: str, bundle: str, entities: list[str]) -> bool:
    """True when the query aimed at THIS entity came back with a failure sentinel.

    Matching on "the failed line mentions this name" is not enough. `entity_queries`
    appends an overview query that enumerates EVERY entity, so one failed overview
    would otherwise mark all of them refused — suppressing every real gap, skipping
    the revise round, and telling the CEO the sources failed when they did not. A
    sentinel line only speaks for an entity when its query names that entity ALONE.
    """
    needle = entity.lower()
    others = [e.lower() for e in entities if e.strip() and e.lower() != needle]
    for line in (bundle or "").splitlines():
        if _SOURCE_FAILED not in line and _NO_RESULTS not in line:
            continue
        query = _query_of(line)
        if not query or needle not in query:
            continue
        if any(o in query for o in others):
            continue  # a multi-entity (overview) query speaks for no single entity
        return True
    return False


def _query_of(line: str) -> str:
    """The lowercased query text out of a `(truy vấn: ...)` sentinel line, or ""."""
    if "(truy vấn:" not in line:
        return ""
    return line.split("(truy vấn:", 1)[1].split(")", 1)[0].strip().lower()


def missing_note(gaps: list[str], bundle: str) -> str:
    """The THIẾU note appended when the pipeline stops with coverage still open.

    Written as data for the CEO, not an apology: which names are missing and which of
    the two reasons applies, so "not in the report" can never be misread as "does not
    exist". Empty string when nothing is missing.
    """
    refused = [
        line.split("(truy vấn:", 1)[1].split(")", 1)[0].strip()
        for line in (bundle or "").splitlines()
        if (_SOURCE_FAILED in line or _NO_RESULTS in line) and "(truy vấn:" in line
    ]
    lines: list[str] = []
    if gaps:
        lines.append(
            "- Chưa thu thập đủ dữ liệu cho: " + ", ".join(gaps)
            + " (đã tìm nhưng không đủ kết quả dùng được)."
        )
    if refused:
        lines.append(
            "- Nguồn tìm kiếm không trả kết quả cho truy vấn: "
            + ", ".join(dict.fromkeys(refused))
            + " — ghi THIẾU do nguồn, KHÔNG kết luận là dữ liệu không tồn tại."
        )
    if not lines:
        return ""
    return "PHẦN THIẾU (do quy trình tự ghi nhận):\n" + "\n".join(lines)


def build_sprint_work(
    *,
    loaded: Any,
    settings: Any,
    context: Any = None,
    acceptance: str = "",
    telemetry: Any = None,
    prefetch: Callable[[Any, Any, list[str]], str] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> Callable[[str, str, Any], tuple[str, float | None]]:
    """Return a `work_override` callable running the sprint pipeline for one step.

    Signature matches `_run_work(title, handoff, hook) -> (text, cost)` exactly, so
    the graph cannot tell the difference: everything after `work` — self_check,
    rework, deliver→gateway — behaves as it does for a normal work step.

    `context` is the step's resolved `ProfileContext` — the SAME one native `_run_work`
    injects. Without it a sprint agent would silently lose its MEMORY.md, its skills,
    and its company docs, which is a quality regression against the very team path this
    mode replaces.

    `on_phase` is the heartbeat hook. The graph's own `on_node` callback only fires
    between NODES, and this whole pipeline is one node, so without it a long sprint
    would look dead to the lease watchdog.
    """
    from my_crew.runtime.collect_prefetch import prefetch_queries

    def _default_prefetch(loaded_: Any, settings_: Any, queries: list[str]) -> str:
        # `keep_sentinels=True`: a sprint step has no tool loop to fall back to, so a
        # total search failure must come back as the REASON it failed, not as "".
        return prefetch_queries(loaded_, settings_, queries, keep_sentinels=True)

    run_prefetch = prefetch if prefetch is not None else _default_prefetch

    def _work(title: str, handoff: str, hook: Any) -> tuple[str, float | None]:
        from my_crew.llm.client import LlmClient

        goal = (title or "").strip()
        entities = resolve_entities(goal, acceptance)
        cost = 0.0
        # Token totals across every call in the pipeline. Native `_run_work` records
        # one call's usage; a sprint step is up to three, so recording only the last
        # would under-report the step by however much the draft cost.
        tokens_in = 0
        tokens_out = 0

        def _tally(result: Any) -> None:
            nonlocal cost, tokens_in, tokens_out
            cost += float(getattr(result, "cost_usd", 0.0) or 0.0)
            tokens_in += int(getattr(result, "prompt_tokens", 0) or 0)
            tokens_out += int(getattr(result, "completion_tokens", 0) or 0)

        def _beat(phase: str) -> None:
            if on_phase is not None:
                try:
                    on_phase(phase)
                except Exception:  # noqa: BLE001 — a heartbeat must never fail the work
                    logger.warning("sprint: phase hook failed", exc_info=True)

        _beat("sprint_prefetch")
        queries = entity_queries(goal, acceptance)
        bundle = ""
        used_queries = 0
        if queries:
            try:
                bundle = run_prefetch(loaded, settings, queries)
                used_queries = len(queries)
            except Exception:  # noqa: BLE001 — same fail-open contract as the launcher
                logger.warning("sprint: prefetch failed, drafting without it", exc_info=True)
                bundle = ""

        client = LlmClient(settings)
        messages = _draft_messages(
            context=context, goal=goal, acceptance=acceptance, handoff=handoff, bundle=bundle,
        )
        _beat("sprint_draft")
        result = client.complete(messages)
        draft = str(getattr(result, "content", "") or "")
        _tally(result)

        for round_no in range(1, MAX_REVISE_ROUNDS + 1):
            _beat("sprint_check")
            gaps = coverage_gaps(draft, entities, bundle)
            if not gaps:
                break
            if used_queries >= MAX_TOTAL_QUERIES:
                logger.info("sprint: query budget spent with %d gap(s) open", len(gaps))
                break
            budget = MAX_TOTAL_QUERIES - used_queries
            extra_queries = [f"{_topic_phrase(goal, entities)} {g}".strip() for g in gaps][:budget]
            try:
                extra = run_prefetch(loaded, settings, extra_queries)
            except Exception:  # noqa: BLE001
                logger.warning("sprint: targeted search failed", exc_info=True)
                extra = ""
            used_queries += len(extra_queries)
            if not extra:
                # Nothing new came back, so a revise call would re-read the same
                # context and produce the same gaps. Stop and report them instead.
                logger.info("sprint: round %d found no new data — stopping honest", round_no)
                break
            bundle = f"{bundle}\n\n{extra}" if bundle else extra
            # Cumulative context: the draft and the new results ride in the SAME
            # thread. Re-briefing from scratch each round is what makes a team task's
            # rework rounds expensive, and there is no reason to repeat it here.
            messages = [
                *messages,
                {"role": "assistant", "content": draft},
                {"role": "user", "content": _revise_instruction(gaps)},
                {"role": "user", "content": extra},
            ]
            _beat(f"sprint_revise_{round_no}")
            result = client.complete(messages)
            revised = str(getattr(result, "content", "") or "")
            _tally(result)
            if revised.strip():
                draft = revised
            # Doom-guard: a revise that closed nothing means more rounds won't either.
            if len(coverage_gaps(draft, entities, bundle)) >= len(gaps):
                logger.info("sprint: revise round %d closed no gap — stopping", round_no)
                break

        note = missing_note(coverage_gaps(draft, entities, bundle), bundle)
        if note:
            draft = f"{draft}\n\n{note}" if draft.strip() else note
        # Same capture contract as native `_run_work`: these are real provider calls
        # with real usage, so the step records exact provenance rather than leaving the
        # rollups to guess. Summed over the pipeline's calls.
        if telemetry is not None:
            telemetry.record(
                input_tokens=tokens_in or None,
                output_tokens=tokens_out or None,
                cost_source="exact",
            )
        _beat("sprint_done")
        return draft, cost

    return _work


def _draft_messages(
    *, context: Any, goal: str, acceptance: str, handoff: str, bundle: str
) -> list[dict[str, str]]:
    """Draft-call messages, built exactly as native `_run_work` builds its own.

    Same prompt builder, same context fields, same "search results ride their own
    trailing message" sandboxing — so the only thing sprint mode changes about the
    model's input is that Python chose the searches.
    """
    from my_crew.company_docs.inject import company_docs_text
    from my_crew.llm.team_task_prompt import build_team_step_messages
    from my_crew.profile.context import EMPTY
    from my_crew.skills.skill_selector import select_skill_text

    ctx = context if context is not None else EMPTY
    title = goal
    if acceptance.strip():
        title = f"{goal}\n\nYÊU CẦU NGHIỆM THU:\n{acceptance.strip()}"
    return build_team_step_messages(
        step_title=title,
        handoff_context=handoff,
        search_context=bundle,
        persona=ctx.persona,
        project=ctx.project,
        memory=ctx.memory,
        capability=ctx.capability,
        skills=select_skill_text(ctx, "internal", kind="team-step"),
        company_docs=company_docs_text(ctx, "internal"),
    )


def _revise_instruction(gaps: list[str]) -> str:
    """The one thing the revise round is allowed to ask for: close these gaps.

    Named explicitly so the model rewrites the missing parts instead of restyling the
    whole draft — an untargeted "improve this" round is how a revise loop turns into
    the slow tool loop this mode replaces.
    """
    return (
        "Bản nháp trên còn thiếu dữ liệu cho: " + ", ".join(gaps) + ".\n"
        "Dưới đây là kết quả tìm kiếm bổ sung. Hãy BỔ SUNG các phần còn thiếu vào bản "
        "nháp và giữ nguyên những phần đã đạt — trả về bản đầy đủ đã cập nhật.\n"
        "Mục nào kết quả bổ sung vẫn không có dữ liệu thì ghi rõ THIẾU kèm lý do, "
        "TUYỆT ĐỐI không suy đoán hay bịa số liệu."
    )
