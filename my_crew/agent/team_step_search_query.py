"""Turning a step's brief into a usable web-search query.

The native work loop used to search for the step TITLE verbatim. Titles are written by
the decompose LLM for a human reading a plan — "Tra cứu thông tin thị trường", "Tổng hợp
kết quả" — so the query that actually went out carried none of the specifics (the
subject, the timeframe, the domain) that live in the step's handoff brief. The search
came back generic, the step wrote something generic, and its own acceptance check failed
it. That is the "agent can't really search" defect.

The fix is deliberately small and deterministic: no extra LLM call, no tool loop (that
is the separate, larger change). Just concatenate the title with the most specific lines
of the brief, drop the boilerplate a search engine gains nothing from, and cap the WORD
count.

That cap is a hard provider limit, not a quality heuristic: Brave rejects a `q` over 50
words with HTTP 422, which the search hook reports as "no results" — indistinguishable
from a genuinely empty result set. The first version of this module capped characters
instead, and that is exactly how it failed in production: the FIRST attempt at a step
searched the short title alone and got results, then every coordinator-guided RETRY
concatenated the guidance plus a prior step's output, crossed 50 words at well under the
character cap, and came back with nothing — so the retry that was supposed to fix a weak
step made it strictly worse, and the step wrote fabricated content instead. Cap by
words. A character cap here is not a stricter version of the same guard, it is the
wrong axis and it silently misses.

EGRESS — an accepted, deliberate trade-off, not an oversight. The handoff brief carries
prior steps' `result_text` and the CEO's verbatim clarify answers, so internal figures
can reach the search provider (Tavily/Brave) in the query string. `redact_query` does
NOT prevent this: it matches credential-shaped tokens (keys, passwords), not confidential
business content. Before this module, only the step title egressed. The CEO was shown a
reproduction of the leak and chose the sharper query anyway, because a query built from
plan-authored fields alone was too weak at exactly the steps where the specifics live in
a prior step's output. Do not widen what feeds this function without re-raising that
trade-off; narrowing it back to title + coordinator guidance is the known safe fallback.
"""

from __future__ import annotations

import re

#: Brave's `q` is capped at 50 WORDS — a 51-word query is not merely down-ranked, it is
#: rejected with HTTP 422 and the step gets ZERO results. Measured against the live API,
#: not assumed: 50 words returned 5 results and 51 returned 0, at identical character
#: lengths. Capping by characters (the first version of this module did, at 300) is the
#: wrong axis and silently broke Vietnamese queries first, since accented text averages
#: ~1.2 bytes/char and hits any byte-shaped ceiling sooner than the ASCII a limit is
#: usually eyeballed against. 44 leaves headroom under the hard limit for the caller's
#: own additions without spending the budget on a margin nobody needs.
MAX_QUERY_WORDS = 44

#: Secondary guard only. No provider limit sits here — it exists so a single pathological
#: "word" (a pasted URL, a base64 blob with no spaces) cannot pass the word count while
#: still shipping a kilobyte of junk. Well under Brave's documented 400-char ceiling.
MAX_QUERY_CHARS = 380

#: Lines a brief carries for the WORKER's benefit that tell a search engine nothing.
#: Matched at line start, case-insensitively — these are the section headers this
#: codebase's own handoff/guidance builders emit, not arbitrary content.
_BOILERPLATE_PREFIXES = (
    "kết quả các bước trước",
    "chỉ dẫn của điều phối",
    "bối cảnh",
    "ghi chú",
    "gợi ý",
    "trả lời bằng tiếng việt",
)

#: The internal-content delimiters `format_internal_content` wraps untrusted step output
#: in. A brief may embed a previous step's result inside them; those lines are data for
#: the worker to reason over, never query terms.
_DELIMITER_RE = re.compile(r"^\s*(<[^>]+>|-{3,}|={3,}|`{3,})")

#: Heading `review_graph._rework_handoff_text` writes above the reviewer's defect list.
#: Defined here rather than there because this module PARSES it: producer and parser
#: sharing one literal is what stops a reworded heading from silently reverting a fix
#: round to searching its own prior draft. `review_graph` imports it back.
REWORK_FAILURES_HEADING = "Danh sách lỗi cần sửa:"


def _is_useful(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _DELIMITER_RE.match(stripped):
        return False
    lowered = stripped.lower()
    return not any(lowered.startswith(p) for p in _BOILERPLATE_PREFIXES)


def build_search_query(title: str, handoff: str = "") -> str:
    """The query to actually send, built from the step's title plus what makes this step
    specific.

    Order matters: the title leads (it names the task), then the brief's own useful
    lines (the subject, the qualifiers, and — after a coordinator intervention — the
    guidance saying what the last attempt missed). Everything is squashed to one line
    and cut to the first `MAX_QUERY_WORDS` words, so what survives an over-long brief is
    the part that identifies the step rather than whatever the last line happened to say.

    A blank title with a blank brief returns "" — the caller must treat that as "no
    search", since an empty query would spend an API call to learn nothing.

    One exception to "then the brief's own useful lines": when the brief carries a
    `REWORK_FAILURES_HEADING` section, those lines lead instead. A fix round's brief is
    `prior draft + defect list`, and the draft is both longer and first, so the plain
    order spends the whole word budget re-searching the text that ALREADY failed review
    — the query that comes back is the one that produced the rejected draft. What makes
    a fix round specific is what the reviewer said was missing. Measured across the
    seven rework rows of task 51ad15207896: leading with the draft put the defect list
    into 3/7 queries, and in one case sent a serialized tool-call blob from the draft to
    the provider; leading with the failures puts it in 7/7. This mirrors what the
    graph's internal `rework` node already does when it builds its query from
    `failures` rather than from the handoff.
    """
    parts: list[str] = []
    if title.strip():
        parts.append(title.strip())
    failure_lines: list[str] = []
    other_lines: list[str] = []
    in_failures = False
    for line in (handoff or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(REWORK_FAILURES_HEADING):
            in_failures = True
            continue
        # The failures section is a run of `- ` bullets. Anything else ends it —
        # `perceive` appends further blocks (CEO clarifications, coordinator guidance)
        # after the deps handoff, and those must not be silently reclassified as
        # reviewer findings just because they trail the list.
        if in_failures and not stripped.startswith("-"):
            in_failures = False
        if _is_useful(line):
            (failure_lines if in_failures else other_lines).append(stripped)
    parts.extend(failure_lines)
    parts.extend(other_lines)
    words = " ".join(parts).split()[:MAX_QUERY_WORDS]
    query = " ".join(words)
    if len(query) <= MAX_QUERY_CHARS:
        return query
    # Only reachable via pathologically long single "words" (a pasted URL, a base64
    # blob). Cut at a word boundary so the tail is not a fragment the provider
    # tokenizes into noise; fall back to the hard cut when there is no space to cut at.
    cut = query[:MAX_QUERY_CHARS]
    space = cut.rfind(" ")
    return cut[:space] if space > 0 else cut
