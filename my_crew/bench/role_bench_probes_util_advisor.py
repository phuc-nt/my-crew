"""`util` and `advisor` role probes.

Util is the cheap-tier role whose calls fail OPEN in production — memory extraction
returns nothing, slot extraction hands back the raw answer, reflection defaults to
"nothing learned" — so a weak model here is invisible to the ticker and only shows up
as a fleet that never remembers, never maps "quản lý dự án" to `pm`, never learns. The
probes make that silence visible.

Advisor is scored both ways: a clean fragment must earn silence (a chatty advisor
pollutes a working agent's context); a three-times-repeated failing call must earn a
note (that pattern is the reason the role exists).
"""

from __future__ import annotations

from typing import Any

from my_crew.bench.role_bench_probe_kit import Probe, ProbeOutcome

_MEMORY_REPORT = (
    "Báo cáo tuần 36 — dự án Alpha.\n"
    "- Sprint 12 trượt 3 ngày do API thanh toán của đối tác đổi schema không báo trước.\n"
    "- CEO quyết định chốt ngân sách marketing quý 4 ở mức 1,2 tỷ, ưu tiên kênh Zalo.\n"
    "- Rủi ro lặp lại: đối tác thanh toán đã đổi schema 2 lần trong 3 tháng.\n"
    "- Đang chờ phòng pháp chế duyệt hợp đồng, xin CEO nhắc giúp."
)


def _memory_probe() -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.agent.memory_extractor import make_llm_costed_extractor

        facts, cost = make_llm_costed_extractor(client)(_MEMORY_REPORT)
        if not facts:
            return ProbeOutcome.failed("empty", "no facts extracted", cost)
        blob = " ".join(facts).lower()
        if "alpha" not in blob and "1,2 tỷ" not in blob and "1.2 tỷ" not in blob:
            return ProbeOutcome.failed("wrong", "facts name neither Alpha nor the budget: "
                                       + " | ".join(facts), cost)
        if any(w in blob for w in ("pháp chế", "nhắc giúp", "xin ceo")):
            return ProbeOutcome.failed("wrong", "kept the internal-process line: "
                                       + " | ".join(facts), cost)
        return ProbeOutcome.passed(f"{len(facts)} facts", cost)

    return Probe("util", "memory/weekly-report", run)


SLOT_CASES = [
    ("slot/verbatim", dict(field="framework", prompt="Bạn muốn dùng framework nào?",
                           answer="à để tôi dùng SCRUM nhé"),
     lambda v, ni: "" if (v.lower() == "scrum" and not ni) else f"got {v!r} new_intent={ni}"),
    ("slot/code-hint", dict(field="role", prompt="Vai trò của agent này là gì?",
                            answer="quản lý dự án",
                            hint="một trong: dev, pm, qa, sales"),
     lambda v, ni: "" if (v.lower() == "pm" and not ni) else f"got {v!r} new_intent={ni}"),
    ("slot/new-intent", dict(field="agent_id", prompt="Giao cho agent nào?",
                             answer="thôi, huỷ việc #99 đi"),
     lambda v, ni: "" if ni else f"treated a new request as the value {v!r}"),
]


def _slot_probe(name: str, kwargs: dict, check) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.agent.ops_chat import extract_slot_value

        value, cost, new_intent = extract_slot_value(client, **kwargs)
        problem = check(value, new_intent)
        if problem:
            return ProbeOutcome.failed("wrong", problem, cost)
        return ProbeOutcome.passed(f"value={value!r} new_intent={new_intent}", cost)

    return Probe("util", name, run)


_VAGUE_DIGEST = (
    "Việc: Bảng giá xe máy điện 2026\n"
    "Kết thúc: failed sau 3 lượt sửa\n"
    "- [failed] Tra giá 3 dòng xe chủ lực → analyst\n"
    "  Tiêu chí đạt ghi 'bảng giá đầy đủ'; mỗi lượt reviewer trượt vì một lý do khác: "
    "thiếu nguồn, thiếu ngày truy cập, thiếu phiên bản xe. Người làm không biết "
    "'đầy đủ' gồm những cột nào.\n"
    "- [done] Viết báo cáo → writer"
)
_TIMEOUT_DIGEST = (
    "Việc: Tổng hợp tin tức ngành\n"
    "Kết thúc: failed\n"
    "- [failed] Tra cứu tin tuần này → researcher\n"
    "  Công cụ tìm kiếm trả lỗi 503 ba lần liên tiếp, bước hết giờ. Tiêu chí và cách "
    "chia bước không có gì bất thường.\n"
)


