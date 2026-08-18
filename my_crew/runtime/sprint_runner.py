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

from my_crew.runtime.collect_prefetch import NO_SEARCH_CAPABILITY

logger = logging.getLogger(__name__)

#: Hard ceilings for one sprint step. `MAX_REVISE_ROUNDS` bounds LLM calls at
#: 1 draft + 2 revises = 3 regardless of how many searches the budget allows; the
#: flat query caps below apply when the brief enumerates nothing (see
#: `sprint_query_budget` for the scaled form an entity list buys).
MAX_REVISE_ROUNDS = 2
MAX_TOTAL_QUERIES = 8
#: Queries issued before the draft. Kept under the total so a revise round always has
#: budget left — a doom-guard that fires because round 1 ate the whole allowance
#: would report gaps it never actually tried to fill.
#: Named apart from `collect_prefetch.MAX_PREFETCH_QUERIES` (3) on purpose: the two
#: modules sit side by side and cap different things — a collect step's title-derived
#: fan-out vs a sprint's per-entity round.
MAX_SPRINT_PREFETCH_QUERIES = 6
#: Ceilings the SCALED budget can never exceed, however long the enumeration: they
#: are what keeps the CEO's per-task cost cap decidable when a brief lists 30 items.
SCALED_PREFETCH_CAP = 12
SCALED_TOTAL_CAP = 16
#: Longest goal (in words) still worth sending verbatim as the overview query. Live
#: task 647ee49de19d is why: the provider rejected the raw-goal query with HTTP 422,
#: so a long overview can only come back as a failure sentinel — buying no data and
#: putting a spurious source-error line into the THIẾU note of a fully-covered report.
_MAX_OVERVIEW_WORDS = 12


def sprint_query_budget(entity_count: int) -> tuple[int, int]:
    """(prefetch cap, total cap) for a brief enumerating `entity_count` subjects.

    The old budget was flat — 6 prefetch slots whether the brief listed 2 subjects or
    9 — so a 9-subject brief silently dropped a third of its subjects before the
    first draft ever ran. Scaled: every subject keeps its own prefetch query plus the
    overview, and the targeted-round allowance grows with the list (at least 2, one
    per subject beyond that) so a wide brief can still re-search what came back thin.

    No enumeration means no per-entity fan-out to pay for, so the flat legacy caps
    apply unchanged — an un-enumerated brief spends exactly what it spent before.
    """
    if entity_count <= 0:
        return MAX_SPRINT_PREFETCH_QUERIES, MAX_TOTAL_QUERIES
    prefetch = min(entity_count + 1, SCALED_PREFETCH_CAP)
    return prefetch, min(prefetch + max(2, entity_count), SCALED_TOTAL_CAP)

#: Sentinels `collect_prefetch` writes when a query returned nothing usable. Their
#: presence in the bundle is a COVERAGE fact (the source failed / has no public data),
#: not a defect in the draft — the check below reads them so a revise round targets
#: the entities that are genuinely still missing rather than re-asking for these.
_SOURCE_FAILED = "[LỖI NGUỒN TÌM KIẾM]"
_NO_RESULTS = "[KHÔNG CÓ KẾT QUẢ]"

#: The bundle-wide marker meaning no search was ATTEMPTED (no opt-in, no provider key).
#: It carries no `(truy vấn: …)`, so it can only be read at bundle level — every
#: entity is uncovered for the same one reason, and saying so once beats listing
#: every name under "đã tìm nhưng không đủ kết quả", which would be a lie twice over.
#: IMPORTED at the module header, never re-declared: the producer writes it and this
#: module reads it, so a copied literal would let either side be reworded while both
#: suites stayed green — and the only symptom would be this whole guard going dark.
_NO_CAPABILITY = NO_SEARCH_CAPABILITY


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
    # the total cap must never cost an entity its own search. It is skipped entirely
    # when the goal is too long to be a search query (see `_MAX_OVERVIEW_WORDS`).
    if len(goal.split()) <= _MAX_OVERVIEW_WORDS:
        queries.append(goal)
    prefetch_cap, _total = sprint_query_budget(len(entities))
    return queries[:prefetch_cap]


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
    entities = listed_entities(goal, prose=True)
    if entities:
        return entities
    text = (acceptance or "").strip()
    if not text or "\n" in text:
        return []
    return listed_entities(text, prose=True)


