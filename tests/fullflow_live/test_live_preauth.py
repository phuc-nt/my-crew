"""Nhóm F — tiền duyệt ở bước xác nhận kế hoạch ("duyệt tất cả") với model thật.

Cái suite scripted KHÔNG chứng minh được: manifest tiền duyệt được dựng từ một kế hoạch
mà model thật sinh ra (cờ ngoài/trong công ty suy từ bước thật), và `preauth_scope` chỉ
được ghi SAU KHI confirm thật đi qua ràng buộc hash. Nửa còn lại — ticker tự duyệt cổng
Lớp B nhân danh CEO rồi học luật `ceo:preauth` vào kho luật của CHÍNH agent nhận bước —
là xác định (không cần model), nên được dựng bằng một dòng phê duyệt thật trong
`ApprovalStore` của agent đó và một lần pump.

Case chỉ trả tiền cho một lượt decompose + tối đa vài tick spawn; không chờ việc xong.
"""

from __future__ import annotations

import pytest

from my_crew.actions.approval_rule_store import SCOPE_ALWAYS, ApprovalRuleStore
from my_crew.actions.approval_store import ApprovalStore
from my_crew.runtime.agent_paths import agent_data_dir

_BRIEF = (
    "Soạn giúp anh email thông báo lịch bảo trì hệ thống cuối tuần này cho khách hàng, "
    "rồi gửi cho danh sách khách đang dùng gói doanh nghiệp."
)
_QUEUED_ACTION = {"type": "email_send", "to": "khach-doanh-nghiep@example.com"}


def _preview(brief: str) -> dict:
    from my_crew.server.routes_office_assign import post_preview

    return post_preview(brief=brief, room_id="")


def _confirm(task_id: str, plan_hash: str, scope: str) -> dict:
    from my_crew.server.routes_office_assign import post_confirm

    return post_confirm(task_id=task_id, plan_hash=plan_hash, preauth_scope=scope)


@pytest.mark.live_slow
def test_f1_confirm_with_always_records_scope_then_ticker_approves_and_learns(live_run):
    """Preview thật → confirm `always` → cổng Lớp B của bước đầu được ticker duyệt nhân
    danh CEO và hành động thật được ghi thành luật ALWAYS cho agent nhận bước."""
    run = live_run()
    preview = _preview(_BRIEF)
    task_id, plan_hash = preview["task_id"], preview["plan_hash"]
    assert task_id and plan_hash, preview

    manifest = preview["manifest"]
    assert manifest["steps"], "kế hoạch thật phải có ít nhất một bước trong manifest"
    for step in manifest["steps"]:
        assert step["step_id"] and step["title"] and step["assigned_to"], step
        for flag in ("external_write", "needs_shell", "needs_web", "needs_mail", "needs_review"):
            assert isinstance(step[flag], bool), step
    assert manifest["external_count"] == sum(
        1 for s in manifest["steps"] if s["external_write"]
    ), manifest
    assert [s["step_id"] for s in manifest["steps"]] == [
        s["step_id"] for s in run.h.step_rows(task_id)
    ], "manifest phải liệt kê đúng các bước của kế hoạch vừa preview"

    out = _confirm(task_id, plan_hash, "always")
    assert out["preauth_scope"] == "always", out
    store = run.h.store()
    try:
        assert store.get(task_id).preauth_scope == "always"
    finally:
        store.close()

    steps = run.h.step_rows(task_id)
    first = steps[0]
    agent = first["assigned_to"]
    assert agent, first
    approvals = ApprovalStore(agent_data_dir(agent) / "approvals.db")
    try:
        approval_id = approvals.enqueue(
            _QUEUED_ACTION, reason="gửi email ra ngoài công ty", actor=agent,
        )
    finally:
        approvals.close()
    store = run.h.store()
    try:
        attempt = store.reserve_step(task_id, first["step_id"])
        assert store.mark_awaiting_approval(
            task_id, first["step_id"], attempt_id=attempt, approval_id=approval_id,
        )
    finally:
        store.close()

    run.h.pump(ticks=1)

    approvals = ApprovalStore(agent_data_dir(agent) / "approvals.db")
    try:
        row = approvals.get(approval_id)
    finally:
        approvals.close()
    assert row is not None and row.status == "approved", row
    after = {s["step_id"]: s["status"] for s in run.h.step_rows(task_id)}
    assert after[first["step_id"]] != "awaiting_approval", after

    rules = ApprovalRuleStore(agent_data_dir(agent) / "approvals.db")
    try:
        learned = rules.list_rules()
        matched = rules.match(_QUEUED_ACTION)
    finally:
        rules.close()
    assert [(r.scope, r.created_by) for r in learned] == [(SCOPE_ALWAYS, "ceo:preauth")], learned
    assert matched is not None and matched.scope == SCOPE_ALWAYS, learned

    # Luật chỉ nằm trong kho của agent nhận bước — agent khác không thừa hưởng.
    others = {s["assigned_to"] for s in steps} - {agent}
    for other in others:
        other_rules = ApprovalRuleStore(agent_data_dir(other) / "approvals.db")
        try:
            assert other_rules.list_rules() == [], other
        finally:
            other_rules.close()
    assert run.cost() > 0, "decompose bằng model thật phải ghi lại chi phí thật"


