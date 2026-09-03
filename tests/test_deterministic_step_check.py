"""Deterministic layer of the team-step self check: code measures before any LLM grades.

Load-bearing:
- `machine_checkable_gaps` catches a missing named entity / an unmet explicit item
  count from CODE — no provider call — and anything it cannot confidently parse
  contributes nothing (fail-open, so the LLM checker's behavior is unchanged).
- The real `_run_self_check` closure short-circuits on a code-found gap BEFORE
  `_llm()` is touched (same settings=None proof as the empty-result guard).
- A clean measurement enters the checker prompt as a plain FACT line; a blank one
  leaves the prompt byte-identical to the pre-check era.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.deterministic_step_check import (
    checked_facts_line,
    entity_coverage,
    machine_checkable_gaps,
)

_ACCEPTANCE_5 = ("- So sánh đủ 5 sàn (Shopee, Lazada, TikTok Shop, Tiki, Sendo), "
                 "kèm nguồn cho từng sàn")


def test_entity_coverage_reports_only_the_missing_names():
    artifact = "Shopee dẫn đầu, Lazada thứ hai, TikTok Shop tăng nhanh, Tiki giữ niche."
    assert entity_coverage(_ACCEPTANCE_5, artifact) == ["Sendo"]


def test_entity_coverage_is_case_insensitive_substring():
    artifact = "bảng gồm SHOPEE, lazada, tiktok shop, tiki và sendo."
    assert entity_coverage(_ACCEPTANCE_5, artifact) == []


def test_no_enumeration_in_criteria_means_no_gaps():
    # Fail-open: criteria without a machine-readable list constrain nothing here.
    assert machine_checkable_gaps("- văn phong mạch lạc, có kết luận", "bài viết...") == []


def test_gap_lines_name_the_entity_for_the_rework_prompt():
    gaps = machine_checkable_gaps(_ACCEPTANCE_5, "Chỉ nói về Shopee, Lazada, TikTok Shop, Tiki.")
    assert len(gaps) == 1 and "Sendo" in gaps[0]


def test_min_item_count_gap_when_the_list_is_short():
    acceptance = "- liệt kê 5 xu hướng chính"
    artifact = "Ba xu hướng:\n- AI\n- video ngắn\n- social commerce"
    gaps = machine_checkable_gaps(acceptance, artifact)
    assert len(gaps) == 1 and "5" in gaps[0] and "3" in gaps[0]


def test_min_item_count_satisfied_by_numbered_lines():
    acceptance = "- liệt kê 3 ví dụ"
    artifact = "1. A\n2. B\n3. C\n4. D"
    assert machine_checkable_gaps(acceptance, artifact) == []


def test_prose_answer_is_not_countable_so_count_check_fails_open():
    # Zero list-shaped lines ⇒ code cannot count items — the LLM checker decides.
    acceptance = "- liệt kê 5 xu hướng"
    artifact = "Năm xu hướng chính là AI, video ngắn, social commerce, livestream và AR."
    assert machine_checkable_gaps(acceptance, artifact) == []


def test_bare_numbers_are_not_quantity_contracts():
    # "bảng 2 cột" / "quý 3" must not demand 2 or 3 list items.
    assert machine_checkable_gaps("- trình bày bảng 2 cột cho quý 3", "text\n- one") == []


def test_facts_line_states_what_was_measured():
    artifact = "Shopee, Lazada, TikTok Shop, Tiki và Sendo đều có mặt."
    line = checked_facts_line(_ACCEPTANCE_5, artifact)
    assert line.startswith("CODE ĐÃ KIỂM")
    assert "5/5" in line


def test_facts_line_blank_when_nothing_was_checkable():
    assert checked_facts_line("- văn phong mạch lạc", "bài viết dài") == ""


def test_facts_line_blank_when_coverage_is_incomplete():
    # An incomplete measurement is a GAP (handled upstream), never a reassuring fact.
    assert checked_facts_line(_ACCEPTANCE_5, "Chỉ có Shopee.") == ""


# --- precision: code demands only what a substring can prove -----------------------
#
# Rework is capped at one round, so a wrong "missing" verdict here is not a cheap
# recover any more: the second one parks the step for the CEO, and the rework's text
# replaces the first attempt's artifact. Three live steps in one run were lost to the
# three shapes below — each pinned so the parser cannot drift back.


def test_an_example_list_in_the_criteria_is_not_a_demand():
    # "(ví dụ: ...)" illustrates what the author had in mind; the result may name others.
    acceptance = ("- Nêu được 4 rủi ro khác nhau (ví dụ: suy giảm chất lượng code, "
                  "quá tải công việc, xung đột phiên bản, mất dữ liệu)")
    artifact = "1. Bàn giao thiếu ngữ cảnh\n2. Nợ kỹ thuật\n3. Lệch ưu tiên\n4. Kiệt sức"
    assert entity_coverage(acceptance, artifact) == []
    assert machine_checkable_gaps(acceptance, artifact) == []


def test_a_colon_led_example_list_is_not_a_demand_either():
    acceptance = "- 4 thói quen hằng tuần, chẳng hạn: standup hàng ngày, retro cuối tuần"
    assert entity_coverage(acceptance, "Họp kế hoạch, review code, demo, 1:1.") == []


def test_a_lowercase_attribute_clause_in_brackets_is_not_a_demand():
    # "(có điểm khởi đầu và điểm kết thúc rõ ràng)" describes the deliverable; a result
    # meets it in its own words, so only the LLM checker can judge it.
    acceptance = ("- Xác định đúng một mạch việc hoàn chỉnh (có điểm khởi đầu và điểm "
                  "kết thúc rõ ràng)")
    assert entity_coverage(acceptance, "Mạch việc bắt đầu 2/6 và khép lại 20/6.") == []


def test_a_lowercase_slash_pair_is_not_a_demand():
    acceptance = "- Bảng gồm: rủi ro/thói quen, dấu hiệu/lợi ích, giải pháp/cách duy trì"
    artifact = "| Rủi ro | Dấu hiệu | Giải pháp |\n| Thói quen | Lợi ích | Cách duy trì |"
    assert entity_coverage(acceptance, artifact) == []


def test_named_examples_are_still_illustrative():
    # The example filter runs before the name filter: a capitalised example is
    # still only an example.
    acceptance = "- So sánh ít nhất 3 sàn (ví dụ: Shopee, Lazada, Tiki)"
    assert entity_coverage(acceptance, "Sendo, Chợ Tốt và Facebook Marketplace.") == []


def test_real_names_are_still_demanded_next_to_an_example_clause():
    acceptance = ("- Phải có: Shopee, Lazada và Tiki (ví dụ về điểm mạnh: giao nhanh, "
                  "rẻ, nhiều mã)")
    assert entity_coverage(acceptance, "Shopee và Lazada dẫn đầu.") == ["Tiki"]


def test_a_count_before_the_word_example_is_not_an_example_clause():
    # "3 ví dụ" is a quantity, not an illustration marker: the count check still runs.
    acceptance = "- liệt kê 3 ví dụ"
    assert machine_checkable_gaps(acceptance, "- A\n- B") == [
        "tiêu chí đòi ít nhất 3 mục nhưng kết quả chỉ có 2 mục dạng danh sách"
    ]


def test_facts_line_counts_only_the_demanded_names():
    acceptance = "- Phải có: Shopee, Lazada và Tiki (ví dụ: giá, phí, kho)"
    line = checked_facts_line(acceptance, "Shopee, Lazada, Tiki đều có mặt.")
    assert "3/3" in line


# --- wiring: the real `_run_self_check` closure ------------------------------------


def _deps(tmp_path):
    """Real deps, real `_run_self_check`. `settings=None` is the proof: a code-found
    gap must return before `_llm()` is ever touched (empty-result-guard precedent)."""
    from my_crew.agent.team_task_graph import default_team_task_deps

    return default_team_task_deps(
        settings=None, step_title="So sánh 5 sàn",
        data_dir=tmp_path, task_id="t1", step_seq=1,
    )


def test_code_found_gap_fails_self_check_without_any_llm(tmp_path):
    passed, failures, confidence = _deps(tmp_path).run_self_check(
        "Phân tích sâu về Shopee và Lazada.", _ACCEPTANCE_5,
    )
    assert passed is False
    assert confidence == 1.0  # a measurement, not a judgment call
    assert any("Sendo" in f for f in failures)


def _fake_llm(monkeypatch, seen):
    """Swap `LlmClient` for a recorder BEFORE the deps factory imports it — the
    factory constructs `LlmClient(settings)` lazily, so patching the class in its
    home module is enough and no provider is ever touched."""
    import my_crew.llm.client as client_mod

    class _Llm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **_kw):
            seen["user"] = messages[-1]["content"]

            class _R:
                content = '{"passed": true, "failures": [], "confidence": 0.9}'
                cost_usd = 0.0

            return _R()

    monkeypatch.setattr(client_mod, "LlmClient", _Llm)


def test_unparseable_criteria_still_reach_the_llm_checker_unchanged(tmp_path, monkeypatch):
    # No machine-checkable part ⇒ the old path runs — pin by observing the LLM call.
    seen: dict = {}
    _fake_llm(monkeypatch, seen)
    passed, failures, _ = _deps(tmp_path).run_self_check(
        "bài viết hoàn chỉnh", "- văn phong mạch lạc",
    )
    assert passed is True and failures == []
    assert "CODE ĐÃ KIỂM" not in seen["user"]  # nothing measured ⇒ no facts line


def test_clean_measurement_rides_into_the_checker_prompt(tmp_path, monkeypatch):
    seen: dict = {}
    _fake_llm(monkeypatch, seen)
    _deps(tmp_path).run_self_check(
        "Shopee, Lazada, TikTok Shop, Tiki và Sendo: bảng so sánh kèm nguồn.",
        _ACCEPTANCE_5,
    )
    assert "CODE ĐÃ KIỂM" in seen["user"]


def test_sprint_steps_skip_the_precheck_entirely(tmp_path, monkeypatch):
    """`deterministic_precheck=False` (how the runner wires sprint steps): the sprint
    pipeline already ran its own `coverage_gaps` — which knows a source-refused entity
    is not a closable gap, unlike this layer — so a gap this layer WOULD flag must
    fall through to the LLM checker instead of failing the draft from code."""
    from my_crew.agent.team_task_graph import default_team_task_deps

    seen: dict = {}
    _fake_llm(monkeypatch, seen)
    deps = default_team_task_deps(
        settings=None, step_title="So sánh 5 sàn",
        data_dir=tmp_path, task_id="t1", step_seq=1,
        deterministic_precheck=False,
    )
    passed, failures, _ = deps.run_self_check("Chỉ nói về Shopee.", _ACCEPTANCE_5)
    assert passed is True and failures == []  # the (faked) LLM decided, not code
    assert "CODE ĐÃ KIỂM" not in seen["user"]


# --- prompt: the facts line is additive and plain ----------------------------------


def test_blank_code_facts_keeps_the_check_prompt_byte_identical():
    from my_crew.llm.team_task_check_prompt import build_self_check_messages

    before = build_self_check_messages(result_text="kq", acceptance="- tiêu chí")
    after = build_self_check_messages(result_text="kq", acceptance="- tiêu chí",
                                      code_facts="")
    assert before == after


def test_code_facts_line_enters_plain_not_wrapped():
    from my_crew.llm.team_task_check_prompt import build_self_check_messages

    fact = "CODE ĐÃ KIỂM (dữ kiện đo bằng máy, không phải nhận định): đủ 5/5 thực thể."
    msgs = build_self_check_messages(result_text="kq", acceptance="- tiêu chí",
                                     code_facts=fact)
    user = msgs[-1]["content"]
    assert fact in user


# --- item counts: "liệt kê đúng N" is a demand, and the fact line is not a ceiling ----


def test_liet_ke_dung_n_is_a_count_demand():
    """"Liệt kê đúng 4 rủi ro" demands four list items exactly like "liệt kê 4" does —
    measured live, the "đúng" left the demand unread and a per-item sub-count ("ít nhất
    2 biện pháp") became the only number the check knew about."""
    acceptance = "- Liệt kê đúng 4 rủi ro vận hành\n- Mỗi rủi ro có ít nhất 2 biện pháp"
    two_items = "- rủi ro A\n- rủi ro B"

    gaps = machine_checkable_gaps(acceptance, two_items)

    assert any("ít nhất 4" in g for g in gaps), gaps


def test_the_item_count_fact_says_not_fewer_than_never_the_criteria_demand_n():
    """Live, "kết quả có 28 mục (tiêu chí đòi 2)" read to the grader as "two were asked
    for, 28 delivered" and was cited as a failure. The fact must state the direction."""
    acceptance = "- Mỗi rủi ro có ít nhất 2 biện pháp phòng ngừa"
    many = "\n".join(f"- biện pháp {i}" for i in range(28))

    line = checked_facts_line(acceptance, many)

    assert "không ít hơn con số tối thiểu 2" in line
    assert "KHÔNG phải lỗi" in line
    assert "tiêu chí đòi 2" not in line


@pytest.mark.parametrize(
    "criteria",
    [
        "bảng ngân sách theo hạng mục cộng đúng 90 triệu",
        "tổng chi phí đúng 90tr, có dòng tổng",
        "giảm giá ít nhất 20% cho khách cũ",
        "doanh thu tối thiểu 1,5 tỷ trong quý",
        "đủ 50k lượt xem",
    ],
    ids=["trieu", "tr-suffix", "percent", "decimal-ty", "k-suffix"],
)
def test_an_amount_after_a_count_lead_in_is_not_an_item_demand(criteria):
    """"cộng đúng 90 triệu" is a sum to reach. Read as "90 list lines" it failed a
    correct five-week event plan on every calibration run, sending it to rework."""
    artifact = "- Địa điểm: 30tr\n- Tiệc: 25tr\n- Dự phòng: 35tr\n"

    assert machine_checkable_gaps(criteria, artifact) == []


def test_a_count_demand_next_to_an_amount_still_counts():
    """The amount exclusion is per match: the real item demand in the same rubric
    survives it."""
    criteria = "liệt kê 5 hạng mục, cộng đúng 90 triệu"
    artifact = "- Địa điểm: 30tr\n- Tiệc: 25tr\n- Dự phòng: 35tr\n"

    gaps = machine_checkable_gaps(criteria, artifact)

    assert gaps == ["tiêu chí đòi ít nhất 5 mục nhưng kết quả chỉ có 3 mục dạng danh sách"]
