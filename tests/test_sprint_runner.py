"""v77 sprint runner: the code-paced work loop.

The pipeline's whole claim is that PYTHON decides and the model only writes. So the
tests below assert on the decisions — how many searches, how many LLM calls, when a
revise round happens, when it stops — rather than on the prose that comes out.

The doom-guard cases carry the most weight: a loop that cannot stop is the failure
mode this design replaced, and "stops but silently drops what it missed" is the
failure mode that would make the report untrustworthy.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import my_crew.runtime.sprint_runner as mod
from my_crew.runtime.sprint_runner import (
    build_sprint_work,
    coverage_gaps,
    entity_queries,
    listed_entities,
    missing_note,
    resolve_entities,
)


class _FakeLlm:
    """Records every call's messages and replays a scripted list of replies."""

    def __init__(self, replies: list[str], cost: float = 0.01):
        self._replies = list(replies)
        self._cost = cost
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, **_kw):
        self.calls.append(list(messages))
        reply = self._replies.pop(0) if self._replies else ""
        return SimpleNamespace(content=reply, cost_usd=self._cost)


@pytest.fixture
def llm(monkeypatch):
    """Install a scriptable LLM; the test fills `.replies` before running the work."""
    box: dict[str, _FakeLlm] = {}

    def _install(replies, cost: float = 0.01) -> _FakeLlm:
        fake = _FakeLlm(replies, cost)
        box["llm"] = fake
        monkeypatch.setattr(mod, "LlmClient", lambda _s: fake, raising=False)
        import my_crew.llm.client as client_mod

        monkeypatch.setattr(client_mod, "LlmClient", lambda _s: fake)
        return fake

    return _install


def _work(prefetch, *, acceptance: str = "", on_phase=None, retry_round: int = 0):
    return build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance=acceptance,
        prefetch=prefetch,
        on_phase=on_phase,
        retry_round=retry_round,
    )


# --- query + entity extraction -------------------------------------------------------


def test_listed_entities_reads_a_vietnamese_colon_list():
    assert listed_entities("So sánh 5 sàn: Shopee, Lazada, TikTok Shop, Tiki và Sendo") == [
        "Shopee", "Lazada", "TikTok Shop", "Tiki", "Sendo",
    ]


def test_listed_entities_ignores_a_prose_clause_after_a_colon():
    """A colon introducing a sentence is not an enumeration — one item is not a list."""
    assert listed_entities("Lưu ý: cần hoàn thành trước thứ sáu tuần này") == []


def test_the_subjects_in_parentheses_beat_the_attributes_after_the_colon():
    """Regression from live benchmark 3d860be3c58b, which the old longest-list rule got
    exactly backwards: it returned the three ATTRIBUTES and never saw the five services.
    The sprint then searched "So sánh 5 dịch vụ streaming giá gói cá nhân" — a query
    about no particular service — and the step died telling the CEO it had no way to get
    real-time data, for a brief whose subjects were written right there in the goal."""
    goal = ("So sánh 5 dịch vụ streaming nhạc tại Việt Nam (Spotify, YouTube Music, "
            "Apple Music, Zing MP3, Nhaccuatui): giá gói cá nhân, kho nhạc Việt, "
            "chất lượng âm thanh. Nêu rõ nguồn.")
    assert listed_entities(goal) == [
        "Spotify", "YouTube Music", "Apple Music", "Zing MP3", "Nhaccuatui",
    ]
    # ...and each subject gets its own search, which is the whole point of getting the
    # entity list right — one query per service, not one query per attribute.
    assert entity_queries(goal)[:5] == [
        "dịch vụ streaming nhạc tại Việt Nam Spotify",
        "dịch vụ streaming nhạc tại Việt Nam YouTube Music",
        "dịch vụ streaming nhạc tại Việt Nam Apple Music",
        "dịch vụ streaming nhạc tại Việt Nam Zing MP3",
        "dịch vụ streaming nhạc tại Việt Nam Nhaccuatui",
    ]


def test_a_colon_list_still_wins_when_there_is_no_parenthesised_list():
    """The parenthesis rule is a PREFERENCE, not a replacement: the plain colon form is
    how most briefs are written and must keep working untouched."""
    assert listed_entities("So sánh 3 công cụ note-taking: Notion, Obsidian và Logseq") == [
        "Notion", "Obsidian", "Logseq",
    ]


def test_a_parenthetical_aside_is_not_mistaken_for_an_entity_list():
    """One item in parentheses is an aside, not an enumeration — so the colon list is
    still what the sprint searches for."""
    assert listed_entities("So sánh 3 sàn (2026): Shopee, Lazada và Tiki") == [
        "Shopee", "Lazada", "Tiki",
    ]


def test_a_prose_enumeration_after_a_preposition_is_recognised_when_asked_for():
    """The v78 C3 brief lists its five tools after "của" — no colon before the names,
    no parentheses. Without the prose branch the resolver returned [], the sprint ran
    ONE kitchen-sink query, saw no coverage gaps, and lost the blind judging 9.5 vs
    24.5 to the team pipeline on the only pair where that happened."""
    goal = (
        "Tìm giá gói cá nhân/nhóm nhỏ (hoặc giá cho 5 người) của Notion, Figma, "
        "Obsidian, Canva và Google Workspace theo tháng; xác định công cụ nào đang "
        "có khuyến mãi hoặc gói miễn phí đủ dùng cho nhóm 5 người."
    )
    assert listed_entities(goal, prose=True) == [
        "Notion", "Figma", "Obsidian", "Canva", "Google Workspace",
    ]