def test_f2_confirm_with_once_records_scope_without_a_rule(live_run):
    """`once` cũng được ghi vào việc, nhưng sau khi ticker duyệt cổng thì KHÔNG có luật
    nào được học — nửa "chỉ việc này" của nút."""
    run = live_run()
    preview = _preview("Tóm tắt giúp anh 3 điểm chính của báo cáo doanh thu quý vừa rồi.")
    task_id, plan_hash = preview["task_id"], preview["plan_hash"]
    assert task_id and plan_hash, preview

    assert _confirm(task_id, plan_hash, "once")["preauth_scope"] == "once"
    store = run.h.store()
    try:
        assert store.get(task_id).preauth_scope == "once"
    finally:
        store.close()

    first = run.h.step_rows(task_id)[0]
    agent = first["assigned_to"]
    approvals = ApprovalStore(agent_data_dir(agent) / "approvals.db")
    try:
        approval_id = approvals.enqueue(_QUEUED_ACTION, reason="gửi email", actor=agent)
    finally:
        approvals.close()
    store = run.h.store()
    try:
        attempt = store.reserve_step(task_id, first["step_id"])
        store.mark_awaiting_approval(
            task_id, first["step_id"], attempt_id=attempt, approval_id=approval_id,
        )
    finally:
        store.close()

    run.h.pump(ticks=1)

    approvals = ApprovalStore(agent_data_dir(agent) / "approvals.db")
    try:
        assert approvals.get(approval_id).status == "approved"
    finally:
        approvals.close()
    rules = ApprovalRuleStore(agent_data_dir(agent) / "approvals.db")
    try:
        assert rules.list_rules() == []
    finally:
        rules.close()


def test_f3_confirm_rejects_an_unknown_scope_before_touching_the_plan(live_run):
    """Scope lạ bị chặn ở 400 và việc KHÔNG được confirm — kế hoạch vẫn ở trạng thái
    preview, nên một client cũ gửi giá trị sai không thể vô tình giao việc."""
    from fastapi import HTTPException

    run = live_run()
    preview = _preview("Liệt kê giúp anh các bước để đăng ký nhãn hiệu.")
    task_id, plan_hash = preview["task_id"], preview["plan_hash"]
    assert task_id and plan_hash, preview

    with pytest.raises(HTTPException) as exc:
        _confirm(task_id, plan_hash, "forever")
    assert exc.value.status_code == 400
    assert run.h.task_rows() == [] or all(
        r["status"] not in ("open", "running") for r in run.h.task_rows()
    ), run.h.task_rows()
    store = run.h.store()
    try:
        assert store.get(task_id).preauth_scope == ""
    finally:
        store.close()
