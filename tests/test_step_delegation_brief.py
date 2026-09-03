"""The worker reads the rubric it is graded on and the scope its siblings own.

Before this block the team-step work prompt carried the title, the artifact line and
the deps' hand-off; `acceptance` reached only the self-check. A step that never read
its rubric stops short of it, and one that never saw the plan redoes a sibling's work
— both are specification failures the harness references guard against by putting
objective, format, boundaries AND rubric in every delegate's brief.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.agent.step_delegation_brief import (
    ACCEPTANCE_HEADER,
    MAX_SIBLINGS,
    SIBLINGS_HEADER,
    delegation_brief,
    sibling_titles,
)


def _step(step_id, title, *, step_type="work", system_inserted=False):
    return SimpleNamespace(
        step_id=step_id, title=title, step_type=step_type, system_inserted=system_inserted,
    )


def test_acceptance_is_shown_verbatim_under_its_header():
    text = delegation_brief("- nêu 3 hãng\n- kèm nguồn", [])
    assert text.startswith(ACCEPTANCE_HEADER)
    assert "- nêu 3 hãng\n- kèm nguồn" in text
    assert SIBLINGS_HEADER not in text


def test_siblings_exclude_self_review_and_system_rows_in_plan_order():
    me = _step("s2", "Viết bản so sánh")
    steps = [
        _step("s1", "Tra cứu giá"),
        me,
        _step("s3", "Soát chéo", step_type="review"),
        _step("s4", "Sửa theo review", system_inserted=True),
        _step("s5", "Đề xuất chiến lược"),
        _step("s6", "   "),
    ]
    assert sibling_titles(me, steps) == ["Tra cứu giá", "Đề xuất chiến lược"]


def test_the_siblings_block_names_each_title_as_not_this_steps_work():
    text = delegation_brief("", ["Tra cứu giá", "Đề xuất chiến lược"])
    assert text.startswith(SIBLINGS_HEADER)
    assert "- Tra cứu giá\n- Đề xuất chiến lược" in text
    assert ACCEPTANCE_HEADER not in text


def test_a_blank_brief_renders_nothing():
    assert delegation_brief("", []) == ""
    assert delegation_brief("   ", ["", "  "]) == ""


def test_the_sibling_list_is_capped_with_a_count_of_the_rest():
    names = [f"Bước {i}" for i in range(MAX_SIBLINGS + 3)]
    text = delegation_brief("", names)
    assert f"- Bước {MAX_SIBLINGS - 1}" in text
    assert f"- Bước {MAX_SIBLINGS}" not in text
    assert "và 3 bước khác" in text


def test_rubric_comes_before_the_siblings_scope():
    text = delegation_brief("đủ 3 hãng", ["Tra cứu giá"])
    assert text.index(ACCEPTANCE_HEADER) < text.index(SIBLINGS_HEADER)


# --- wiring: the graph's work AND rework prompts carry the block ------------------


def _fake_llm(monkeypatch, seen):
    import my_crew.llm.client as client_mod

    class _Llm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **_kw):
            seen.append(messages[-1]["content"])

            class _R:
                content = "bản nháp"
                cost_usd = 0.0

            return _R()

    monkeypatch.setattr(client_mod, "LlmClient", _Llm)


def test_the_graphs_work_and_rework_calls_both_carry_the_brief(tmp_path, monkeypatch):
    from my_crew.agent.team_task_graph import default_team_task_deps

    seen: list[str] = []
    _fake_llm(monkeypatch, seen)
    brief = delegation_brief("đủ 3 hãng, kèm nguồn", ["Tra cứu giá"])
    deps = default_team_task_deps(
        settings=None, step_title="Viết bản so sánh", data_dir=tmp_path, task_id="t1",
        step_seq=2, delegation_brief=brief,
    )
    deps.run_work("Viết bản so sánh", "", None)
    deps.run_rework("Viết bản so sánh", "bản nháp", ["thiếu nguồn"], "")

    assert len(seen) == 2
    for user in seen:
        assert ACCEPTANCE_HEADER in user and "đủ 3 hãng, kèm nguồn" in user
        assert "- Tra cứu giá" in user


def test_without_a_brief_the_prompts_are_unchanged(tmp_path, monkeypatch):
    from my_crew.agent.team_task_graph import default_team_task_deps

    seen: list[str] = []
    _fake_llm(monkeypatch, seen)
    deps = default_team_task_deps(
        settings=None, step_title="Viết", data_dir=tmp_path, task_id="t1", step_seq=1,
    )
    deps.run_work("Viết", "", None)
    assert ACCEPTANCE_HEADER not in seen[0] and SIBLINGS_HEADER not in seen[0]