def test_the_prose_branch_is_opt_in_so_router_thresholds_stay_frozen():
    """`listed_entities` is also imported by the intake router and the team
    decomposer, whose fan-out thresholds were frozen at the v78 acceptance. Only the
    sprint's own resolver opts into prose recognition; the default must keep
    returning [] for prose lists or routing behavior silently shifts."""
    goal = "Tìm giá của Notion, Figma, Obsidian, Canva và Google Workspace theo tháng"
    assert listed_entities(goal) == []
    assert listed_entities(goal, prose=True) == [
        "Notion", "Figma", "Obsidian", "Canva", "Google Workspace",
    ]


def test_a_prose_list_whose_attributes_come_before_the_subjects_still_parses():
    """The intake rewrites briefs, and its rewrite of the same C3 brief put the
    attribute clause BEFORE the list — "giá ... theo tháng hiện nay của Notion, ...".
    So the prose parser must not pre-cut the text at attribute lead-ins the way the
    colon branch does; it trims non-name words off the edge items instead."""
    goal = (
        "Tóm tắt ngắn về chi phí công cụ làm việc cho nhóm nội dung: tra cứu giá gói "
        "cá nhân hoặc gói nhóm nhỏ theo tháng hiện nay của Notion, Figma, Obsidian, "
        "Canva và Google Workspace; xác định công cụ nào đang có giảm giá."
    )
    assert listed_entities(goal, prose=True) == [
        "Notion", "Figma", "Obsidian", "Canva", "Google Workspace",
    ]


def test_a_prose_list_without_a_connector_still_counts_at_three_names():
    """Live task 847cefe9b088: the intake's second rephrase of the same brief dropped
    the "và" entirely — "của các công cụ Notion, Figma, Obsidian, Canva, Google
    Workspace cho nhóm nội dung" — and the connector requirement sent the sprint back
    to one kitchen-sink query. Three capitalised items are enough evidence of a list
    on their own; the connector only lowers that bar to two."""
    goal = (
        "Tóm tắt ngắn chi phí hiện nay của các công cụ Notion, Figma, Obsidian, "
        "Canva, Google Workspace cho nhóm nội dung"
    )
    assert listed_entities(goal, prose=True) == [
        "Notion", "Figma", "Obsidian", "Canva", "Google Workspace",
    ]


def test_a_two_name_comma_splice_needs_a_connector_to_be_a_list():
    """Without "và"/"hoặc", two capitalised items are as likely a comma splice joining
    clauses ("Notion, Figma là hai công cụ…") as a list — the floor stays at three."""
    assert listed_entities(
        "Notion, Figma là hai công cụ phổ biến trong nhóm nhỏ", prose=True
    ) == []


def test_a_lowercase_attribute_run_is_never_mistaken_for_a_prose_entity_list():
    """Vietnamese attributes are lowercase; capitalization is the discriminator that
    keeps "giá, tính năng và hỗ trợ" from becoming three fake search subjects."""
    assert listed_entities("Đánh giá công cụ theo giá, tính năng và hỗ trợ", prose=True) == []


def test_a_prose_list_whose_attribute_clause_brings_its_own_commas_still_parses():
    """Live task e577613a962f: the decomposer rewrote the streaming brief without
    parentheses or a colon — "gồm Spotify, …, Nhaccuatui về giá gói cá nhân, kho
    nhạc Việt và chất lượng âm thanh". The attribute clause's own commas push the
    last entity into a MIDDLE part ("Nhaccuatui về giá gói cá nhân"), which the
    all-capitalised middle rule used to reject wholesale — one kitchen-sink query,
    three rework rounds, and a blind-judge loss on source quality. A middle part
    that OPENS with a capitalised run now ends the list there instead."""
    goal = (
        "So sánh 5 dịch vụ streaming nhạc tại Việt Nam gồm Spotify, YouTube Music, "
        "Apple Music, Zing MP3, Nhaccuatui về giá gói cá nhân, kho nhạc Việt và "
        "chất lượng âm thanh; nêu rõ nguồn cho từng thông tin."
    )
    assert listed_entities(goal, prose=True) == [
        "Spotify", "YouTube Music", "Apple Music", "Zing MP3", "Nhaccuatui",
    ]


def test_a_middle_part_with_no_leading_capitalised_run_still_rejects_the_splice():
    """The mid-list cut must not weaken the clause-splice guard: a middle part that
    opens lowercase means the commas join clauses, not names, so the whole run is
    rejected even though the names collected before it would have met the floor."""
    assert listed_entities(
        "So sánh Spotify, YouTube Music, rồi đánh giá Zalo, Momo và Grab", prose=True
    ) == []


def test_a_lowercase_middle_item_rejects_the_prose_run_instead_of_being_skipped():
    """Edge items may carry surrounding prose ("của Notion", "Canva theo tháng") but a
    lowercase run in the MIDDLE means the commas are joining clauses, not names —
    keeping the survivors would invent subjects from half a sentence."""
    assert listed_entities("So sánh Notion, giá hợp lý và Figma nói chung", prose=True) == []


def test_entity_queries_gives_each_entity_its_own_topic_prefixed_query():
    """The topic names the SUBJECT ("giá dịch vụ"), not the assignment: "So sánh" is
    what the CEO asked us to do, and a search engine has nothing to say about that."""
    queries = entity_queries("So sánh giá 3 dịch vụ: Netflix, Spotify, YouTube")
    assert queries[:3] == [
        "giá dịch vụ Netflix",
        "giá dịch vụ Spotify",
        "giá dịch vụ YouTube",
    ]
    assert queries[-1] == "So sánh giá 3 dịch vụ: Netflix, Spotify, YouTube"