def _reflection_probe(name: str, digest: str, expect_lesson: bool) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.agent.task_reflection import NOTHING_TOKEN, _build_prompt, is_durable_lesson
        from my_crew.bench.role_bench_probe_kit import complete_text

        text, cost, early = complete_text(
            client, [{"role": "user", "content": _build_prompt(digest, [])}], "util")
        if early:
            return early
        durable = is_durable_lesson(text)
        if expect_lesson and not durable:
            return ProbeOutcome.failed("wrong", "no durable lesson: " + text[:120], cost)
        if not expect_lesson and (durable or NOTHING_TOKEN not in text):
            return ProbeOutcome.failed("wrong", "drew a lesson from a 503: " + text[:120], cost)
        return ProbeOutcome.passed(text[:80], cost)

    return Probe("util", name, run)


_STEP = {"title": "Tra giá 3 dòng xe chủ lực", "step_id": "s1", "assigned_to": "analyst"}
_CLEAN_DELTA = (
    "[tool web_search] q='giá VinFast Evo200 2026' → 5 kết quả\n"
    "[tool open_url] vinfastauto.com/evo200 → 'Giá niêm yết 22.000.000đ, cập nhật 08/2026'\n"
    "[tool web_search] q='giá Yadea Ossy 2026' → 4 kết quả\n"
    "[tool open_url] yadea.com.vn/ossy → 'Giá 18.490.000đ'\n"
    "[note] Đã có 2/3 dòng kèm nguồn và ngày; còn Dat Bike.\n"
    "[tool web_search] q='giá Dat Bike Quantum 2026' → 3 kết quả\n"
    "[tool open_url] dat.bike/quantum → 'Giá từ 39.900.000đ'\n"
    "[note] Đủ 3 dòng. Lập bảng: dòng | giá | nguồn | ngày truy cập.\n"
) * 2
_LOOPING_DELTA = (
    "[tool open_url] https://vinfastauto.com/evo200 → ERROR 403 Forbidden\n"
    "[note] Thử lại.\n"
    "[tool open_url] https://vinfastauto.com/evo200 → ERROR 403 Forbidden\n"
    "[note] Thử lại lần nữa.\n"
    "[tool open_url] https://vinfastauto.com/evo200 → ERROR 403 Forbidden\n"
    "[note] Thử lại.\n"
    "[tool open_url] https://vinfastauto.com/evo200 → ERROR 403 Forbidden\n"
    "[note] Chắc mạng chập chờn, thử tiếp.\n"
) * 2


def _advisor_probe(name: str, delta: str, expect_note: bool) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        from my_crew.runtime.advisor_sweep import _ask_advisor

        verdict = _ask_advisor(delta, _STEP, None, client)
        if expect_note and verdict is None:
            return ProbeOutcome.failed("wrong", "silent on a 4x repeated 403 loop")
        if not expect_note and verdict is not None:
            return ProbeOutcome.failed("wrong", f"spoke on clean work: {verdict[0]} "
                                       + verdict[1][:100])
        return ProbeOutcome.passed("silent" if verdict is None else f"{verdict[0]}: "
                                   + verdict[1][:80])

    return Probe("advisor", name, run)


def util_probes() -> list[Probe]:
    probes = [_memory_probe()]
    probes += [_slot_probe(n, kw, chk) for n, kw, chk in SLOT_CASES]
    probes += [
        _reflection_probe("reflection/vague-acceptance", _VAGUE_DIGEST, True),
        _reflection_probe("reflection/tool-503", _TIMEOUT_DIGEST, False),
    ]
    return probes


def advisor_probes() -> list[Probe]:
    return [
        _advisor_probe("sweep/clean-work", _CLEAN_DELTA, False),
        _advisor_probe("sweep/repeated-403", _LOOPING_DELTA, True),
    ]
