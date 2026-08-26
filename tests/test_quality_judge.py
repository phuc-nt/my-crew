"""Judge chấm chất lượng: chống thiên vị, và đếm phiếu đúng bên.

Toàn bộ file chạy offline bằng LLM giả. Một judge thật không thể dùng để test chính nó:
nó không tất định, nên một bài kiểm tra chạy bằng model thật sẽ xanh/đỏ theo tâm trạng
của model chứ không theo tính đúng của phần cộng phiếu — mà phần cộng phiếu mới là chỗ
lỗi âm thầm (quy phiếu sai bên thì bảng kết quả vẫn đẹp, chỉ là ngược).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from my_crew.bench import quality_judge as judge


@dataclass
class _Reply:
    content: str


class _StubLlm:
    """LLM giả trả lời theo một hàm quyết định, đồng thời ghi lại mọi prompt đã nhận."""

    def __init__(self, decide):
        self._decide = decide
        self.prompts: list[str] = []
        self.models: list[str] = []

    def complete(self, messages, model=None, **_kwargs):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        self.models.append(model)
        return _Reply(self._decide(prompt))


def _always(winner: str):
    return lambda _p: json.dumps({"winner": winner, "ly_do": "vì thế"})


def _picks_the_side_containing(marker: str):
    """Chấm theo NỘI DUNG: bên nào chứa `marker` thì bên đó thắng.

    Đây là judge "đúng" cho test — nó không quan tâm vị trí, nên nếu phiếu vẫn bị quy
    sai bên thì lỗi nằm ở phần gỡ mù chứ không ở model."""
    def _decide(prompt: str) -> str:
        head, tail = prompt.split("--- BẢN B ---", 1)
        winner = "A" if marker in head.split("--- BẢN A ---", 1)[1] else "B"
        return json.dumps({"winner": winner, "ly_do": "có số liệu"})
    return _decide


# --- gỡ mù: phiếu phải về đúng bản ----------------------------------------------------


def test_votes_follow_the_content_not_the_position():
    llm = _StubLlm(_picks_the_side_containing("SỐ-LIỆU"))
    verdict = judge.judge_case(llm, "c", "đề", "bản cũ nói chung chung",
                               "bản mới có SỐ-LIỆU", votes=5,
                               rng=random.Random(1))
    assert verdict.winner == "candidate", verdict
    assert set(verdict.votes) == {"candidate"}, verdict.votes
def test_the_position_bias_of_a_judge_that_always_picks_a_cancels_out():
    """Bài kiểm tra quan trọng nhất của lớp xáo thứ tự.

    Model có thiên vị vị trí thật. Nếu bỏ xáo, một judge luôn chọn A sẽ trao 100% phiếu
    cho bất kỳ bản nào ta xếp trước — nghĩa là bảng kết quả đo thứ tự tham số, không đo
    chất lượng. Có xáo thì thiên vị đó phải tan về ~50/50.

    Assert vào TỈ LỆ chứ không vào nhãn thắng: 200 phiếu tung đồng xu công bằng vẫn
    lệch vài chục phiếu về một phía, nên đòi hoà tuyệt đối là đòi một tính chất mà
    ngay cả cách xáo đúng cũng không có."""
    llm = _StubLlm(_always("A"))
    verdict = judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=200,
                               rng=random.Random(7))
    share = verdict.votes.count("baseline") / len(verdict.votes)
    assert 0.35 < share < 0.65, share


def test_the_prompt_never_carries_the_labels():
    """Mù nhãn: chữ "baseline"/"candidate" lọt vào prompt là judge biết bên nào là bản
    mới, và ba lớp chống thiên vị phía trên thành vô nghĩa."""
    llm = _StubLlm(_always("A"))
    judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=4, rng=random.Random(2))
    joined = "\n".join(llm.prompts).lower()
    assert "baseline" not in joined and "candidate" not in joined, joined[:400]


def test_both_orderings_actually_occur_across_votes():
    """Xáo chỉ có tác dụng nếu nó thật sự đảo. Ghim bằng cách nhìn vị trí nội dung
    trong chính các prompt đã gửi, chứ không tin vào việc có gọi `random`."""
    llm = _StubLlm(_always("A"))
    judge.judge_case(llm, "c", "đề", "AAA", "BBB", votes=12, rng=random.Random(3))
    firsts = {p.split("--- BẢN A ---", 1)[1].split("--- BẢN B ---", 1)[0].strip()
              for p in llm.prompts}
    assert firsts == {"AAA", "BBB"}, firsts


# --- hình dạng prompt ------------------------------------------------------------------


def test_the_prompt_states_the_goal_and_every_rubric_criterion():
    prompt = judge.build_prompt("So sánh 3 nhà cung cấp", "x", "y")
    assert "So sánh 3 nhà cung cấp" in prompt
    for key, _desc in judge.RUBRIC:
        assert key in prompt, key


def test_no_rubric_criterion_rewards_length():
    """Rủi ro cố hữu của judge tự do là thưởng cho bản dài hơn. Rubric là chỗ duy nhất
    chặn được điều đó, nên không tiêu chí nào được nói về độ dài."""
    text = " ".join(f"{k} {d}" for k, d in judge.RUBRIC).lower()
    for banned in ("dài", "độ dài", "số từ", "chi tiết hơn"):
        assert banned not in text, banned


def test_the_judge_model_defaults_to_a_different_family_from_the_task_model():
    llm = _StubLlm(_always("A"))
    judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=1)
    assert set(llm.models) == {judge.DEFAULT_JUDGE_MODEL}
    assert not judge.DEFAULT_JUDGE_MODEL.startswith(("anthropic/", "openai/"))


def test_an_explicit_model_overrides_the_default():
    llm = _StubLlm(_always("A"))
    judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=2, model="x/y")
    assert set(llm.models) == {"x/y"}


# --- lời đáp hỏng ---------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "xin lỗi tôi không chấm được", "{ hỏng",
                                 '{"winner": "C"}'])
def test_an_unreadable_reply_costs_one_sample_not_the_whole_run(bad):
    """Một phiếu hỏng phải thành "hoa" chứ không phải ngoại lệ: nổ ở case thứ 9 sẽ vứt
    luôn 8 case đã trả tiền chấm trước đó."""
    llm = _StubLlm(lambda _p: bad)
    verdict = judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=3)
    assert verdict.winner == "hoa"
    assert set(verdict.votes) == {"hoa"}, verdict.votes


def test_a_json_reply_wrapped_in_prose_is_still_read():
    llm = _StubLlm(lambda _p: 'Đây là kết quả:\n{"winner":"A","ly_do":"rõ hơn"}\nHết.')
    verdict = judge.judge_case(llm, "c", "đề", "cũ", "mới", votes=1,
                               rng=random.Random(0))
    assert verdict.winner in {"baseline", "candidate"}
    assert verdict.notes == ("rõ hơn",)


# --- toàn bộ lượt chấm -----------------------------------------------------------------


def _write(tmp_path, name, files):
    d = tmp_path / name
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.md").write_text(text, encoding="utf-8")
    return d


def test_a_case_missing_on_one_side_is_skipped_and_reported(tmp_path):
    """Chỉ một bên có thì không có gì để so. Lặng lẽ tính nó thắng là bịa ra kết luận,
    nên nó phải nằm ở `skipped` và không được vào bảng phiếu."""
    base = _write(tmp_path, "base", {"a": "cũ", "b": "chỉ bên cũ có"})
    cand = _write(tmp_path, "cand", {"a": "mới có SỐ-LIỆU", "c": "chỉ bên mới có"})
    llm = _StubLlm(_picks_the_side_containing("SỐ-LIỆU"))

    report = judge.run_judging(llm, base, cand, votes=3, rng=random.Random(5))

    assert [c["case"] for c in report["cases"]] == ["a"]
    assert report["skipped"] == ["b", "c"]
    assert report["tally"] == {"baseline": 0, "candidate": 1, "hoa": 0}


def test_the_report_records_which_judge_and_how_many_votes(tmp_path):
    """Con số chấm chất lượng chỉ tái lập được nếu biết ai chấm và chấm mấy phiếu."""
    base = _write(tmp_path, "base", {"a": "cũ"})
    cand = _write(tmp_path, "cand", {"a": "mới"})
    llm = _StubLlm(_always("A"))
    report = judge.run_judging(llm, base, cand, votes=5, model="x/y",
                               rng=random.Random(0))
    assert report["judge_model"] == "x/y"
    assert report["votes_per_case"] == 5
    assert report["format_version"] == judge.FORMAT_VERSION


def test_reading_a_missing_directory_fails_loudly(tmp_path):
    """Gõ sai đường dẫn phải nổ ngay. Trả về rỗng thì lượt chấm "thành công" với 0 case
    và người đọc tưởng hai bản ngang nhau."""
    with pytest.raises(ValueError, match="không phải thư mục"):
        judge.load_deliverables(tmp_path / "khong-ton-tai")


def test_the_presentation_order_alternates_every_vote():
    """Triệt tiêu thiên vị vị trí phải CHẮC CHẮN, không phải chắc theo xác suất.

    Bốc ngẫu nhiên độc lập từng phiếu thì với 3 phiếu có ~24% khả năng cả ba cùng một
    thứ tự — và đó đúng là những lần mà một giám khảo thiên vị vị trí thắng 3-0 mà bảng
    kết quả không có dấu hiệu gì. Luân phiên thì số lần mỗi bản đứng trước lệch nhau
    tối đa một phiếu, mọi lần chạy, không phụ thuộc seed.
    """
    seen: list[str] = []

    class _Recorder:
        def complete(self, messages, **_kw):
            seen.append(messages[-1]["content"])
            return SimpleNamespace(content='{"winner":"hoa","reason":"r"}')

    judge.judge_case(_Recorder(), "c", "đề", "BASELINE_TEXT", "CANDIDATE_TEXT", votes=6)

    baseline_first = [p.index("BASELINE_TEXT") < p.index("CANDIDATE_TEXT") for p in seen]
    assert len(baseline_first) == 6
    assert baseline_first.count(True) == baseline_first.count(False) == 3, baseline_first
    # Luân phiên chứ không phải "gộp lại thì cân": hai phiếu liền nhau luôn ngược nhau.
    assert all(a != b for a, b in zip(baseline_first, baseline_first[1:], strict=False))