def test_the_topic_keeps_the_subject_whole_instead_of_cutting_it_at_the_word_limit():
    """Regression from live benchmark 210e3686daf5. The topic used to be the goal's first
    six non-entity words — "Nghiên cứu so sánh 5 dịch" — five of which described the
    assignment and the sixth of which severed "dịch" from "vụ streaming nhạc". Every
    per-entity query then asked about comparison articles rather than about a music
    service, and the draft came back with a price for one service out of five."""
    goal = (
        "Nghiên cứu và so sánh 5 dịch vụ streaming nhạc tại Việt Nam (Spotify, "
        "YouTube Music, Apple Music, Zing MP3, Nhaccuatui) về giá gói cá nhân, "
        "kho nhạc Việt, và chất lượng âm thanh, kèm nguồn tham khảo."
    )
    assert entity_queries(goal)[:5] == [
        "dịch vụ streaming nhạc tại Việt Nam Spotify",
        "dịch vụ streaming nhạc tại Việt Nam YouTube Music",
        "dịch vụ streaming nhạc tại Việt Nam Apple Music",
        "dịch vụ streaming nhạc tại Việt Nam Zing MP3",
        "dịch vụ streaming nhạc tại Việt Nam Nhaccuatui",
    ]


def test_a_quantifier_and_its_preposition_leave_the_topic_together():
    """"của 5" counted the entities the query already names. Dropping the number alone
    would strand "của" mid-phrase, so the preposition governing it goes with it."""
    goal = (
        "Khảo sát giá gói trả phí của 5 dịch vụ họp online: Zoom, Google Meet, "
        "Microsoft Teams, Cisco Webex, Zoho Meeting"
    )
    assert entity_queries(goal)[0] == "giá gói trả phí dịch vụ Zoom"


def test_a_task_verb_is_only_stripped_from_the_head_of_the_topic():
    """"so sánh" leading the goal is the assignment; the same words inside the subject
    are vocabulary the query needs, so only a LEADING run is removed."""
    assert entity_queries("Tổng hợp bảng so sánh 3 CRM: Hubspot, Zoho, Salesforce")[0] == (
        "bảng so sánh CRM Hubspot"
    )


def test_a_deliverable_head_goal_yields_the_subject_not_the_deliverable():
    """Regression from live task 8251ebc8c8c0. Intake rephrases briefs into
    deliverable-head goals ("Tóm tắt ngắn về chi phí…"); the topic used to break at
    "về" with only head words collected, producing five queries of the form
    "Tóm tắt ngắn <tên công cụ>" — no price keyword, generic results, drafts that
    invented numbers, and a correct self-check refusal that stalled the task. The
    head ("Tóm tắt ngắn") plus its lead-in must be consumed so the topic starts at
    the actual subject; and the word-limit cut must not strand "gói cá" out of
    "gói cá nhân" — backing the half-shipped phrase off entirely beats keeping it."""
    goal = (
        "Tóm tắt ngắn về chi phí hàng tháng gói cá nhân hoặc gói nhóm nhỏ hiện nay "
        "của Notion, Figma, Obsidian, Canva và Google Workspace; chỉ ra công cụ nào "
        "đang có chương trình giảm giá hoặc gói miễn phí đủ dùng cho nhóm khoảng 5 "
        "người; đưa nhận định ngắn giữa việc đổi công cụ hay giữ nguyên Notion + Figma"
    )
    tools = ("Notion", "Figma", "Obsidian", "Canva", "Google Workspace")
    queries = entity_queries(goal)
    assert queries == [f"chi phí hàng tháng {tool}" for tool in tools]


def test_entity_queries_falls_back_to_the_goal_when_nothing_is_enumerated():
    assert entity_queries("tổng hợp tin tức AI tuần này") == ["tổng hợp tin tức AI tuần này"]


def test_entity_queries_scale_with_the_list_but_never_beyond_the_hard_cap():
    """The v78 budget was flat — 6 prefetch slots whether the brief listed 2 subjects
    or 9, so a 9-subject brief silently dropped a third of its subjects before the
    first draft. The budget now follows the entity count up to a hard ceiling."""
    nine = "Khảo sát: A1, B2, C3, D4, E5, F6, G7, H8, I9"
    assert len(entity_queries(nine)) == 10, "9 entity queries + 1 overview"
    fifteen = "Khảo sát: " + ", ".join(f"Xx{i}" for i in range(15))
    assert len(entity_queries(fifteen)) == mod.SCALED_PREFETCH_CAP


def test_a_long_goal_never_rides_along_as_the_overview_query():
    """Live task 647ee49de19d: the raw-goal overview query came back HTTP 422. A goal
    that long can only return a failure sentinel, which then writes a spurious
    source-error line into the THIẾU note of a report that actually covered
    everything — so the overview is skipped, not truncated."""
    goal = (
        "Tìm giá gói cá nhân/nhóm nhỏ (hoặc giá cho 5 người) của Notion, Figma, "
        "Obsidian, Canva và Google Workspace theo tháng; xác định công cụ nào đang "
        "có khuyến mãi hoặc gói miễn phí đủ dùng cho nhóm 5 người."
    )
    queries = entity_queries(goal)
    assert len(queries) == 5, "one query per tool, no overview"
    assert goal not in queries
    assert all(len(q.split()) <= 12 for q in queries)


def test_sprint_query_budget_keeps_the_legacy_caps_when_nothing_is_enumerated():
    """No entity list means no per-entity fan-out to pay for — the flat v77 budget
    stays exactly as it was so un-enumerated briefs spend nothing new."""
    assert mod.sprint_query_budget(0) == (
        mod.MAX_SPRINT_PREFETCH_QUERIES, mod.MAX_TOTAL_QUERIES,
    )


def test_sprint_query_budget_scales_with_the_entity_count():
    assert mod.sprint_query_budget(5) == (6, 11)
    assert mod.sprint_query_budget(9) == (10, 16)


def test_sprint_query_budget_is_capped_no_matter_how_long_the_list():
    assert mod.sprint_query_budget(30) == (mod.SCALED_PREFETCH_CAP, mod.SCALED_TOTAL_CAP)


# --- coverage check ------------------------------------------------------------------


