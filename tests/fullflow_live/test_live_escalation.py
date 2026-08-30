"""Nhóm F — escalation về Manager agent (P3) với model thật.

Điểm khiến nhóm này đáng chạy live: task escalation được đúc bằng đường KHÔNG-decompose
(`create_task` + `set_plan` tự đặt hash), rồi giao lại cho ticker THẬT chạy. Nếu hash mà
`_wake_plan_hash` tính khác với hash mà `_verify_plan_hash` tính lại trên `TeamStep` thật,
việc sẽ kẹt ngay tick đầu — và đó là loại hỏng chỉ lộ ra khi có một agent thật nhận bước
và chạy nó bằng model thật, chứ không lộ ra với một model script.

F2/F3 là các phanh: chúng cố tình rẻ (không gọi model, không pump), nhưng chính chúng là
lưới regression cho ba cái phanh mà P3 dựng lên.
"""

from __future__ import annotations

import dataclasses

import pytest

from my_crew.runtime.manager_escalation import escalate_to_manager, is_escalation_origin

#: Một worker CÓ trong roster của cast — `resolve_manager_id` mặc định rơi về
#: `coordinator_id`, mà `assignable_staff` loại điều phối viên ra khỏi danh sách nhận
#: việc, nên một fleet không cấu hình `manager_id` sẽ degrade chứ không đúc task. Case
#: happy-path phải chỉ đích danh một nhân sự thật.
MANAGER_ID = "analyst"


def _company_with_manager(run, **overrides):
    return dataclasses.replace(run.h.company, manager_id=MANAGER_ID, **overrides)


# --- F1: đúc task cho Manager rồi chạy thật -----------------------------------------


@pytest.mark.live_slow
def test_f1_an_escalation_mints_a_manager_task_that_really_runs(live_run):
    """Yêu cầu vượt thẩm quyền → task một bước cho Manager, chạy tới trạng thái cuối.

    Đây là case chứng minh cái vehicle không-decompose thật sự dùng được: hash tự đặt
    phải khớp với hash mà ticker tính lại, nếu không việc kẹt ở tick một. Assert vào bản
    ghi: đúng một task, PIC là Manager, route mang dấu `origin=escalation`, và sau khi
    pump thì bước đã rời khỏi trạng thái chờ."""
    run = live_run()
    task_id = escalate_to_manager(
        source="customer_assistant",
        summary="Khách yêu cầu hoàn tiền vượt hạn mức tự quyết của trợ lý.",
        context_ref="cust-4821",
        company=_company_with_manager(run),
    )
    assert task_id, "escalation với manager hợp lệ phải đúc được task"

    rows = run.h.task_rows()
    assert [r["id"] for r in rows] == [task_id], rows

    route = run.route(task_id)
    assert route.get("origin") == "escalation", route
    assert route.get("source") == "customer_assistant", route
    assert route.get("context_ref") == "cust-4821", route

    steps = run.h.step_rows(task_id)
    assert len(steps) == 1, f"escalation là vehicle MỘT bước: {steps}"
    assert steps[0]["assigned_to"] == MANAGER_ID, steps

    run.h.pump(ticks=3)
    after = run.h.step_rows(task_id)
    assert after[0]["status"] != "pending", (
        "kế hoạch tự đặt phải qua được `_verify_plan_hash` — bước vẫn `pending` sau 3 "
        f"tick nghĩa là hash không khớp và việc kẹt: {after}"
    )

    # KHÔNG assert `cost() > 0`. Đo thật, hai lần chạy ra hai đường đều đúng: có lần
    # Manager làm xong việc (task `done`, có chi phí), có lần Manager thấy đây là quyết
    # định của người nên hỏi lại và bước đỗ ở chờ-trả-lời (chi phí 0, vì lượt hỏi không
    # tính vào sổ của task). Với một đề "hoàn tiền vượt hạn mức", hỏi lại là hành vi
    # ĐÚNG — buộc phải có chi phí sẽ biến một phán đoán tốt thành test đỏ.
    # Thứ phải luôn đúng, và là thứ case này tồn tại để đo, là bước đã được ticker nhặt
    # lên: hash tự đặt khớp với hash tính lại.


# --- F2/F3/F4: ba cái phanh ----------------------------------------------------------


def test_f2_an_escalation_task_can_never_escalate_again(live_run):
    """Phanh đệ quy: task do escalation đúc ra không được escalate tiếp.

    Không có phanh này, một Manager gặp việc khó sẽ đúc ra một task Manager nữa, lặp vô
    hạn. Đo bằng chính route mà F1 ghi ra, không phải bằng một dict tự bịa."""
    run = live_run()
    first = escalate_to_manager(
        source="customer_assistant", summary="Yêu cầu vượt thẩm quyền lần một.",
        company=_company_with_manager(run),
    )
    assert first, "case này cần một escalation thành công trước đã"

    origin_route = run.route(first)
    assert is_escalation_origin(origin_route), origin_route

    second = escalate_to_manager(
        source="customer_assistant", summary="Yêu cầu vượt thẩm quyền lần hai.",
        origin_route=origin_route, company=_company_with_manager(run),
    )
    assert second is None, "escalation từ trong một task escalation phải bị từ chối"
    assert len(run.h.task_rows()) == 1, "không được đúc thêm task nào"


def test_f3_the_daily_cap_stops_an_escalation_storm(live_run, tmp_path):
    """Phanh trần ngày: quá hạn mức thì degrade về báo người, không đúc thêm.

    Sidecar được trỏ vào file riêng của case để không phụ thuộc số đếm của các case
    khác chạy cùng ngày."""
    run = live_run()
    sidecar = tmp_path / "cap.json"
    company = _company_with_manager(run, escalation_daily_cap=1)

    first = escalate_to_manager(
        source="customer_assistant", summary="Việc thứ nhất trong ngày.",
        company=company, sidecar_path=sidecar,
    )
    assert first, "việc đầu tiên vẫn phải qua khi trần là 1"

    second = escalate_to_manager(
        source="customer_assistant", summary="Việc thứ hai trong ngày.",
        company=company, sidecar_path=sidecar,
    )
    assert second is None, "vượt trần ngày phải bị từ chối"
    assert len(run.h.task_rows()) == 1, "chỉ được đúc đúng một task"


def test_f4_an_unassignable_manager_degrades_instead_of_minting(live_run):
    """Phanh roster: Manager không nhận việc được thì degrade, không đúc task treo.

    Đây chính là cấu hình MẶC ĐỊNH của một fleet chưa đặt `manager_id` — chuỗi fallback
    rơi về điều phối viên, mà điều phối viên bị loại khỏi danh sách nhận việc. Đúc một
    task cho người không bao giờ nhận được nó tệ hơn là không đúc: nó im lặng và không
    ai biết."""
    run = live_run()
    task_id = escalate_to_manager(
        source="customer_assistant",
        summary="Yêu cầu vượt thẩm quyền khi chưa cấu hình manager.",
        company=run.h.company,
    )
    assert task_id is None, (
        "manager rơi về điều phối viên (không nhận việc được) phải degrade về báo người"
    )
    assert run.h.task_rows() == [], "không được để lại task treo nào"