def listed_entities(text: str, *, prose: bool = False) -> list[str]:
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

    `prose=True` adds a LAST-RESORT branch for lists written in running prose — "của
    Notion, Figma, Obsidian, Canva và Google Workspace theo tháng" — where neither
    punctuation anchor exists. It is opt-in because this function is also imported by
    the intake router and the team decomposer, whose fan-out thresholds were frozen
    at the v78 acceptance: only the sprint's own resolver may see the prose branch.
    """
    paren = _longest_enumeration(re.finditer(r"\(([^)\n]+)\)", text or ""))
    if paren:
        return paren
    colon = _longest_enumeration(
        re.finditer(r":\s*([^.\n:?!]+)", text or ""), stop_at_attributes=True
    )
    if not prose:
        return colon
    # An ALL-LOWERCASE colon list is the attribute clause, and the subjects are then
    # somewhere else in the sentence — the same subjects-beat-attributes ordering the
    # parenthesised branch above encodes, in the third shape real briefs use: the names
    # in running prose and the criteria behind a colon ("... gồm Spotify, YouTube Music,
    # ... trên các tiêu chí: giá gói cá nhân, kho nhạc Việt, chất lượng âm thanh" — live
    # task 7ebfc0374c5c). Letting the colon win there searched for the three CRITERIA,
    # found nothing usable about any service, and stalled the task. Capitalisation is
    # the same discriminator `_prose_enumeration` already relies on, so a colon list of
    # real names ("Phải có: Spotify, Zing MP3") still wins as before.
    if colon and any(_capitalised_name_word(item) for item in colon):
        return colon
    return _prose_enumeration(text or "") or colon


def _longest_enumeration(matches: Any, *, stop_at_attributes: bool = False) -> list[str]:
    """The longest comma/`và`-separated item list among `matches`, else [].

    `stop_at_attributes` applies only to the colon form, where the subject list and
    the attribute clause share one run of text: "Notion, Obsidian và Apple Notes theo
    giá, offline" ends its subjects at "theo". Without the cut, "Apple Notes theo giá"
    becomes an entity and each attribute becomes one too, so the sprint searches for
    a product that does not exist and reports coverage gaps it can never close. The
    parenthesised form needs no such cut — its closing bracket already ends the list.
    """
    best: list[str] = []
    for m in matches:
        text = m.group(1)
        if stop_at_attributes:
            text = _before_attribute_lead_in(text)
        items = [
            part.strip(" .;–-")
            for chunk in text.split(",")
            for part in re.split(r"\s+và\s+", chunk)
        ]
        items = [i for i in items if i and len(i.split()) <= 7]
        if len(items) > len(best):
            best = items
    return best if len(best) >= 2 else []


def _before_attribute_lead_in(text: str) -> str:
    """`text` truncated at the first attribute lead-in that follows an entity.

    Matched on word boundaries so a lead-in buried inside a name ("Theo Dõi Chi Tiêu")
    does not sever the list, and only from the second word on, since a clause that
    OPENS with a lead-in has no subjects before it to keep.
    """
    for lead in _ATTRIBUTE_LEAD_INS:
        m = re.search(rf"\S\s+\b{re.escape(lead)}\b\s", text, flags=re.IGNORECASE)
        if m:
            text = text[: m.start() + 1]
    return text


#: Punctuation stripped off the edges of a prose item's words before judging case.
_EDGE_PUNCT = " .;–-—\"'“”‘’"


def _prose_enumeration(text: str) -> list[str]:
    """A comma+`và`/`hoặc` list of capitalised names inside running prose, else [].

    This is the shape the C3 benchmark brief used — the subjects follow a preposition
    ("… của Notion, Figma, Obsidian, Canva và Google Workspace theo tháng") with no
    colon or parenthesis anywhere near them, so both punctuation branches return []
    and the sprint used to degrade to one kitchen-sink query.

    Capitalisation is the discriminator that keeps attribute runs out: Vietnamese
    attributes are lowercase ("giá, tính năng và hỗ trợ"), names are not. The edge
    items may carry the surrounding sentence — the first is trimmed to its TRAILING
    capitalised run ("của Notion" → "Notion"), the last to its LEADING run ("Google
    Workspace theo tháng" → "Google Workspace"). There is deliberately no pre-cut at
    attribute lead-ins here: real briefs put the attribute clause on either side of
    the list ("theo tháng hiện nay của Notion, …"), so cutting at the first lead-in
    would destroy exactly the list this branch exists to find.
    """
    best: list[str] = []
    best_floor = 2
    for segment in re.split(r"[.\n:;?!()]", text):
        if "," not in segment:
            continue
        # A closing connector is strong evidence of a deliberate list, so two items
        # suffice. Without one ("… của các công cụ Notion, Figma, Obsidian, Canva,
        # Google Workspace cho nhóm nội dung" — live task 847cefe9b088, an intake
        # rephrase that dropped the "và") the commas could be splicing clauses, so
        # three capitalised items are required before the run counts as a list.
        floor = 2 if re.search(r"\b(?:và|hoặc)\b", segment) else 3
        parts = [
            part
            for chunk in segment.split(",")
            for part in re.split(r"\s+(?:và|hoặc)\s+", chunk)
        ]
        items = _proper_noun_items(parts)
        if len(items) >= floor and len(items) > len(best):
            best, best_floor = items, floor
    return best if len(best) >= best_floor else []


def _proper_noun_items(parts: list[str]) -> list[str]:
    """`parts` reduced to capitalised names, or [] when they are not a name list.

    Leading parts with no trailing capitalised run are the preceding clause and are
    skipped. A part in the MIDDLE that opens with a capitalised run and then turns
    lowercase is the list's LAST entity carrying the trailing attribute clause —
    "Nhaccuatui về giá gói cá nhân, kho nhạc Việt và chất lượng âm thanh" — which
    lands mid-list (not in the final part) whenever the attributes bring commas of
    their own. The name is kept and the list ends there. A middle part with NO
    leading capitalised run means the commas are joining clauses, not names, and
    rejects the whole run — keeping the survivors would invent search subjects from
    half a sentence.
    """
    items: list[str] = []
    for index, part in enumerate(parts):
        words = part.split()
        ends_list = False
        if not items:
            j = len(words)
            while j and _capitalised_name_word(words[j - 1]):
                j -= 1
            words = words[j:]
            if not words:
                continue
        elif index == len(parts) - 1 or not all(
            _capitalised_name_word(w) for w in words
        ):
            j = 0
            while j < len(words) and _capitalised_name_word(words[j]):
                j += 1
            if j == 0 and index < len(parts) - 1:
                return []
            words = words[:j]
            if not words:
                continue
            ends_list = index < len(parts) - 1
        if len(words) > 7 or not words[0].strip(_EDGE_PUNCT)[:1].isupper():
            return []
        items.append(" ".join(w.strip(_EDGE_PUNCT) for w in words))
        if ends_list:
            break
    return items


def _capitalised_name_word(word: str) -> bool:
    """True for a word that can sit inside a proper name ("Google", "365", "MP3")."""
    bare = word.strip(_EDGE_PUNCT + ",():")
    return bool(bare) and (bare[:1].isupper() or bare[:1].isdigit())


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
    "tóm", "tắt", "viết", "soạn",
    "research", "survey", "compare", "compile", "summarise", "summarize", "list",
    "review", "analyse", "analyze", "report", "write",
)

#: Words that only describe the deliverable's FORM ("bản tóm tắt ngắn", "bài viết
#: nhanh") — with the task verbs they make up the head a brief may open with before
#: naming its subject. Live task 8251ebc8c8c0 is why they must be consumed: the
#: intake rephrased the C3 brief to "Tóm tắt ngắn về chi phí …", the lead-in break
#: fired right after the head, and all five entity queries became "Tóm tắt ngắn
#: <tên>" — summary-request phrases with no costing word, so every result came back
#: without a single price and the self-check (correctly) refused the draft.
_HEAD_DESCRIPTORS = (
    "bản", "bài", "ngắn", "gọn", "nhanh",
    "brief", "short", "quick", "concise", "summary", "overview",
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
    # The leading deliverable head ("Nghiên cứu so sánh", "Tóm tắt ngắn") is consumed
    # DURING the walk, not stripped afterwards, because the lead-in break must know
    # whether a subject word has appeared yet. "Tóm tắt ngắn VỀ chi phí …" — that
    # `về` introduces the SUBJECT, and breaking there hands every query a head with
    # no noun in it. Only a later run of task verbs is load-bearing vocabulary
    # ("bảng so sánh" as the deliverable) and is kept.
    head_stripped = False
    head_done = False
    for raw in goal.split():
        word = raw.strip(",.():;")
        # `và`/`hoặc`/`and`/`or` are list GLUE, not topic words — with the entities
        # stripped out they would otherwise survive into every query ("So sánh 3 công
        # cụ: và Notion"). `hoặc` joined the set with the prose branch, which splits
        # its lists on it exactly as on `và`.
        if not word or word.lower() in entity_words or word.lower() in ("và", "hoặc", "and", "or"):
            continue
        lower = word.lower()
        if not head_done:
            if lower in _TASK_VERBS or lower in _HEAD_DESCRIPTORS:
                head_stripped = True
                continue
            head_done = True
            if head_stripped and lower in _ATTRIBUTE_LEAD_INS:
                continue  # the lead-in right after the head introduces the subject
        elif words and lower in _ATTRIBUTE_LEAD_INS:
            break  # the subject ended; the rest is what to report ABOUT it
        words.append(word)
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


def _attribute_tail(goal: str) -> str:
    """The goal's attribute clause — everything after the FIRST lead-in that follows
    at least one subject word. The mirror of `_before_attribute_lead_in`: that helper
    keeps the subjects, this one keeps what the CEO asked to know ABOUT them."""
    earliest: int | None = None
    tail = ""
    for lead in _ATTRIBUTE_LEAD_INS:
        m = re.search(
            rf"\S\s+\b{re.escape(lead)}\b\s+(\S.*)$", goal, flags=re.IGNORECASE | re.DOTALL
        )
        if m and (earliest is None or m.start(1) < earliest):
            earliest = m.start(1)
            tail = m.group(1)
    return tail


def attribute_angles(goal: str, acceptance: str, entities: list[str]) -> list[str]:
    """Phrasings a targeted retry can pair with a gap, in priority order.

    The C3 benchmark's second stacked defect: the revise round's query was
    byte-for-byte the prefetch query whose thin results were ALREADY in the bundle —
    a guaranteed re-buy of the same answer. The goal's attribute clause and the
    acceptance lines carry the CEO's own vocabulary for what is being asked about
    each subject ("giá tháng", "gói miễn phí đủ dùng cho nhóm 5 người"), so retries
    draw their phrasing from there instead. Each phrase goes through `_topic_phrase`
    so task verbs, quantifiers and dangling tails are held to the same standard as
    the prefetch queries.
    """
    sources = list(re.split(r"[,;.]", _attribute_tail(goal)))
    sources += [line.strip().lstrip("-•* \t") for line in (acceptance or "").splitlines()]
    angles: list[str] = []
    seen: set[str] = set()
    for raw in sources:
        phrase = _topic_phrase(raw.strip(), entities)
        key = phrase.lower()
        if len(phrase.split()) >= 2 and key not in seen:
            seen.add(key)
            angles.append(phrase)
    return angles


def _fresh_gap_query(
    gap: str, topic: str, angles: list[str], rotation: int, asked: set[str]
) -> str | None:
    """The first phrasing for `gap` not yet sent to a source, else None.

    Candidates in order: the gap paired with each attribute angle — starting at
    `rotation` so a second doom-guard round leads with a DIFFERENT angle than the
    round that just came back thin — then the prefetch's own topic+gap form, then the
    bare gap. `asked` spans the prefetch and every earlier round: a query in it has
    its answer in the bundle already, so re-sending it buys nothing.
    """
    candidates = [f"{gap} {angles[(rotation + i) % len(angles)]}" for i in range(len(angles))]
    candidates += [f"{topic} {gap}".strip(), gap]
    for candidate in candidates:
        if candidate.lower() not in asked:
            return candidate
    return None


#: Words that cannot END a topic phrase: each one governs the word after it, so cutting
#: the phrase here strands it ("… tại Việt" for Việt Nam, "… của 5 dịch" for dịch vụ).
_DANGLING_TAIL_WORDS = (
    "tại", "ở", "của", "cho", "trong", "trên", "với", "và", "các", "những", "một",
    "dịch", "công", "nền", "sản", "thương", "hệ", "ứng", "phần", "gói", "bản",
    "in", "at", "of", "for", "the", "a", "an", "and", "on", "with",
)

#: The subset of governors whose governed phrase routinely runs LONGER than one word:
#: prepositions take a full noun phrase ("tại Việt Nam", "của nhóm nhỏ") and classifiers
#: like "gói"/"bản" name a variant that may span several words ("gói cá nhân"). Compound
#: first-syllables ("dịch", "công", …) are deliberately NOT here — their head is exactly
#: one word away, which the one-word grace in `_trimmed_to_whole_phrase` already covers.
_PHRASE_GOVERNORS = (
    "tại", "ở", "của", "cho", "trong", "trên", "với",
    "gói", "bản", "các", "những", "một",
    "in", "at", "of", "for", "on", "with",
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
    elif len(kept) >= 2 and kept[-2].strip(",.():;").lower() in _PHRASE_GOVERNORS:
        # "… gói | cá nhân": the governed phrase runs PAST the cut, and the boundary
        # pair itself looks clean to `_governs_next` ("cá" is no known governor), so
        # only the governor one step back betrays the half-shipped phrase. Live task
        # 8251ebc8c8c0 hit this as "chi phí hàng tháng gói cá <tên>". Dropping the
        # half (the dangler sweep below then takes the governor too) beats guessing
        # where the phrase ends.
        kept.pop()
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
    return _sentinel_query(line).lower()


def _sentinel_query(line: str) -> str:
    """The query text of a `(truy vấn: …)` sentinel line, brackets balanced.

    Splitting at the FIRST `)` is wrong here: `entity_queries` appends the raw goal as
    its overview query, and `listed_entities` exists precisely because CEOs write their
    subjects in parentheses — so "So sánh 3 sàn (Shopee, Lazada, Tiki)" routinely rides
    inside the sentinel and gets cut at "Tiki", leaving an unbalanced bracket in the
    note the CEO reads. Track the depth instead and close on the paren that actually
    matches the opener.
    """
    if "(truy vấn:" not in line:
        return ""
    rest = line.split("(truy vấn:", 1)[1]
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return rest[:i].strip()
            depth -= 1
    return rest.strip()


def _has_results(bundle: str) -> bool:
    """True when `bundle` carries anything beyond failure sentinels.

    A bundle of nothing but `[LỖI NGUỒN…]`/`[KHÔNG CÓ KẾT QUẢ]` lines is non-empty but
    informationally empty — treating it as new data buys a revise round whose entire
    supporting payload is failure notices.

    Asked as "is there a non-sentinel line", not "is there a `RESULTS_BLOCK` header":
    the header is what `collect_prefetch` writes, but a caller may inject a bundle by
    other means, and content without that header is still content. Only the sentinels
    are known-empty, so only they are subtracted.
    """
    for line in (bundle or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SOURCE_FAILED in stripped or _NO_RESULTS in stripped:
            continue
        return True
    return False


def missing_note(gaps: list[str], bundle: str) -> str:
    """The THIẾU note appended when the pipeline stops with coverage still open.

    Written as data for the CEO, not an apology: which names are missing and which of
    the two reasons applies, so "not in the report" can never be misread as "does not
    exist". Empty string when nothing is missing.
    """
    if _NO_CAPABILITY in (bundle or ""):
        # No query ran, so there is nothing to enumerate per entity — and calling this
        # "đã tìm nhưng không đủ" would claim a search that never happened.
        return (
            "PHẦN THIẾU (do quy trình tự ghi nhận):\n"
            "- Không thực hiện được tra cứu web (thiếu quyền hoặc thiếu cấu hình nguồn), "
            "nên mọi số liệu cần tra cứu đều THIẾU DO KHÔNG TRA CỨU ĐƯỢC — "
            "KHÔNG kết luận là dữ liệu không tồn tại."
        )
    # Split by sentinel, not pooled. `_source_refused` and `_has_results` may treat the
    # two alike — neither is re-searchable, neither is data — but this note is the one
    # place the difference reaches a human, and the two imply opposite next moves: a
    # broken source is worth retrying later, absent public data never will be. Pooling
    # them sends the CEO chasing a retry that cannot help.
    broken: list[str] = []
    nothing_public: list[str] = []
    for line in (bundle or "").splitlines():
        if "(truy vấn:" not in line:
            continue
        if _SOURCE_FAILED in line:
            broken.append(_sentinel_query(line))
        elif _NO_RESULTS in line:
            nothing_public.append(_sentinel_query(line))
    lines: list[str] = []
    if gaps:
        lines.append(
            "- Chưa thu thập đủ dữ liệu cho: " + ", ".join(gaps)
            + " (đã tìm nhưng không đủ kết quả dùng được)."
        )
    if broken:
        lines.append(
            "- Nguồn tìm kiếm gặp lỗi, không truy cập được cho truy vấn: "
            + ", ".join(dict.fromkeys(broken))
            + " — ghi THIẾU DO NGUỒN LỖI, KHÔNG kết luận là dữ liệu không tồn tại; "
            "có thể tra cứu lại sau."
        )
    if nothing_public:
        lines.append(
            "- Nguồn hoạt động bình thường nhưng không có kết quả cho truy vấn: "
            + ", ".join(dict.fromkeys(nothing_public))
            + " — nhiều khả năng dữ liệu không công khai; ghi THIẾU kèm lý do đó, "
            "KHÔNG tự suy ra con số."
        )
    if not lines:
        return ""
    return "PHẦN THIẾU (do quy trình tự ghi nhận):\n" + "\n".join(lines)


def _fetch_official_pages(
    settings: Any,
    bundle: str,
    entities: list[str],
    *,
    on_beat: Callable[[], None] | None = None,
) -> str:
    """Pick the official URLs out of `bundle` and scrape them; "" when there is nothing
    to add. Wrapped so a fetch can never fail a step: this round is a bonus on top of
    the snippet bundle the caller already holds.

    The transcript event is what makes the round verifiable on a live run. A fix that
    cannot be seen in a transcript can only ever be unit-tested, and this arc already
    shipped three such fixes that no live run exercised. `skipped` is part of that: with
    no Firecrawl configured the round still picks URLs and still fetches nothing, so
    `bytes: 0` alone cannot tell "the capability is absent" from "all pages failed" —
    and the first is the DEFAULT deployment, so a reader who guesses wrong guesses wrong
    most of the time.
    """
    from my_crew.runtime.official_page_fetch import (
        MAX_FETCH_PAGES,
        fetch_official_pages,
        firecrawl_available,
    )
    from my_crew.runtime.official_page_pick import pick_official_urls
    from my_crew.runtime.step_recorder import record_event

    if not firecrawl_available(settings):
        record_event({"t": "fetch", "urls": [], "bytes": 0, "skipped": "no-firecrawl"})
        return ""
    try:
        urls = pick_official_urls(bundle, entities, limit=MAX_FETCH_PAGES)
        fetched = fetch_official_pages(settings, urls, on_beat=on_beat) if urls else ""
    except Exception:  # noqa: BLE001 — an enhancement round must never fail the step
        logger.warning("sprint: official-page fetch failed, using snippets", exc_info=True)
        record_event({"t": "fetch", "urls": [], "bytes": 0, "skipped": "error"})
        return ""
    if not urls:
        record_event({"t": "fetch", "urls": [], "bytes": 0, "skipped": "no-official-url"})
        return ""
    if not fetched:
        # Firecrawl IS configured and URLs WERE picked, yet nothing came back: every page
        # was blocked, 404, timed out, or returned empty. Without a reason here this is
        # the one remaining `bytes: 0` with a populated `urls` list — the exact ambiguity
        # `skipped` exists to remove, surviving on the only path that needs a live
        # Firecrawl to reach. A live run showed this shape before the field was added.
        record_event({"t": "fetch", "urls": urls, "bytes": 0, "skipped": "all-pages-failed"})
        return ""
    record_event({"t": "fetch", "urls": urls, "bytes": len(fetched)})
    return fetched


def build_sprint_work(
    *,
    loaded: Any,
    settings: Any,
    context: Any = None,
    acceptance: str = "",
    telemetry: Any = None,
    prefetch: Callable[[Any, Any, list[str]], str] | None = None,
    on_phase: Callable[[str], None] | None = None,
    needs_web: bool = True,
    retry_round: int = 0,
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

    `needs_web=False` means intake ruled the step tool-less (write/reason on data
    already in the brief) — the whole search machinery stays off: no prefetch, no
    coverage rounds, and no THIẾU note. Live task 780861b42737 is why: a thank-you
    note with nothing to look up still ran a doomed prefetch, hit the no-capability
    sentinel, and shipped the CEO a "không thực hiện được tra cứu web" disclaimer
    about a search the task never needed.

    `retry_round` is the step's intervention count — 0 on the first attempt. It shifts
    the prefetch queries onto attribute angles the earlier attempt never sent, so a
    retry gathers DIFFERENT evidence instead of re-buying the bundle that already
    failed its coverage check.
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
        # Tool-less step: no entities to cover means no queries, no coverage gaps and
        # no THIẾU note — quality control is the review step, same as a needs_web=False
        # team work step.
        entities = resolve_entities(goal, acceptance) if needs_web else []
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
        queries = entity_queries(goal, acceptance) if needs_web else []
        _prefetch_cap, total_queries_cap = sprint_query_budget(len(entities))
        angles = attribute_angles(goal, acceptance, entities) if needs_web else []
        if retry_round > 0 and queries and angles:
            # Retry attempt: lead with an angle the earlier attempts never sent. The
            # topic+entity form they used is already spent — its results are what the
            # coordinator judged insufficient — so repeating it wastes the whole
            # prefetch budget on answers the step has seen.
            queries = [
                f"{q} {angles[(retry_round - 1 + i) % len(angles)]}"
                for i, q in enumerate(queries)
            ]
        # Every query ever sent, prefetch included: its answer — thin or not — is in
        # the bundle, so no later round may spend budget re-sending the same string.
        asked = {q.lower() for q in queries}
        bundle = ""
        used_queries = 0
        if queries:
            try:
                bundle = run_prefetch(loaded, settings, queries)
                used_queries = len(queries)
            except Exception:  # noqa: BLE001 — same fail-open contract as the launcher
                logger.warning("sprint: prefetch failed, drafting without it", exc_info=True)
                bundle = ""

        # Snippets name the vendor's page but rarely carry the figure on it, so the
        # draft was forced onto resellers — the source quality the blind judge marked
        # down 3 rounds running. Open the pages the picker vouches for, once, before
        # drafting. Pure enhancement: no Firecrawl, nothing picked, or a failed scrape
        # all leave `bundle` exactly as the snippet round built it.
        if needs_web and bundle:
            fetched = _fetch_official_pages(
                settings, bundle, entities, on_beat=lambda: _beat("sprint_fetch")
            )
            if fetched:
                bundle = f"{bundle}\n\n{fetched}"

        client = LlmClient(settings)
        messages = _draft_messages(
            context=context, goal=goal, acceptance=acceptance, handoff=handoff, bundle=bundle,
        )
        _beat("sprint_draft")
        result = client.complete(messages, role="content")
        draft = str(getattr(result, "content", "") or "")
        _tally(result)

        for round_no in range(1, MAX_REVISE_ROUNDS + 1):
            _beat("sprint_check")
            gaps = coverage_gaps(draft, entities, bundle)
            if not gaps:
                break
            if _NO_CAPABILITY in bundle:
                # Searching was never possible; a targeted round would hit the same
                # wall and a revise call would only ask the model to invent the gap.
                logger.info("sprint: no search capability — reporting %d gap(s)", len(gaps))
                break
            if used_queries >= total_queries_cap:
                logger.info("sprint: query budget spent with %d gap(s) open", len(gaps))
                break
            budget = total_queries_cap - used_queries
            topic = _topic_phrase(goal, entities)
            extra_queries: list[str] = []
            for g in gaps:
                if len(extra_queries) >= budget:
                    break
                fresh = _fresh_gap_query(g, topic, angles, round_no - 1, asked)
                if fresh is None:
                    continue
                asked.add(fresh.lower())
                extra_queries.append(fresh)
            if not extra_queries:
                # Every phrasing for every open gap has been sent already — another
                # round would re-buy answers that are in the bundle. Stop honest.
                logger.info("sprint: no unasked query left for %d gap(s)", len(gaps))
                break
            try:
                extra = run_prefetch(loaded, settings, extra_queries)
            except Exception:  # noqa: BLE001
                logger.warning("sprint: targeted search failed", exc_info=True)
                extra = ""
            used_queries += len(extra_queries)
            # Merged BEFORE the stop decision, not after: the round's sentinels are the
            # evidence for WHY these gaps stay open, and `missing_note` reads them off
            # the bundle. Breaking first would drop them, and the note would then blame
            # the gaps on thin results for searches that actually hit a dead source.
            bundle = f"{bundle}\n\n{extra}" if bundle else extra
            if not _has_results(extra):
                # Nothing new came back, so a revise call would re-read the same
                # context and produce the same gaps. Stop and report them instead.
                # "Nothing" includes a round that returned ONLY sentinels: those say
                # the sources failed, and paying for a revise whose entire supporting
                # payload is failure notices asks the model to close a gap using data
                # it was never given — the one thing this pipeline must not invite.
                logger.info("sprint: round %d found no new data — stopping honest", round_no)
                break
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
            result = client.complete(messages, role="content")
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