def test_coverage_gaps_finds_the_entity_the_draft_never_mentions():
    draft = "Netflix giá 260k. Spotify giá 59k."
    assert coverage_gaps(draft, ["Netflix", "Spotify", "YouTube"], "") == ["YouTube"]


def test_coverage_gaps_ignores_an_entity_whose_source_already_refused():
    """Re-searching a query that came back empty burns budget to reach the same wall —
    that is a reporting fact, not a gap another round can close."""
    bundle = "[KHÔNG CÓ KẾT QUẢ] (truy vấn: giá YouTube) Nguồn hoạt động bình thường"
    assert coverage_gaps("Netflix giá 260k.", ["Netflix", "YouTube"], bundle) == []


def test_missing_note_separates_an_uncovered_entity_from_a_failed_query():
    """The two belong on their own lines: "we searched and got too little for Sendo" is
    a different fact from "the query for Tiki never reached a source"."""
    bundle = "[LỖI NGUỒN TÌM KIẾM] (truy vấn: giá Tiki) Không truy cập được web search"
    note = missing_note(["Sendo"], bundle)
    assert "Sendo" in note
    assert "giá Tiki" in note
    assert "KHÔNG kết luận là dữ liệu không tồn tại" in note


def test_a_dead_source_and_an_empty_one_do_not_produce_the_same_note():
    """`[LỖI NGUỒN]` and `[KHÔNG CÓ KẾT QUẢ]` imply OPPOSITE next moves — retry later
    versus never — so the note the CEO acts on must not collapse them.

    Caught by running the pipeline end-to-end rather than by a unit test: both bundles
    were pooled into one "không trả kết quả ... ghi THIẾU do nguồn" line, which told a
    CEO the source had broken when the truth was that the data is not public. The unit
    test that claimed to cover this only ever fed the source-error bundle, so the two
    were never compared against each other.
    """
    query = "(truy vấn: giá Tiki)"
    dead = missing_note([], f"[LỖI NGUỒN TÌM KIẾM] {query} Không truy cập được")
    empty = missing_note([], f"[KHÔNG CÓ KẾT QUẢ] {query} Nguồn hoạt động bình thường")

    assert dead and empty
    assert dead != empty
    assert "lỗi" in dead.lower() and "không công khai" not in dead
    assert "không công khai" in empty and "lỗi" not in empty.lower()
    # Neither may ever license the model to conclude the data does not exist.
    assert "KHÔNG kết luận là dữ liệu không tồn tại" in dead
    assert "KHÔNG tự suy ra con số" in empty


def test_a_bundle_carrying_both_failure_kinds_reports_each_under_its_own_reason():
    """A real run mixes them — one entity's source times out while another's simply has
    no public data. Each query must land under the reason that actually applies to it."""
    bundle = (
        "[LỖI NGUỒN TÌM KIẾM] (truy vấn: giá Tiki) Không truy cập được\n\n"
        "[KHÔNG CÓ KẾT QUẢ] (truy vấn: giá Sendo) Nguồn hoạt động bình thường"
    )
    note = missing_note([], bundle)
    broken_line = next(ln for ln in note.splitlines() if "lỗi" in ln.lower())
    empty_line = next(ln for ln in note.splitlines() if "không công khai" in ln)

    assert "giá Tiki" in broken_line and "giá Sendo" not in broken_line
    assert "giá Sendo" in empty_line and "giá Tiki" not in empty_line


def test_missing_note_is_empty_when_everything_was_covered():
    assert missing_note([], "") == ""


# --- pipeline ------------------------------------------------------------------------


def test_happy_path_is_one_search_round_and_one_llm_call(llm):
    fake = llm(["Netflix 260k. Spotify 59k."])
    seen: list[list[str]] = []

    def _prefetch(_loaded, _settings, queries):
        seen.append(list(queries))
        return "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nNetflix 260k, Spotify 59k"

    text, cost = _work(_prefetch)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert len(fake.calls) == 1, "a fully-covered draft must not trigger a revise"
    assert len(seen) == 1
    assert cost == pytest.approx(0.01)
    assert "PHẦN THIẾU" not in text


def test_a_coverage_gap_triggers_one_targeted_search_and_a_revise(llm):
    fake = llm(["Netflix 260k.", "Netflix 260k. Spotify 59k."])
    seen: list[list[str]] = []

    def _prefetch(_loaded, _settings, queries):
        seen.append(list(queries))
        return "KẾT QUẢ TÌM KIẾM (truy vấn: x):\ndữ liệu"

    text, cost = _work(_prefetch)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert len(fake.calls) == 2
    assert len(seen) == 2
    # The prefetch already asked "dịch vụ Spotify" and its results are in the bundle —
    # re-sending the same string re-buys the same thin answer. With no attribute
    # clause to angle by, the bare subject is the only query left that is new.
    assert seen[1] == ["Spotify"], "round 2 targets only the gap, with a NEW query"
    assert "Spotify" in text
    assert "PHẦN THIẾU" not in text
    assert cost == pytest.approx(0.02)


def test_a_targeted_query_asks_a_new_angle_instead_of_the_query_that_came_back_thin(llm):
    """C3's second stacked defect: the round-2 query was byte-for-byte the prefetch
    query whose results were already in the bundle — a guaranteed re-read of the same
    wall. When the brief carries an attribute clause, the retry angles by it."""
    fake = llm(["Chỉ có Notion.", "Notion 10 USD. Obsidian 8 USD."])
    seen: list[list[str]] = []

    def _prefetch(_loaded, _settings, queries):
        seen.append(list(queries))
        return "KẾT QUẢ TÌM KIẾM (truy vấn: x):\ndữ liệu"

    _work(_prefetch)("So sánh 2 công cụ: Notion, Obsidian theo giá tháng", "", None)

    flat = [q.lower() for one_round in seen for q in one_round]
    assert len(set(flat)) == len(flat), "no query is ever sent twice"
    assert seen[1] == ["Obsidian giá tháng"]
    assert len(fake.calls) == 2


