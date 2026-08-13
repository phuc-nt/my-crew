"""v77 sprint runner: the code-paced work loop.

The pipeline's whole claim is that PYTHON decides and the model only writes. So the
tests below assert on the decisions — how many searches, how many LLM calls, when a
revise round happens, when it stops — rather than on the prose that comes out.

The doom-guard cases carry the most weight: a loop that cannot stop is the failure
mode this design replaced, and "stops but silently drops what it missed" is the
failure mode that would make the report untrustworthy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.runtime.sprint_runner as mod
from my_crew.runtime.sprint_runner import (
    build_sprint_work,
    coverage_gaps,
    entity_queries,
    listed_entities,
    missing_note,
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


def _work(prefetch, *, acceptance: str = "", on_phase=None):
    return build_sprint_work(
        loaded=SimpleNamespace(soul="", project="", web_search=True),
        settings=SimpleNamespace(),
        acceptance=acceptance,
        prefetch=prefetch,
        on_phase=on_phase,
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


def test_entity_queries_falls_back_to_the_goal_when_nothing_is_enumerated():
    assert entity_queries("tổng hợp tin tức AI tuần này") == ["tổng hợp tin tức AI tuần này"]


def test_entity_queries_never_exceeds_the_prefetch_cap():
    goal = "Khảo sát: A, B, C, D, E, F, G, H, I"
    assert len(entity_queries(goal)) == mod.MAX_SPRINT_PREFETCH_QUERIES


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
    assert seen[1] == ["dịch vụ Spotify"], "round 2 targets only the gap"
    assert "Spotify" in text
    assert "PHẦN THIẾU" not in text
    assert cost == pytest.approx(0.02)


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
