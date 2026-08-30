"""Bảng thống kê theo làn: đọc bản ghi định tuyến của cả đội thành số.

Fixture dựng bằng ĐÚNG API store mà production dùng (`create_task`/`set_plan`/
`set_route`/`mark_done`/`set_delivery`), không phải bằng INSERT tay. Viết SQL tay vào
bảng fixture nghĩa là test tự định nghĩa lấy schema của nó: đổi cột thật thì fixture vẫn
xanh trong khi hàm đọc đã hỏng.
"""

from __future__ import annotations

from my_crew.bench.task_metrics import load_lane_stats
from my_crew.runtime.team_task_store import TeamTaskStore


def _task(store, task_id, *, route, cost, delivered, step_type="sprint"):
    store.create_task(task_id=task_id, title=task_id, original_request="đề",
                      assigned_by="ceo", pic_id="content")
    store.set_plan(task_id, [{
        "step_id": "s1", "title": "làm", "assigned_to": "content",
        "deps": [], "acceptance": "- xong", "step_type": step_type,
    }], f"hash-{task_id}")
    if route is not None:
        store.set_route(task_id, route)
    store.mark_done(task_id, "s1", outcome_ref="ref", cost_usd=cost)
    store.set_delivery(task_id, status="delivered" if delivered else "failed")


def _fixture(tmp_path):
    """Một cửa hàng phủ ĐỦ mọi `source` bộ định tuyến có thể ghi, cộng một task đời
    trước không có bản ghi định tuyến."""
    db = tmp_path / "fleet.db"
    store = TeamTaskStore(db)
    try:
        _task(store, "sp-heur-1", cost=0.02, delivered=True,
              route={"mode": "sprint", "source": "heuristic", "reason": "r",
                     "signals": {"brief_len": 40, "entities": 2, "distinct_asks": 1},
                     "effort": "low", "effort_high": False})
        _task(store, "sp-heur-2", cost=0.04, delivered=True,
              route={"mode": "sprint", "source": "heuristic", "reason": "r",
                     "signals": {"brief_len": 60, "entities": 3, "distinct_asks": 1},
                     "effort": "medium", "effort_high": False})
        _task(store, "sp-prefix", cost=0.06, delivered=False,
              route={"mode": "sprint", "source": "prefix", "reason": "r",
                     "signals": {}, "effort": "high", "effort_high": True})
        _task(store, "sp-dead", cost=0.03, delivered=False,
              route={"mode": "team", "source": "heuristic", "dead_end": True,
                     "reason": "r", "signals": {}, "previous": "sp-heur-1"},
              step_type="content")
        _task(store, "tm-refusal", cost=0.30, delivered=True,
              route={"mode": "team", "source": "refusal", "reason": "r",
                     "signals": {}}, step_type="content")
        _task(store, "tm-down", cost=0.20, delivered=True,
              route={"mode": "team", "source": "downgrade", "reason": "r",
                     "signals": {}}, step_type="content")
        _task(store, "tm-up", cost=0.40, delivered=True,
              route={"mode": "team", "source": "upgrade", "reason": "r",
                     "signals": {}, "previous_task": "sp-dead"}, step_type="content")
        _task(store, "legacy", cost=0.10, delivered=True, route=None,
              step_type="content")
    finally:
        store.close()
    return db


def test_every_router_source_lands_in_its_lane(tmp_path):
    stats = load_lane_stats(_fixture(tmp_path))
    lanes = stats["lanes"]

    assert stats["total_tasks"] == 8
    assert lanes["sprint"].sources == {"heuristic": 2, "prefix": 1}
    assert lanes["team"].sources == {"dead_end": 1, "downgrade": 1,
                                     "refusal": 1, "upgrade": 1}