def test_the_second_round_rotates_to_a_different_angle_for_a_persisting_gap(llm):
    """Round 1 closed one gap, so the pipeline keeps going — and round 2's query for
    the still-open gap must lead with the NEXT angle, not re-pair the gap with the
    phrasing whose thin answer round 1 already merged into the bundle."""
    fake = llm([
        "Chỉ có Notion.",
        "Notion có giá. Obsidian có giá.",
        "Notion, Obsidian và Logseq đều có giá.",
    ])
    seen: list[list[str]] = []

    def _prefetch(_loaded, _settings, queries):
        seen.append(list(queries))
        return f"KẾT QUẢ TÌM KIẾM (truy vấn: x):\ndữ liệu mới {len(seen)}"

    _work(_prefetch, acceptance="- Liệt kê gói miễn phí của từng công cụ")(
        "So sánh 3 công cụ: Notion, Obsidian, Logseq theo giá tháng", "", None,
    )

    flat = [q.lower() for one_round in seen for q in one_round]
    assert len(seen) == 3, "prefetch + both revise rounds"
    assert seen[1] == ["Obsidian giá tháng", "Logseq giá tháng"]
    assert seen[2] == ["Logseq gói miễn phí của từng công cụ"]
    assert len(set(flat)) == len(flat), "every round asks something new"
    assert len(fake.calls) == mod.MAX_REVISE_ROUNDS + 1


def test_the_revise_round_carries_the_draft_forward_instead_of_re_briefing(llm):
    """Cumulative context is the point: round 2 must see round 1's draft, not restart."""
    fake = llm(["Netflix 260k.", "Netflix 260k. Spotify 59k."])
    _work(lambda *_a: "kết quả")("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    second = fake.calls[1]
    assert len(second) > len(fake.calls[0])
    assert any(m["role"] == "assistant" and "Netflix 260k." in m["content"] for m in second)
    assert any("còn thiếu dữ liệu cho: Spotify" in m["content"] for m in second)


def test_doom_guard_stops_after_max_rounds_and_reports_what_is_missing(llm):
    """A model that keeps returning the same gap must not loop — it must stop honest."""
    fake = llm(["Chỉ có Netflix."] * 6)

    text, _cost = _work(lambda *_a: "kết quả mới")(
        "So sánh 2 dịch vụ: Netflix, Spotify", "", None,
    )

    assert len(fake.calls) <= mod.MAX_REVISE_ROUNDS + 1
    assert "PHẦN THIẾU" in text
    assert "Spotify" in text


def test_a_search_round_that_returns_nothing_new_stops_immediately(llm):
    """No new data means a revise call would re-read the same context — skip it."""
    calls = {"n": 0}

    def _prefetch(_loaded, _settings, _queries):
        calls["n"] += 1
        return "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nchỉ có Netflix" if calls["n"] == 1 else ""

    fake = llm(["Chỉ có Netflix."] * 4)
    text, _ = _work(_prefetch)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert len(fake.calls) == 1, "no new data ⇒ no revise call"
    assert "PHẦN THIẾU" in text


def test_a_provider_error_is_reported_not_silently_passed_as_success(llm):
    llm(["Netflix 260k."])
    bundle = (
        "[LỖI NGUỒN TÌM KIẾM] (truy vấn: giá Spotify) Không truy cập được web search"
    )
    text, _ = _work(lambda *_a: bundle)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert "giá Spotify" in text
    assert "KHÔNG kết luận là dữ liệu không tồn tại" in text


def test_the_no_capability_marker_is_the_producer_s_own_string():
    """The guard is a string comparison across two modules, so a copied literal would
    let either side be reworded with both suites still green — and the only symptom
    would be the sprint silently going back to claiming a search it never ran. A
    review proved that exact blind spot: mutating the producer's constant left 59
    tests passing, because each side asserted against its own copy."""
    from my_crew.runtime.collect_prefetch import NO_SEARCH_CAPABILITY

    assert mod._NO_CAPABILITY is NO_SEARCH_CAPABILITY


def test_a_step_that_could_never_search_says_so_instead_of_claiming_it_tried(llm):
    """No `web_search` opt-in and no provider key both mean zero queries ran. The note
    used to read "đã tìm nhưng không đủ kết quả dùng được" for every entity — a claim
    about a search that never happened, on top of a draft written from model memory."""
    llm(["Netflix thì tôi nhớ khoảng 260k."])
    bundle = mod._NO_CAPABILITY + " Agent chưa được cấp quyền web_search"
    text, _ = _work(lambda *_a: bundle)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert "Không thực hiện được tra cứu web" in text
    assert "đã tìm nhưng không đủ" not in text
    assert "KHÔNG kết luận là dữ liệu không tồn tại" in text


def test_a_tool_less_sprint_runs_no_search_and_ships_no_thieu_note(llm):
    """Intake ruled `needs_web=False` — write/reason on data already in the brief.
    Live UAT caught the old behavior: a thank-you note still ran a doomed prefetch,
    hit the no-capability sentinel, and the CEO's final message carried a disclaimer
    about a web search the task never needed. Tool-less means ALL search machinery
    off: no prefetch call, no coverage rounds, no PHẦN THIẾU — even when the goal
    happens to parse as an entity list."""
    fake = llm(["Cảm ơn Netflix và Spotify đã đồng hành."])
    searched: list[list[str]] = []

    def _prefetch(_l, _s, queries):
        searched.append(list(queries))
        return mod._NO_CAPABILITY + " Agent chưa được cấp quyền web_search"

    text, _ = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        prefetch=_prefetch,
        needs_web=False,
    )("Viết thư cảm ơn 2 đối tác: Netflix, Spotify", "", None)

    assert searched == [], "tool-less sprint must never call prefetch"
    assert len(fake.calls) == 1, "one draft call, no revise rounds"
    assert "PHẦN THIẾU" not in text
    assert "tra cứu" not in text


