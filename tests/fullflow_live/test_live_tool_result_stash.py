"""Nhóm L4 — kết quả công cụ quá khổ đi qua VÒNG LẶP THẬT với model thật.

Suite offline (`tests/test_oversized_tool_result_handoff.py`) đã đo cạn `stash_if_oversized`
và một lời gọi `_execute_call` đơn lẻ. Cái nó KHÔNG đo được, và chỉ chỗ này đo được: sau khi
nhận placeholder, model thật có ĐỌC được nó như một bản xem trước và làm việc tiếp không —
hay nó coi phần preview là toàn bộ dữ liệu rồi kết luận sai. Placeholder được viết chính là
để chống điều đó (`tool_result_stash` docstring: "deliberately NOT silent"), nhưng với model
script thì lời hứa ấy chưa từng bị thử.

Vì sao tiêm `tools_map` thay vì đợi một công cụ thật trả >12.000 ký tự: đã quét cạn registry
(2026-09-01) và KHÔNG công cụ keyless nào vượt nổi ngưỡng — `history.search` ~4,7k,
`web.scrape` 8.000 và cần Firecrawl; 4 công cụ không trần đều cần credential.
`tools_map` là tham số thường của vòng lặp, và chính product code khai báo phải
chịu được "a hand-built tools_map" (`thin_tool_loop.py:339-341`) — nên đây là seam SẴN CÓ.
Thứ được thay chỉ là NGUỒN của chuỗi dài; từ `stash_if_oversized` trở xuống là sản phẩm
nguyên vẹn: stash thật, vòng lặp thật, model thật đọc placeholder thật.

KHÔNG hạ `TOOL_RESULT_STASH_CHARS` cho vừa công cụ — ngưỡng giữ nguyên 12.000, chuỗi dài
vượt ngưỡng là do fixture cấp.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.tool_result_stash import (
    STASH_PREVIEW_CHARS,
    TOOL_RESULT_STASH_CHARS,
    tool_results_dir,
)
from my_crew.runtime_backends.thin_tool_loop import run_thin_loop
from my_crew.runtime_backends.tool_call_context import tool_call_context

TASK_ID = "live-stash-task"
STEP_ID = "live-stash-step"

#: Mã chỉ xuất hiện ở PHẦN ĐUÔI của kết quả — tức phần bị cắt khỏi prompt. Nếu model nhắc
#: tới nó thì hoặc payload đã lọt vào context (đúng thứ stash sinh ra để chặn), hoặc model
#: bịa. Cả hai đều là fail.
TAIL_MARKER = "MA-CUOI-BANG-7Q4Z"

#: Mã nằm trong 2.000 ký tự đầu — phần model ĐƯỢC thấy. Dùng để phân biệt "model đọc được
#: preview" với "model chẳng đọc được gì".
HEAD_MARKER = "MA-DAU-BANG-3K8T"


def _oversized_rows() -> str:
    """Một bảng tồn kho dài hơn ngưỡng stash, nội dung thật chứ không phải 'x' lặp.

    Nội dung phải đọc được thì phép đo mới có nghĩa: model cần hiểu nó đang cầm một bản
    xem trước của dữ liệu có thật, và điều đó không kiểm chứng được bằng một chuỗi rác.
    """
    head = f"BẢNG TỒN KHO KHO A — mã lô đầu bảng: {HEAD_MARKER}\n"
    rows = [
        f"{i:04d} | mã hàng VT-{i:04d} | tồn {100 + (i % 37)} thùng | "
        f"kho {'A' if i % 2 else 'B'} | trạng thái {'đủ' if i % 3 else 'sắp hết'}"
        for i in range(1, 400)
    ]
    tail = f"\nmã lô cuối bảng: {TAIL_MARKER}\n"
    text = head + "\n".join(rows) + tail
    assert len(text) > TOOL_RESULT_STASH_CHARS, (
        f"fixture phải vượt ngưỡng stash mới đo được gì: {len(text)} <= "
        f"{TOOL_RESULT_STASH_CHARS}"
    )
    return text


class _Ctx:
    persona = "Bạn là nhân viên kho, trả lời ngắn gọn bằng tiếng Việt."
    project = "Kiểm kê kho"
    memory = ""
    capability = ""


@pytest.fixture
def stash_root(monkeypatch, tmp_path):
    """Trỏ root dùng chung vào tmp — không được đụng `.data/` thật của người dùng."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


