"""v15 PIC core rules: @-prefix parsing, one-terminal-owned-by-PIC validation, the F4
code-override of a CEO-named PIC, and the hash-neutrality pin (pic_id is metadata —
a PIC task hashes byte-identical to the same DAG without one, so `_verify_plan_hash`'s
recompute domain is untouched).
"""

from __future__ import annotations

import pytest

from my_crew.agent.ops_assign_team_task import parse_pic_prefix
from my_crew.agent.task_decomposition import (
    DecomposedTask,
    DecompositionError,
    TeamStepPlan,
    decomposition_content_hash,
    validate_decomposition,
)

STAFF = {"noi-dung", "nghien-cuu", "kiem-dinh"}


def _step(sid, who, deps=()):
    return TeamStepPlan(step_id=sid, title=f"t-{sid}", assigned_to=who, deps=tuple(deps))


def _task(pic="", *steps):
    return DecomposedTask(steps=tuple(steps), pic_id=pic)


# ---- parse_pic_prefix -------------------------------------------------------

def test_at_id_prefix_extracts_pic_and_clean_brief():
    assert parse_pic_prefix("@noi-dung viết bài giới thiệu") == ("noi-dung", "viết bài giới thiệu")


def test_at_all_and_no_prefix_mean_llm_proposes():
    assert parse_pic_prefix("@all tổng hợp tình hình") == ("", "tổng hợp tình hình")
    assert parse_pic_prefix("tổng hợp tình hình") == ("", "tổng hợp tình hình")


def test_email_like_or_mid_string_at_is_not_a_prefix():
    # @ not at the start never parses as a PIC mention
    assert parse_pic_prefix("gửi mail tới a@b.com nhé") == ("", "gửi mail tới a@b.com nhé")


# ---- validate: one terminal owned by PIC (F5) -------------------------------

def test_valid_pic_plan_passes_and_keeps_pic():
    task = _task(
        "noi-dung",
        _step("s1", "nghien-cuu"),
        _step("s2", "noi-dung", deps=["s1"]),
    )
    out = validate_decomposition(task, staff_ids=STAFF)
    assert out.pic_id == "noi-dung"


def test_multiple_terminals_rejected():
    task = _task("noi-dung", _step("s1", "nghien-cuu"), _step("s2", "noi-dung"))
    with pytest.raises(DecompositionError, match="ĐÚNG MỘT bước chốt cuối"):
        validate_decomposition(task, staff_ids=STAFF)


def test_terminal_not_owned_by_pic_rejected():
    task = _task("noi-dung", _step("s1", "noi-dung"), _step("s2", "kiem-dinh", deps=["s1"]))
    with pytest.raises(DecompositionError, match="PIC"):
        validate_decomposition(task, staff_ids=STAFF)


def test_pic_not_in_staff_rejected():
    # steps are all validly assigned — only the PIC id itself is bogus.
    task = _task("ai-do", _step("s1", "noi-dung"))
    with pytest.raises(DecompositionError, match="PIC .* không có trong danh sách"):
        validate_decomposition(task, staff_ids=STAFF)


def test_single_step_task_must_belong_to_pic():
    ok = validate_decomposition(_task("noi-dung", _step("s1", "noi-dung")), staff_ids=STAFF)
    assert ok.pic_id == "noi-dung"
    with pytest.raises(DecompositionError):
        validate_decomposition(_task("noi-dung", _step("s1", "kiem-dinh")), staff_ids=STAFF)


def test_no_pic_task_skips_pic_rules_v14_compatible():
    # two terminals + no pic — exactly what every pre-v15 decompose produces; must pass.
    task = _task("", _step("s1", "nghien-cuu"), _step("s2", "noi-dung"))
    out = validate_decomposition(task, staff_ids=STAFF)
    assert out.pic_id == ""


# ---- F4: CEO-named PIC overrides the model's proposal -----------------------

def test_ceo_named_pic_overrides_llm_proposal():
    # model proposed kiem-dinh, CEO @-named noi-dung — code must win.
    task = _task(
        "kiem-dinh",
        _step("s1", "nghien-cuu"),
        _step("s2", "noi-dung", deps=["s1"]),
    )
    out = validate_decomposition(task, staff_ids=STAFF, pic_id="noi-dung")
    assert out.pic_id == "noi-dung"


def test_ceo_named_pic_still_requires_terminal_ownership():
    task = _task(
        "kiem-dinh",
        _step("s1", "nghien-cuu"),
        _step("s2", "kiem-dinh", deps=["s1"]),
    )
    with pytest.raises(DecompositionError, match="PIC"):
        validate_decomposition(task, staff_ids=STAFF, pic_id="noi-dung")


# ---- hash neutrality pin (Decision A pattern) --------------------------------

def test_pic_id_is_outside_the_canonical_hash():
    steps = (_step("s1", "nghien-cuu"), _step("s2", "noi-dung", deps=["s1"]))
    with_pic = DecomposedTask(steps=steps, pic_id="noi-dung")
    without_pic = DecomposedTask(steps=steps)
    assert decomposition_content_hash(with_pic) == decomposition_content_hash(without_pic)