def test_no_search_capability_spends_no_revise_rounds(llm):
    """Every retry would hit the same wall, and the revise prompt asks the model to
    close gaps it has no new data for — an invitation to invent."""
    fake = llm(["Chỉ có Netflix.", "KHÔNG ĐƯỢC GỌI", "KHÔNG ĐƯỢC GỌI"])
    searched: list[list[str]] = []

    def _prefetch(_l, _s, queries):
        searched.append(list(queries))
        return mod._NO_CAPABILITY + " Hệ thống chưa cấu hình khoá nhà cung cấp tìm kiếm"

    build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        prefetch=_prefetch,
    )("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert len(fake.calls) == 1
    assert len(searched) == 1


def test_a_targeted_round_of_only_sentinels_buys_no_revise_call(llm):
    """The round came back non-empty but informationally empty. Spending a revise on it
    hands the model an instruction to close a gap plus a payload of failure notices —
    asking it to write from nothing, which is exactly what the honesty contract bans."""
    fake = llm(["Chỉ có Netflix.", "KHÔNG ĐƯỢC GỌI"])
    rounds: list[list[str]] = []

    def _prefetch(_l, _s, queries):
        rounds.append(list(queries))
        if len(rounds) == 1:
            return "KẾT QUẢ TÌM KIẾM (truy vấn: giá Netflix):\nNetflix 260k."
        return "[LỖI NGUỒN TÌM KIẾM] (truy vấn: giá Spotify) Không truy cập được."

    text, _ = _work(_prefetch)("So sánh 2 dịch vụ: Netflix, Spotify", "", None)

    assert len(rounds) == 2, "the targeted round still runs — only the revise is skipped"
    assert len(fake.calls) == 1
    # The round's sentinels must survive into the note: they are the evidence for WHY
    # Spotify is still missing. Dropped, the note blames thin results for a search that
    # actually hit a dead source — the two reasons this module exists to keep apart.
    assert "giá Spotify" in text
    assert "KHÔNG kết luận là dữ liệu không tồn tại" in text
    assert "đã tìm nhưng không đủ" not in text


def test_a_parenthesised_query_survives_into_the_note_with_its_brackets_intact(llm):
    """`entity_queries` appends the raw goal as the overview query, and CEOs write their
    subjects in parentheses — so cutting the sentinel at the first `)` truncated the
    query mid-list and left an unbalanced bracket in what the CEO reads."""
    llm(["Chưa có dữ liệu."])
    goal = "So sánh 3 sàn (Shopee, Lazada, Tiki)"
    bundle = f"[LỖI NGUỒN TÌM KIẾM] (truy vấn: {goal}) Không truy cập được web search."
    text, _ = _work(lambda *_a: bundle)(goal, "", None)

    assert goal in text
    assert "Tiki)" in text


def test_prefetch_failure_still_produces_a_draft(llm):
    """Fail-open, same contract as the launcher: no search is not no work."""
    def _boom(*_args):
        raise RuntimeError("search down")

    fake = llm(["Viết theo hiểu biết sẵn có."])
    text, _ = _work(_boom)("tổng hợp tin tức AI", "", None)

    assert len(fake.calls) == 1
    assert text.startswith("Viết theo hiểu biết sẵn có.")


def test_every_phase_beats_the_heartbeat(llm):
    """One node covers the whole pipeline, so without this the lease looks dead."""
    llm(["Chỉ có Netflix.", "Vẫn chỉ có Netflix."])
    phases: list[str] = []
    _work(lambda *_a: "kết quả", on_phase=phases.append)(
        "So sánh 2 dịch vụ: Netflix, Spotify", "", None,
    )

    assert phases[0] == "sprint_prefetch"
    assert "sprint_draft" in phases
    assert phases[-1] == "sprint_done"


def test_a_broken_heartbeat_never_fails_the_work(llm):
    llm(["xong"])

    def _bad(_phase):
        raise RuntimeError("store down")

    text, _ = _work(lambda *_a: "kết quả", on_phase=_bad)("tổng hợp tin tức", "", None)
    assert text == "xong"


def test_acceptance_criteria_reach_the_draft_prompt(llm):
    fake = llm(["xong"])
    _work(lambda *_a: "kết quả", acceptance="- Phải có bảng giá")(
        "tổng hợp tin tức AI", "", None,
    )
    assert any("Phải có bảng giá" in m["content"] for m in fake.calls[0])


def test_entities_declared_only_in_acceptance_still_drive_coverage(llm):
    """The CEO often names the list in the criteria, not the one-line goal."""
    fake = llm(["Chỉ có Netflix."] * 4)
    text, _ = _work(lambda *_a: "kết quả", acceptance="Phải có: Netflix, Spotify")(
        "so sánh dịch vụ streaming", "", None,
    )
    assert len(fake.calls) > 1
    assert "PHẦN THIẾU" in text


def test_a_multiline_rubric_never_supplies_entities():
    """A rubric's bullets use colons to introduce ATTRIBUTES, not entities. Reading
    them as entities produced gaps ("giá", "tính năng") no draft could ever close."""
    rubric = "- Nêu rõ: giá, tính năng và hỗ trợ\n- Có bảng so sánh"
    assert mod.resolve_entities("khảo sát thị trường", rubric) == []


def test_the_list_glue_never_leaks_into_a_query():
    """`và`/`and` join the entity list; with the entities stripped they would
    otherwise survive as topic words ("So sánh 3 công cụ và Notion")."""
    queries = entity_queries("So sánh 3 công cụ: Notion, Asana và Trello")
    assert all(" và " not in q and not q.endswith(" và") for q in queries[:3])
    assert queries[0] == "công cụ Notion"


def test_a_failed_overview_query_does_not_mask_every_entity():
    """The overview query names EVERY entity, so letting it speak for each one would
    suppress every real gap and tell the CEO the sources failed when they had not."""
    bundle = (
        f"{mod._SOURCE_FAILED} (truy vấn: so sánh giá netflix, spotify, youtube) hỏng"
    )
    assert coverage_gaps("Chỉ nói Netflix.", ["Netflix", "Spotify", "YouTube"], bundle) == [
        "Spotify", "YouTube",
    ]


def test_a_single_entity_failure_still_suppresses_that_entity():
    bundle = f"{mod._NO_RESULTS} (truy vấn: so sánh giá spotify) không có kết quả"
    assert coverage_gaps("Chỉ nói Netflix.", ["Netflix", "Spotify"], bundle) == []


def test_a_subject_list_in_prose_beats_an_attribute_list_behind_a_colon():
    """Live task 7ebfc0374c5c: the step title named the five services in running prose
    and put the three CRITERIA behind a colon ("... trên các tiêu chí: giá gói cá
    nhân, ..."). The colon branch won, so the sprint searched for the criteria, found
    nothing usable about any service, and the task stalled. Subjects beat attributes
    here for the same reason the parenthesised branch already outranks the colon."""
    title = (
        "So sánh 5 dịch vụ streaming nhạc tại Việt Nam gồm Spotify, YouTube Music, "
        "Apple Music, Zing MP3, Nhaccuatui trên các tiêu chí: giá gói cá nhân, "
        "kho nhạc Việt, chất lượng âm thanh. Nêu rõ nguồn cho từng thông tin."
    )
    assert resolve_entities(title, "") == [
        "Spotify", "YouTube Music", "Apple Music", "Zing MP3", "Nhaccuatui",
    ]


def test_a_colon_list_of_real_names_still_wins_over_prose():
    """The discriminator is capitalisation, not position: a colon that introduces the
    SUBJECTS ("Phải có: Spotify, Zing MP3") must keep winning as it always has."""
    assert resolve_entities("Khảo sát thị trường", "Phải có: Spotify, Zing MP3, Nhaccuatui") == [
        "Spotify", "Zing MP3", "Nhaccuatui",
    ]


def test_a_retry_attempt_does_not_re_send_the_queries_that_already_failed(llm):
    """A coordinator retry re-runs this deterministic pipeline from scratch, so without
    a rotation it sends byte-identical queries, gets the bundle that was already judged
    insufficient, and stalls the same way (live tasks f62348234949, 7ebfc0374c5c)."""
    seen: list[list[str]] = []

    def _prefetch(_loaded, _settings, queries):
        seen.append(list(queries))
        return "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nNetflix 260k, Spotify 59k"

    goal = "So sánh 2 dịch vụ: Netflix, Spotify"
    acceptance = "- Nêu giá gói cá nhân\n- Nêu chất lượng hình ảnh"

    llm(["Netflix 260k. Spotify 59k."])
    _work(_prefetch, acceptance=acceptance)(goal, "", None)
    llm(["Netflix 260k. Spotify 59k."])
    _work(_prefetch, acceptance=acceptance, retry_round=1)(goal, "", None)

    first, retry = seen[0], seen[1]
    assert retry != first, "a retry must ask something the failed attempt did not"
    assert all(q not in first for q in retry)
    # The subjects are still covered — only the angle changed, so the retry still
    # searches FOR Netflix and Spotify rather than wandering off the goal.
    assert any("Netflix" in q for q in retry) and any("Spotify" in q for q in retry)


# --- official-page fetch round -------------------------------------------------------


def test_without_firecrawl_the_bundle_reaching_the_draft_is_unchanged(llm):
    """The deployment default. The fetch round must be invisible: the draft sees exactly
    the snippet bundle prefetch produced, so a deployment that never configures
    Firecrawl behaves as it did before this round existed."""
    # Deliberately a bundle the picker WOULD match, so what this asserts is the absent
    # Firecrawl config skipping the round — not the picker happening to find nothing.
    bundle = (
        "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nhttps://www.spotify.com/vn/\nSpotify 59k"
        "\n\nhttps://zingmp3.vn/vip\nZing MP3"
    )

    fake = llm(["Spotify 59k."])
    _work(lambda *_a: bundle)("So sánh 2 dịch vụ: Spotify, Zing MP3", "", None)

    drafted = "\n".join(m["content"] for m in fake.calls[0])
    assert bundle in drafted
    assert "TRANG CHÍNH THỨC" not in drafted


def test_with_firecrawl_the_official_page_reaches_the_draft(llm, monkeypatch):
    """The payoff: the price lives on the vendor's page, not in the snippet, so the
    draft can cite the official source instead of falling back to a reseller."""
    monkeypatch.setattr(
        "my_crew.tools.firecrawl_tool.scrape_url",
        lambda url, config, **_k: SimpleNamespace(
            url=url, title="Spotify Premium", markdown="Gói cá nhân 59.000đ/tháng",
            status_code=200,
        ),
    )
    work = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(
            firecrawl_base_url="http://localhost:3002", firecrawl_api_key=None
        ),
        prefetch=lambda *_a: (
            "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nhttps://www.spotify.com/vn/premium/\nSpotify"
            "\n\nhttps://zingmp3.vn/vip\nZing MP3"
        ),
    )
    fake = llm(["Spotify 59.000đ."])
    work("So sánh 2 dịch vụ: Spotify, Zing MP3", "", None)

    drafted = "\n".join(m["content"] for m in fake.calls[0])
    assert "TRANG CHÍNH THỨC" in drafted
    assert "59.000" in drafted


