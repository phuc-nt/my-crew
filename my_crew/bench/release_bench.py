"""Release-comparison bench: the same briefs, a simulated web, a faithful model.

`pipeline_bench` measures what the code decides to SPEND; this module measures what
the code manages to DELIVER for that spend, so two revisions can be compared axis by
axis without a network or a daemon. The simulated web is fixed across revisions —
only the code under test changes — and it reproduces the two behaviours that decided
the v78 C3 benchmark:

- a query longer than a real search box tolerates comes back as a source-failure
  sentinel (live task 647ee49de19d: the raw-goal query was rejected with HTTP 422);
- a query naming exactly ONE subject comes back with usable data for it, anything
  broader comes back as a thin overview with no numbers.

The scripted model is FAITHFUL rather than replayed: it writes data for exactly the
subjects whose results appear in its context and nothing else. That is the property
the live self-check enforces (no unsourced numbers), so coverage here moves for the
same reason it moves in production — because the code did or did not put the right
search results in front of the model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any
from unittest import mock

from my_crew.bench.brief_suite import ALL_CASES
from my_crew.bench.pipeline_bench import BriefCase
from my_crew.runtime.sprint_runner import build_sprint_work, resolve_entities

#: Longest query the simulated web accepts, mirroring the live provider's rejection
#: of the raw-goal kitchen-sink query. Deliberately looser than the pipeline's own
#: overview cutoff: an honest single-sentence brief must pass, while a multi-clause
#: goal sent verbatim — the C3 failure — must bounce.
MAX_WEB_QUERY_WORDS = 20

#: Marker the simulated web puts in front of usable data. The faithful model covers a
#: subject if and only if this marker names it somewhere in the conversation.
DATA_MARK = "DỮ LIỆU"

_BROKEN_SOURCE = "[LỖI NGUỒN TÌM KIẾM]"


@dataclass(frozen=True)
class ReleaseMetric:
    """What one brief cost and what it delivered, on the revision under test."""

    case: str
    llm_calls: int
    searches: int
    entities_parsed: int
    coverage_expected: int
    coverage_closed: int
    gaps_open: int
    has_thieu_note: bool
    output_chars: int
    queries: tuple[str, ...]
    #: Which effort tier this row was run at. The suite runs every brief at "medium"
    #: (the pre-P3 behaviour, so the numbers stay comparable to older reports) and every
    #: brief AGAIN at "low", because what P3 claims is a saving and a saving is a delta
    #: between two tiers — one tier alone cannot show it.
    effort: str = "medium"
    #: Revise rounds actually run. `llm_calls` already implies it, but only if the
    #: reader knows the pipeline is draft-plus-revises; naming it makes a budget change
    #: legible without that knowledge.
    revise_rounds: int = 0
    #: The model ROLE the tier selects — the mechanism by which "low" is cheaper. A tier
    #: that stopped naming its cheap role would keep every other number identical.
    model_role: str = ""


def simulated_web(subjects: list[str]):
    """A deterministic search stub over a fixed body of knowledge about `subjects`."""

    def render(query: str) -> str:
        if len(query.split()) > MAX_WEB_QUERY_WORDS:
            return f"{_BROKEN_SOURCE} (truy vấn: {query}) HTTP Error 422: Unprocessable Entity"
        named = [s for s in subjects if s.lower() in query.lower()]
        if len(named) == 1:
            subject = named[0]
            return (
                f"KẾT QUẢ TÌM KIẾM (truy vấn: {query}):\n"
                f"{DATA_MARK} {subject}: giá tháng 5 USD, có gói miễn phí "
                f"(nguồn: https://example.com/{subject.lower().replace(' ', '-')})"
            )
        # Zero subjects named, or several at once: a generic overview holds no numbers
        # a faithful model could cite — the "thin" side of the two-sided web.
        return f"KẾT QUẢ TÌM KIẾM (truy vấn: {query}):\nBài tổng quan chung, không có số liệu."

    return render


class _FaithfulLlm:
    """Writes data for exactly the subjects whose results are in its context.

    The live model is held to this by the self-check (no numbers without a traceable
    source), so simulating it this way makes coverage a function of the CODE's search
    decisions — the thing a release comparison needs to isolate.
    """

    def __init__(self, subjects: list[str]) -> None:
        self._subjects = list(subjects)
        self.covered: list[str] = []
        self.calls = 0

    def complete(self, messages: list[dict[str, str]], **_kw: Any) -> SimpleNamespace:
        self.calls += 1
        text = "\n".join(str(m.get("content", "")) for m in messages)
        self.covered = [s for s in self._subjects if f"{DATA_MARK} {s}" in text]
        if self.covered:
            reply = "| Mục | Giá | Nguồn |\n" + "\n".join(
                f"| {s} | 5 USD/tháng | https://example.com/{i} |"
                for i, s in enumerate(self.covered)
            )
        else:
            reply = "Chưa thu thập được số liệu nào từ nguồn tìm kiếm."
        return SimpleNamespace(content=reply, cost_usd=0.0, prompt_tokens=0, completion_tokens=0)


def bench_case(case: BriefCase, *, effort: str = "medium") -> ReleaseMetric:
    """Run one brief through the real pipeline against the simulated web.

    `effort` is passed straight to the runner rather than simulated here: the tier's
    whole effect lives inside `build_sprint_work` (which model role it names, how much
    search/revise budget it allows), so measuring it any other way would be measuring a
    reimplementation.
    """
    from my_crew.runtime.sprint_runner import LOW_EFFORT_MODEL_ROLE
    parsed = resolve_entities(case.goal, case.acceptance)
    # The simulated web's knowledge is the suite's expected subjects — fixed across
    # revisions so a revision that fails to PARSE them also fails to FIND them, which
    # is exactly what happened live. Cases that deliberately omit expectations (the
    # spend-cap brief) fall back to whatever the revision parsed.
    subjects = list(case.expected_entities) or parsed
    llm = _FaithfulLlm(subjects)
    web = simulated_web(subjects)
    seen: list[str] = []

    def _prefetch(_loaded: Any, _settings: Any, queries: list[str]) -> str:
        seen.extend(queries)
        return "\n".join(web(q) for q in queries)

    with mock.patch("my_crew.llm.client.LlmClient", lambda _settings: llm):
        work = build_sprint_work(
            loaded=SimpleNamespace(soul="", project="", web_search=True),
            settings=SimpleNamespace(),
            acceptance=case.acceptance,
            prefetch=_prefetch,
            effort=effort,
        )
        text, _cost = work(case.goal, "", None)

    covered = set(llm.covered)
    return ReleaseMetric(
        case=case.name,
        llm_calls=llm.calls,
        searches=len(seen),
        entities_parsed=len(parsed),
        coverage_expected=len(subjects),
        coverage_closed=len(covered),
        gaps_open=sum(1 for s in subjects if s not in covered),
        has_thieu_note="PHẦN THIẾU" in (text or ""),
        output_chars=len(text or ""),
        queries=tuple(seen),
        effort=effort,
        # draft is call 1; every call after it is a revise round.
        revise_rounds=max(0, llm.calls - 1),
        model_role=LOW_EFFORT_MODEL_ROLE if effort == "low" else "content",
    )


#: Effort tiers the suite measures. "high" is deliberately absent: P3 runs it exactly as
#: medium, so a third identical column would be noise standing in for a signal.
BENCHED_EFFORTS = ("medium", "low")

#: Bumped whenever a compared field is added or its meaning changes, so `compare_reports`
#: can refuse a stale baseline instead of silently reading a missing field as a change.
FORMAT_VERSION = 2


def _run_once(cases: tuple[BriefCase, ...]) -> dict[str, Any]:
    """One full pass: every brief at every benched tier.

    Keyed `<case>@<effort>` so the low and medium rows of one brief sit side by side in
    a sorted report and diff against their own counterpart, never against each other.
    """
    return {
        f"{case.name}@{effort}": asdict(bench_case(case, effort=effort))
        for case in cases
        for effort in BENCHED_EFFORTS
    }


def run_suite(cases: tuple[BriefCase, ...] = ALL_CASES, *, repeats: int = 1) -> dict[str, Any]:
    """The whole suite as one JSON-ready report, verified stable over `repeats` runs.

    The pipeline is supposed to be deterministic — scripted model, stubbed web, no
    clock — so any run-to-run difference is itself a defect worth failing loudly on.
    """
    first = _run_once(cases)
    for _ in range(max(0, repeats - 1)):
        if _run_once(cases) != first:
            raise RuntimeError("release bench is non-deterministic between repeats")
    return {"schema": 1, "format_version": FORMAT_VERSION, "cases": first}


#: The axes a release comparison reports on. `queries` stays out — it is evidence for
#: reading a diff, not a number to delta.
COMPARED_FIELDS = (
    "llm_calls",
    "searches",
    "entities_parsed",
    "coverage_closed",
    "gaps_open",
    "has_thieu_note",
    "output_chars",
    "revise_rounds",
    "model_role",
)


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-case, per-axis rows where the two reports differ, plus cases only one has.

    A version mismatch is refused rather than compared. The one exception is a baseline
    with NO `format_version` at all: that is a report from before the field existed, and
    refusing it would block exactly the comparison this mode exists for — measuring the
    current revision against an older tag. What must never happen is two reports that
    BOTH claim a version, disagree, and get compared field by field anyway.

    Such an old baseline has flat `case` keys, while the current one has `case@effort`.
    Comparing them raw turns every case into two "shape changed" rows and buries the
    question actually being asked — did spend move. The old runs measured what is now
    the `medium` tier, so its keys are read as `case@medium`; the `low` rows then show
    as candidate-only, which is true (that tier did not exist) and is one row per case
    instead of three.
    """
    b_ver = baseline.get("format_version")
    c_ver = candidate.get("format_version")
    if b_ver is not None and c_ver is not None and b_ver != c_ver:
        raise ValueError(
            f"release report format_version lệch nhau ({b_ver} vs {c_ver}) — "
            "chạy lại baseline bằng bản script hiện tại trước khi so"
        )

    rows: list[dict[str, Any]] = []
    base_cases = dict(baseline.get("cases", {}))
    cand_cases = dict(candidate.get("cases", {}))
    # Chỉ bắc cầu khi baseline là bản CŨ còn candidate là bản MỚI. Hai bên cùng không
    # khai phiên bản là hai báo cáo cùng thời — đổi tên khoá một bên khi đó là tự tạo
    # ra lệch khoá chứ không phải xoá lệch khoá.
    if b_ver is None and c_ver is not None:
        base_cases = {(k if "@" in k else f"{k}@medium"): v
                      for k, v in base_cases.items()}
    for name in sorted(set(base_cases) | set(cand_cases)):
        a, b = base_cases.get(name), cand_cases.get(name)
        if a is None or b is None:
            rows.append({"case": name, "field": "presence",
                         "baseline": a is not None, "candidate": b is not None})
            continue
        for field in COMPARED_FIELDS:
            if a.get(field) != b.get(field):
                rows.append({"case": name, "field": field,
                             "baseline": a.get(field), "candidate": b.get(field)})
    return rows