@pytest.mark.live_slow
def test_l4_an_oversized_tool_result_is_stashed_and_the_model_reads_the_preview(
    stash_root, live_api_key, journey_budget,
):
    """Kết quả >12k đi qua vòng lặp thật: prompt bị chặn, đĩa giữ đủ, model vẫn làm việc.

    Bốn khẳng định, không cái nào thừa:

    - **payload KHÔNG vào messages.** Đây là lý do stash tồn tại: `messages` được gửi lại
      MỖI vòng, nên một kết quả quá khổ lọt vào sẽ nhân kích thước với số vòng còn lại.
      Đo bằng `TAIL_MARKER` — mã chỉ có ở phần đuôi đã bị cắt.
    - **đĩa giữ NGUYÊN VĂN.** Nửa còn lại của lời hứa: chặn context mà vẫn không mất dữ
      liệu. Thiếu khẳng định này thì stash không khác gì cắt cụt.
    - **model ĐỌC được bản xem trước.** Chỉ đo được với model thật. Placeholder tự nói nó
      là bản một phần; nếu lời hứa đó có tác dụng thì model dùng được dữ liệu trong phần
      đầu (`HEAD_MARKER`) thay vì bó tay.
    - **vòng lặp về đích có chi phí > 0.** Chống rỗng: một vòng lặp chết trước khi gọi
      model cũng thoả ba khẳng định trên vì những lý do chẳng liên quan gì tới stash.
    """
    from my_crew.config.config_builders import build_settings_from_dict

    payload = _oversized_rows()
    calls: list[dict] = []

    def _inventory_dump(args):
        calls.append(dict(args or {}))
        return payload

    settings = build_settings_from_dict({
        "openrouter_api_key": live_api_key,
        "openrouter_model": "anthropic/claude-haiku-4.5",
        "data_dir": stash_root,
    })

    with tool_call_context(
        agent_id="analyst", task_id=TASK_ID, step_id=STEP_ID, iteration=0
    ):
        text, cost = run_thin_loop(
            title=(
                "Gọi công cụ history_search để lấy bảng tồn kho, rồi cho biết mã lô ghi ở "
                "ĐẦU bảng là gì. Nếu dữ liệu bạn nhận được chỉ là một phần, hãy nói rõ "
                "điều đó."
            ),
            handoff="", context=_Ctx(), settings=settings,
            tools_map={"history_search": _inventory_dump}, max_steps=4,
        )

    # Không truyền `status`: ca này chạy thẳng vòng lặp chứ không qua một task của fleet,
    # nên nó không có task-status payload thật để đóng góp cho baseline recorder.
    journey_budget.note_cost(cost or 0.0)

    assert calls, (
        "model chưa từng gọi công cụ, nên chưa có kết quả quá khổ nào để stash — phép đo "
        f"rỗng. Vòng lặp trả về: {text!r}"
    )

    stashed = sorted(tool_results_dir(stash_root, TASK_ID).glob("*.txt"))
    assert stashed, (
        f"kết quả {len(payload)} ký tự vượt ngưỡng {TOOL_RESULT_STASH_CHARS} nhưng không "
        f"file stash nào được ghi ở {tool_results_dir(stash_root, TASK_ID)}"
    )
    on_disk = stashed[0].read_text(encoding="utf-8")
    assert TAIL_MARKER in on_disk and HEAD_MARKER in on_disk, (
        "artifact stash phải giữ NGUYÊN VĂN cả đầu lẫn đuôi — mất đuôi nghĩa là stash chỉ "
        f"là một phép cắt cụt tốn thêm file. Dài {len(on_disk)} ký tự."
    )

    assert TAIL_MARKER not in text, (
        f"mã cuối bảng {TAIL_MARKER!r} nằm ngoài {STASH_PREVIEW_CHARS} ký tự đầu, nên nó "
        "chỉ có thể tới đây nếu payload đã lọt vào messages (đúng thứ stash sinh ra để "
        f"chặn) hoặc model bịa. Kết quả: {text!r}"
    )
    assert HEAD_MARKER in text, (
        "model không nêu được mã lô đầu bảng dù nó nằm gọn trong phần preview — "
        "placeholder đã không truyền đạt được rằng đây là bản xem trước dùng được. "
        f"Kết quả: {text!r}"
    )
    assert (cost or 0.0) > 0, (
        f"vòng lặp tốn $0 nghĩa là chưa từng gọi model thật; phép đo rỗng. cost={cost!r}"
    )