def test_a_reseller_url_in_the_bundle_is_never_fetched(llm, monkeypatch):
    """Fetching the aggregator would spend the budget re-buying the exact source
    quality this round exists to replace.

    The entity names are the aggregators themselves, so the host DOES pass the
    brand-label rule and only the aggregator guard can refuse it. With unrelated
    entities the label rule alone would refuse these hosts and this test would pass
    with the guard deleted — verified, and that is what it used to do.
    """
    scraped: list[str] = []

    def _scrape(url, config, **_k):
        scraped.append(url)
        return SimpleNamespace(url=url, title="t", markdown="nội dung", status_code=200)

    monkeypatch.setattr("my_crew.tools.firecrawl_tool.scrape_url", _scrape)
    work = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(
            firecrawl_base_url="http://localhost:3002", firecrawl_api_key=None
        ),
        prefetch=lambda *_a: (
            "KẾT QUẢ TÌM KIẾM (truy vấn: x):\n"
            "https://www.amazon.com/music/\nĐại lý"
            "\n\nhttps://vi.wikipedia.org/wiki/X\nBách khoa"
        ),
    )
    llm(["Nội dung."])
    work("So sánh 2 dịch vụ: Amazon Music, Wikipedia", "", None)
    assert scraped == []


def test_a_failing_fetch_still_lets_the_step_draft(llm, monkeypatch):
    """Firecrawl going down must degrade to today's behaviour, not fail the step."""
    def _boom(url, config, **_k):
        raise RuntimeError("firecrawl offline")

    monkeypatch.setattr("my_crew.tools.firecrawl_tool.scrape_url", _boom)
    work = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(
            firecrawl_base_url="http://localhost:3002", firecrawl_api_key=None
        ),
        prefetch=lambda *_a: (
            "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nhttps://www.spotify.com/vn/\nSpotify 59k"
            "\n\nhttps://zingmp3.vn/vip\nZing MP3"
        ),
    )
    fake = llm(["Spotify 59k."])
    text, _cost = work("So sánh 2 dịch vụ: Spotify, Zing MP3", "", None)
    assert "Spotify 59k." in text
    assert "TRANG CHÍNH THỨC" not in "\n".join(m["content"] for m in fake.calls[0])