def test_a_task_with_no_route_record_is_unknown_never_guessed(tmp_path):
    """Task đời trước v77 không có bản ghi định tuyến. Đoán làn từ hình dạng DAG sẽ
    gộp lặng lẽ đống task team cũ vào con số mới và làm bảng so bản sai lệch."""
    lanes = load_lane_stats(_fixture(tmp_path))["lanes"]
    assert lanes["unknown"].tasks == 1
    assert lanes["unknown"].sources == {"unknown": 1}
    assert "legacy" not in {la.lane for la in lanes.values()}


def test_delivery_rate_and_cost_per_task_are_per_lane(tmp_path):
    """Chi phí phải chia theo SỐ TASK của chính làn đó. Chia cho tổng cả đội sẽ làm
    làn đắt trông rẻ đi đúng theo tỉ lệ làn rẻ chạy nhiều bao nhiêu."""
    lanes = load_lane_stats(_fixture(tmp_path))["lanes"]

    assert lanes["sprint"].tasks == 3
    assert lanes["sprint"].delivered == 2
    assert lanes["sprint"].delivery_rate == round(2 / 3, 2)
    assert abs(lanes["sprint"].cost_usd - 0.12) < 1e-6
    assert abs(lanes["sprint"].cost_per_task - 0.04) < 1e-6

    assert lanes["team"].tasks == 4
    assert abs(lanes["team"].cost_usd - 0.93) < 1e-6


def test_the_three_miss_rates_are_measured_over_routed_tasks_only(tmp_path):
    """Ba tỉ lệ này là cách duy nhất thấy bộ định tuyến sai: dead_end = chọn sprint cho
    việc sprint không làm nổi, downgrade = lưới an toàn phải đỡ, upgrade = một dead_end
    đã bị trả tiền làm lại lần hai.

    Mẫu số là 7 việc CÓ định tuyến, không phải 8 việc trong store: việc đời trước v77
    nằm ở lane `unknown` vì router chưa từng quyết định gì về nó (xem bài
    `test_tasks_without_a_route_record_are_reported_as_unknown`). Đưa nó vào mẫu số thì
    ba tỉ lệ này giảm dần theo bề dày lịch sử của store — chỉ tích thêm việc cũ là bảng
    so bản đã "cải thiện" mà bộ định tuyến không đổi một dòng nào.
    """
    stats = load_lane_stats(_fixture(tmp_path))
    assert stats["total_tasks"] == 8
    assert stats["routed_tasks"] == 7
    assert stats["rates"] == {"dead_end": round(1 / 7, 3), "downgrade": round(1 / 7, 3),
                              "upgrade": round(1 / 7, 3)}


def test_an_empty_store_reports_no_rates_instead_of_dividing_by_zero(tmp_path):
    db = tmp_path / "empty.db"
    TeamTaskStore(db).close()
    stats = load_lane_stats(db)
    assert stats["total_tasks"] == 0
    assert stats["lanes"] == {}
    assert set(stats["rates"].values()) == {None}


def test_a_corrupt_route_record_is_counted_not_crashed_on(tmp_path):
    """Bản ghi định tuyến là dữ liệu quan sát. Một dòng JSON hỏng làm sập cả bảng
    thống kê nghĩa là mất luôn số của 500 task lành vì một task hỏng."""
    db = tmp_path / "bad.db"
    store = TeamTaskStore(db)
    try:
        _task(store, "ok", route={"mode": "sprint", "source": "heuristic"},
              cost=0.01, delivered=True)
        store._conn.execute(
            "UPDATE team_tasks SET route_json = ? WHERE id = ?", ("{ hỏng", "ok"))
        store._conn.commit()
    finally:
        store.close()

    lanes = load_lane_stats(db)["lanes"]
    assert lanes["unknown"].tasks == 1


def test_the_window_limit_keeps_the_newest_tasks(tmp_path):
    """`--limit` là cửa sổ "gần đây", nên nó phải cắt phần CŨ. Cắt nhầm đầu mới thì
    bảng đo bản cũ của chính mình."""
    stats = load_lane_stats(_fixture(tmp_path), limit=3)
    assert stats["total_tasks"] == 3
