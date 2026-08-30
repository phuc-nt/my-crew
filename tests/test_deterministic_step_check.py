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
