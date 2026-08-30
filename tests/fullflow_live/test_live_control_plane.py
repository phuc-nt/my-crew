"""Nhóm E — control-plane API (P2) với model thật.

Cái mà suite scripted KHÔNG chứng minh được: `/api/control-plane/delegate` gọi thẳng
`preview_assign_team_task`, tức là nó phải chạy qua tầng decompose bằng model thật để ra
được một kế hoạch có hash. Với LLM giả, `plan_hash` chỉ là hash của một DAG do script
dựng sẵn — ràng buộc hash đúng về mặt cơ học nhưng chưa từng bị thử với một kế hoạch mà
model thật sinh ra.

E2 cố tình rẻ: nó dừng ở preview, không pump, nên chỉ trả tiền cho một lượt decompose.
Ràng buộc chống TOCTOU là thứ phải đúng NGAY CẢ KHI kế hoạch khác nhau mỗi lần chạy —
đó chính là lý do nó phải được đo bằng model thật chứ không phải kế hoạch cố định.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


def _delegate(**body) -> dict:
    """Gọi thẳng route handler (không qua TestClient): tầng cần đo là hợp đồng
    delegate + ràng buộc hash, không phải tầng auth/HTTP đã có suite riêng."""
    from my_crew.server.routes_control_plane import post_delegate

    return post_delegate(
        brief=body.get("brief", ""),
        task_id=body.get("task_id", ""),
        plan_hash=body.get("plan_hash", ""),
        confirm=body.get("confirm", False),
        room_id=body.get("room_id", ""),
    )


# --- E1: một cửa ngoài SPA, trọn vòng đời -------------------------------------------


@pytest.mark.live_slow
def test_e1_an_outside_caller_delegates_and_polls_status_end_to_end(live_run):
    """Caller ngoài (script/CLI) giao việc một bước rồi poll trạng thái.

    Đây là case duy nhất chứng minh hợp đồng HTTP của P2 thật sự dẫn tới một việc chạy
    được: brief → decompose thật → confirm → ticker chạy → `GET /tasks/{id}` khớp với
    store. Assert vào bản ghi (task tồn tại, đúng id, có bước) chứ không vào chữ model
    viết ra."""
    run = live_run()
    out = _delegate(
        brief="Viết giúp bản mô tả phạm vi ngắn cho tính năng đăng nhập bằng số điện thoại.",
        confirm=True,
    )
    assert out["confirmed"] is True, out
    task_id = out["task_id"]
    assert task_id, out

    rows = run.h.task_rows()
    assert [r["id"] for r in rows] == [task_id], rows

    steps_before = run.h.step_rows(task_id)
    assert steps_before, "việc đã confirm phải có kế hoạch với ít nhất một bước"
    assert all(s["status"] == "pending" for s in steps_before), steps_before

    # Ticker chỉ tiến MỘT hành động mỗi tick, nên số tick phải đủ cho DAG này chạy được
    # ít nhất một bước — assert vào tiến độ thật, không phải vào "có tồn tại bước nào".
    run.h.pump(ticks=3)

    from my_crew.server.control_plane_views import build_task_status

    status = build_task_status(task_id)
    assert status is not None, f"vừa giao xong mà status trả None: {task_id}"
    assert status.get("task_id") == task_id or status.get("id") == task_id, status

    steps_after = run.h.step_rows(task_id)
    assert any(s["status"] != "pending" for s in steps_after), (
        "việc giao qua control-plane phải thật sự được ticker nhặt lên và chạy — mọi "
        f"bước vẫn `pending` nghĩa là nó nằm im: {steps_after}"
    )
    assert run.cost() > 0, "decompose bằng model thật phải ghi lại chi phí thật"


# --- E2: ràng buộc hash, chống TOCTOU -----------------------------------------------


def test_e2_a_confirm_with_a_stale_plan_hash_is_refused(live_run):
    """Ràng buộc hash phải từ chối một kế hoạch KHÁC với kế hoạch đã preview.

    Vì sao phải đo bằng model thật: `plan_hash` được tính trên DAG mà decompose sinh ra.
    Với model giả, DAG là hằng số nên phép so hash chưa bao giờ gặp một kế hoạch thật.
    Ở đây preview chạy thật, rồi confirm bằng một hash sai — phải là 409, và việc phải
    KHÔNG được dispatch.

    Case dừng ở preview: không pump, nên chỉ tốn đúng một lượt decompose."""
    run = live_run()
    preview = _delegate(brief="Tóm tắt giúp anh 3 rủi ro chính khi mở thêm chi nhánh mới.")
    task_id = preview["task_id"]
    assert task_id and preview["plan_hash"], preview
    assert preview["confirmed"] is False, preview

    with pytest.raises(HTTPException) as excinfo:
        _delegate(task_id=task_id, plan_hash="0" * 64, confirm=True)
    assert excinfo.value.status_code == 409, excinfo.value.detail

    assert not any(
        s["status"] == "running" for s in run.h.step_rows(task_id)
    ), "confirm bằng hash sai không được phép làm chạy bất cứ bước nào"


def test_e3_a_confirm_without_a_plan_hash_is_refused(live_run):
    """Thiếu hash không được coi là "bỏ qua kiểm tra".

    Một client viết ẩu (quên echo `plan_hash`) phải bị từ chối chứ không được rơi vào
    đường confirm-không-điều-kiện. Không gọi model — case này chỉ đo tầng hợp đồng."""
    live_run()
    with pytest.raises(HTTPException) as excinfo:
        _delegate(task_id="deadbeefcafe", plan_hash="", confirm=True)
    assert excinfo.value.status_code == 400, excinfo.value.detail