def test_a_toolless_step_never_fetches(llm, monkeypatch):
    """needs_web=False means the whole search machinery stays off; the fetch round is
    part of that machinery."""
    scraped: list[str] = []
    monkeypatch.setattr(
        "my_crew.tools.firecrawl_tool.scrape_url",
        lambda url, config, **_k: scraped.append(url),
    )
    work = build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(
            firecrawl_base_url="http://localhost:3002", firecrawl_api_key=None
        ),
        prefetch=lambda *_a: "https://www.spotify.com/vn/",
        needs_web=False,
    )
    llm(["Thư cảm ơn."])
    work("Viết thư cảm ơn", "", None)
    assert scraped == []


def test_the_fetch_round_records_why_it_fetched_nothing(llm, tmp_path):
    """A round that fetched nothing must say WHICH nothing. On the default deployment
    (no Firecrawl) the picker would still find URLs, so `bytes: 0` alone cannot separate
    "capability absent" from "all pages failed" — and absent is the common case, so a
    reader guessing from bytes guesses wrong most of the time."""
    from my_crew.config.config_builders import build_settings_from_dict
    from my_crew.runtime.step_recorder import open_step_recorder, step_transcript_path

    bundle = "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nhttps://www.spotify.com/vn/\nSpotify 59k"
    settings = build_settings_from_dict({"data_dir": tmp_path})
    llm(["Spotify 59k."])
    with open_step_recorder(settings, agent_id="a1", task_id="t1", step_id="s1",
                            attempt_id="att1"):
        _work(lambda *_a: bundle)("So sánh 2 dịch vụ: Spotify, Zing MP3", "", None)

    path = step_transcript_path(tmp_path, "t1", "s1", "att1")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fetches = [e for e in events if e["t"] == "fetch"]
    assert len(fetches) == 1
    assert fetches[0]["skipped"] == "no-firecrawl"
    assert fetches[0]["bytes"] == 0


def test_a_round_where_every_page_failed_says_so(llm, tmp_path, monkeypatch):
    """The gap a live run exposed: with Firecrawl CONFIGURED and URLs picked, a total
    fetch failure recorded `bytes: 0` with a populated `urls` list and no reason — the
    one ambiguous shape left, on the only path that needs a live Firecrawl to reach.
    "All pages failed" and "capability absent" demand different responses (fix the
    scraper vs configure one), so the transcript has to name which happened."""
    import my_crew.runtime.official_page_fetch as fetch_mod

    bundle = "KẾT QUẢ TÌM KIẾM (truy vấn: x):\nhttps://www.spotify.com/vn/\nSpotify 59k"
    monkeypatch.setattr(fetch_mod, "firecrawl_available", lambda _s: True)
    # Configured but every page comes back empty — the real-world blocked/404/timeout case.
    monkeypatch.setattr(fetch_mod, "fetch_official_pages",
                        lambda *_a, **_kw: "", raising=False)

    from my_crew.config.config_builders import build_settings_from_dict
    from my_crew.runtime.step_recorder import open_step_recorder, step_transcript_path

    settings = build_settings_from_dict({"data_dir": tmp_path})
    llm(["Spotify 59k."])
    with open_step_recorder(settings, agent_id="a1", task_id="t2", step_id="s1",
                            attempt_id="att1"):
        _work(lambda *_a: bundle)("So sánh 2 dịch vụ: Spotify, Zing MP3", "", None)

    path = step_transcript_path(tmp_path, "t2", "s1", "att1")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fetch = next(e for e in events if e["t"] == "fetch")
    assert fetch["skipped"] == "all-pages-failed"
    assert fetch["bytes"] == 0
    # The URLs stay: WHICH pages failed is the diagnostic value here, unlike the
    # no-capability path where there is nothing to diagnose.
    assert fetch["urls"] == ["https://www.spotify.com/vn/"]
